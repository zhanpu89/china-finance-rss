#!/usr/bin/env python3
"""SSE-only limit benchmark. Group A: 50 codes x quote. Group B: 50 codes x 3 fields.

Run: python3 doc/tester/sse_bench.py [duration_seconds]
Writes /tmp/sse_bench_out.json (or SSE_BENCH_OUT).
"""
import json, os, sys, time, threading, http.client, socket

HOST = 'localhost'
STREAM_PORT = 8054
MAIN_PORT = 8053
OUT = os.environ.get('SSE_BENCH_OUT', '/tmp/sse_bench_out.json')

CODES = json.load(open(os.environ.get('SSE_BENCH_CODES', 'doc/tester/sse_codes50.json')))


def api(method, path, body=None, port=STREAM_PORT, timeout=30):
    c = http.client.HTTPConnection(HOST, port, timeout=timeout)
    hdr = {'Content-Type': 'application/json'} if body is not None else {}
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdr)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw) if raw else {}
    except Exception:
        return r.status, raw.decode('utf-8', 'replace')


def health():
    try:
        c = http.client.HTTPConnection(HOST, MAIN_PORT, timeout=10)
        c.request('GET', '/healthz?check=0')
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return d.get('metrics', d)
    except Exception as e:
        return {'_health_error': str(e)}


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples = []
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            t = time.time()
            m = health()
            self.samples.append((t, m))
            self.stop.wait(2.0)


def sse_run(sid, duration, label):
    rec = {'label': label, 'sid': sid, 'frames': [], 'errors': [], 'start': None, 'end': None}
    sock = socket.create_connection((HOST, STREAM_PORT), timeout=30)
    sock.settimeout(duration + 30)
    req = (f"GET /stream/quote/{sid} HTTP/1.1\r\nHost: {HOST}\r\n"
           f"Accept: text/event-stream\r\nConnection: close\r\n\r\n")
    sock.sendall(req.encode())
    buf = b''
    while b'\r\n\r\n' not in buf:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b'\r\n\r\n')
    rec['headers'] = head.decode('utf-8', 'replace').splitlines()[0] if head else ''
    cur = rest
    deadline = time.time() + duration
    t0 = time.time()
    rec['start'] = t0
    while time.time() < deadline:
        while b'\n\n' in cur:
            block, _, cur = cur.partition(b'\n\n')
            txt = block.decode('utf-8', 'replace').strip()
            if not txt:
                continue
            now = time.time()
            ev = {'t': now}
            for line in txt.splitlines():
                if line.startswith('event:'):
                    ev['event'] = line[6:].strip()
                elif line.startswith('data:'):
                    ev['data'] = line[5:].strip()
            if ev.get('event') == 'quote' and 'data' in ev:
                try:
                    d = json.loads(ev['data'])
                except Exception as e:
                    rec['errors'].append(f'json {e}')
                    continue
                items = d.get('items') or {}
                nonnull = {c: [f for f, v in (row or {}).items() if v is not None]
                           for c, row in items.items()}
                ev['codes_total'] = d.get('codes_total')
                ev['items_n'] = len(items)
                ev['missing_count'] = d.get('missing_count')
                ev['stale_count'] = d.get('stale_count', 0)
                ev['fields'] = d.get('fields')
                ev['nonnull_codes'] = sum(1 for v in nonnull.values() if v)
                ev['data_codes'] = {c: v for c, v in nonnull.items() if v}
                ev['frame_bytes'] = len(ev['data'])
                ev['ts'] = d.get('ts')
                rec['frames'].append(ev)
            elif ev.get('event') == 'ping':
                rec['frames'].append({'t': now, 'event': 'ping'})
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        except OSError as e:
            rec['errors'].append(f'recv {e}')
            break
        if not chunk:
            rec['errors'].append('closed by server')
            break
        cur += chunk
    rec['end'] = time.time()
    try:
        sock.close()
    except Exception:
        pass
    return rec


def analyze(rec, fields):
    fr = [f for f in rec['frames'] if f.get('event') == 'quote']
    out = {'label': rec['label'], 'sid': rec['sid'], 'headers': rec.get('headers'),
           'errors': rec['errors'], 'n_quote_frames': len(fr),
           'n_ping': sum(1 for f in rec['frames'] if f.get('event') == 'ping')}
    if not fr:
        return out
    ts = [f['t'] for f in fr]
    iv = [round(b - a, 2) for a, b in zip(ts, ts[1:])]
    out['intervals'] = iv
    out['interval_min'] = min(iv) if iv else None
    out['interval_max'] = max(iv) if iv else None
    out['interval_avg'] = round(sum(iv) / len(iv), 2) if iv else None
    out['codes_total'] = [f.get('codes_total') for f in fr]
    out['items_n'] = [f.get('items_n') for f in fr]
    out['missing_count'] = [f.get('missing_count') for f in fr]
    out['stale_count'] = [f.get('stale_count') for f in fr]
    out['nonnull_codes'] = [f.get('nonnull_codes') for f in fr]
    out['frame_bytes'] = [f.get('frame_bytes') for f in fr]
    full = [f for f in fr if (f.get('missing_count') == 0 and f.get('nonnull_codes') == f.get('codes_total'))]
    out['first_full_frame_s'] = round(full[0]['t'] - rec['start'], 2) if full else None
    out['n_full_frames'] = len(full)
    per = {}
    for f in fr:
        for c, fl in (f.get('data_codes') or {}).items():
            per.setdefault(c, {}).setdefault('all', []).append(f['t'])
            for fn in fl:
                per[c].setdefault(fn, []).append(f['t'])
    win = rec['end'] - rec['start']
    stats = {}
    for c, d in per.items():
        gaps = [round(b - a, 2) for a, b in zip(d['all'], d['all'][1:])]
        stats[c] = {
            'appearances': len(d['all']),
            'period_s': round(win / len(d['all']), 2) if d['all'] else None,
            'max_gap_s': max(gaps) if gaps else None,
            'fields': {fn: len(v) for fn, v in d.items() if fn != 'all'},
        }
    out['per_code'] = stats
    out['n_codes_seen'] = len(stats)
    periods = [v['period_s'] for v in stats.values() if v['period_s']]
    maxgaps = [v['max_gap_s'] for v in stats.values() if v['max_gap_s']]
    out['period_avg'] = round(sum(periods) / len(periods), 2) if periods else None
    out['period_max'] = max(periods) if periods else None
    out['max_gap_worst'] = max(maxgaps) if maxgaps else None
    if fields:
        for fn in fields:
            cnts = [v['fields'].get(fn, 0) for v in stats.values()]
            out[f'field_{fn}_min_refreshes'] = min(cnts) if cnts else 0
            out[f'field_{fn}_avg_period_s'] = round(win / (sum(cnts) / len(cnts)), 2) if cnts and sum(cnts) else None
    out['window_s'] = round(win, 2)
    return out


def delta(a, b, keys):
    out = {}
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out[k] = {kk: vb.get(kk, 0) - va.get(kk, 0) for kk in sorted(set(va) | set(vb))}
        elif isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            out[k] = round(vb - va, 3)
        else:
            out[k] = {'before': va, 'after': vb}
    return out


DELTA_KEYS = ['stream_tick_degraded_total', 'stream_tick_slip_total',
              'stream_frame_dropped_total', 'stream_slow_client_total',
              'http_503_total', 'upstream_fetch_total', 'upstream_fail_total']

AFTER_KEYS = ['stream_tick_duration_ms', 'stream_refresh_lag_ticks',
              'stream_frame_dropped_total', 'stream_frame_distinct',
              'stream_frame_peak_bytes', 'stream_queue_bytes',
              'stream_tick_degraded_total', 'stream_tick_slip_total',
              'http_503_total', 'upstream_fetch_total', 'upstream_fail_total']


def run_case(label, fields, duration):
    print(f'\n===== {label}: {len(CODES)} codes, fields={fields}, duration={duration}s =====', flush=True)
    m0 = health()
    st, resp = api('POST', '/stream/subscriptions', {'codes': CODES, 'fields': fields})
    print('CREATE', st, json.dumps(resp, ensure_ascii=False)[:500], flush=True)
    sid = resp.get('sid') if isinstance(resp, dict) else None
    if not sid:
        return {'label': label, 'create_failed': resp, 'create_status': st}
    time.sleep(1.0)
    st2, gstat = api('GET', f'/stream/subscriptions/{sid}')
    sampler = Sampler()
    sampler.start()
    rec = sse_run(sid, duration, label)
    sampler.stop.set()
    sampler.join(timeout=5)
    m1 = health()
    an = analyze(rec, fields)
    an['create'] = resp
    an['create_status'] = st
    an['group_status'] = gstat
    tick_ms = [s[1].get('stream_tick_duration_ms') for s in sampler.samples]
    lag = [s[1].get('stream_refresh_lag_ticks') for s in sampler.samples]
    an['tick_ms_samples'] = tick_ms
    an['lag_samples'] = lag
    an['tick_ms_max'] = max([x for x in tick_ms if isinstance(x, (int, float))] or [None])
    an['lag_max'] = max([x for x in lag if isinstance(x, (int, float))] or [None])
    an['metrics_delta'] = delta(m0, m1, DELTA_KEYS)
    an['metrics_after'] = {k: m1.get(k) for k in AFTER_KEYS}
    an['duration'] = duration
    an['window_s'] = round(rec['end'] - rec['start'], 2)
    fetch = an['metrics_delta'].get('upstream_fetch_total') or {}
    if isinstance(fetch, dict) and an.get('window_s'):
        an['fetch_rate_per_s'] = {k: round(v / an['window_s'], 2) for k, v in fetch.items()}
    print('RESULT', json.dumps({k: v for k, v in an.items() if k != 'per_code'}, ensure_ascii=False)[:3000], flush=True)
    st3, dresp = api('DELETE', f'/stream/subscriptions/{sid}')
    print('DELETE', st3, json.dumps(dresp, ensure_ascii=False)[:200], flush=True)
    an['delete_status'] = st3
    return an


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    out = {'codes': CODES, 'n_codes': len(CODES)}
    out['A'] = run_case('A_quote_50', ['quote'], duration)
    time.sleep(3)
    out['B'] = run_case('B_3field_50', ['quote', 'fundflow', 'timeline'], duration)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'\nWROTE {OUT}', flush=True)


if __name__ == '__main__':
    main()
