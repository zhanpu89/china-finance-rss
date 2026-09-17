#!/usr/bin/env python3
"""In-session acceptance: 4A quote 50c <=4s, 4B 3-domain 50c <=8s, 4C depth fields.

Writes JSON summary to doc/tester/sse_depth_out.json and prints compact
per-stage results.  Read-only: only SSE + subscription CRUD.
"""
import json, os, sys, time, threading, http.client, socket

HOST = 'localhost'
STREAM_PORT = 8054
MAIN_PORT = 8053
OUT = 'doc/tester/sse_depth_out.json'
CODES = json.load(open('doc/tester/sse_codes50.json'))

DEPTH_VALUE_FIELDS = [f'{s}_{k}_{i}' for s in ('b', 's') for k in ('px', 'amount') for i in range(1, 6)]


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
            self.samples.append((time.time(), health()))
            self.stop.wait(2.0)


def sse_run(sid, duration, keep_raw_depth_for=None):
    rec = {'sid': sid, 'frames': [], 'errors': [], 'start': None, 'end': None,
           'raw_depth_sample': {}, 'bytes_total': 0, 'bytes_max_frame': 0,
           'depth_present': {}, 'depth_zero_only': [], 'last_items': {}}
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
    _, _, cur = buf.partition(b'\r\n\r\n')
    deadline = time.time() + duration
    rec['start'] = time.time()
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
                fb = len(ev['data'].encode('utf-8'))
                rec['bytes_total'] += fb
                rec['bytes_max_frame'] = max(rec['bytes_max_frame'], fb)
                items = d.get('items') or {}
                nonnull = {c: bool([f for f, v in (row or {}).items() if v is not None])
                           for c, row in items.items()}
                ev.update(codes_total=d.get('codes_total'), items_n=len(items),
                          missing_count=d.get('missing_count'), stale_count=d.get('stale_count', 0),
                          fields=d.get('fields'), nonnull_codes=sum(1 for v in nonnull.values() if v),
                          frame_bytes=fb, ts=d.get('ts'))
                for c, row in items.items():
                    q = (row or {}).get('quote')
                    has = isinstance(q, dict) and 'depth' in q
                    rec['depth_present'].setdefault(c, {'present': 0, 'absent': 0})
                    rec['depth_present'][c]['present' if has else 'absent'] += 1
                    if has:
                        dep = q['depth']
                        if not isinstance(dep, dict) or all(not dep.get(f) for f in DEPTH_VALUE_FIELDS):
                            if c not in rec['depth_zero_only']:
                                rec['depth_zero_only'].append(c)
                    if keep_raw_depth_for and c in keep_raw_depth_for and has \
                            and c not in rec['raw_depth_sample']:
                        rec['raw_depth_sample'][c] = q['depth']
                    rec['last_items'][c] = sorted((row or {}).get('quote', {}).keys()) if isinstance((row or {}).get('quote'), dict) else None
                rec['frames'].append(ev)
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


def analyze(rec):
    fr = [f for f in rec['frames'] if f.get('event') == 'quote']
    out = {'n_quote_frames': len(fr), 'errors': rec['errors'],
           'n_ping': sum(1 for f in rec['frames'] if f.get('event') == 'ping'),
           'bytes_max_frame': rec['bytes_max_frame'],
           'bytes_avg_frame': round(rec['bytes_total'] / len(fr), 1) if fr else None}
    if not fr:
        return out
    ts = [f['t'] for f in fr]
    iv = [round(b - a, 2) for a, b in zip(ts, ts[1:])]
    out.update(intervals=iv,
               interval_min=min(iv) if iv else None,
               interval_max=max(iv) if iv else None,
               interval_avg=round(sum(iv) / len(iv), 2) if iv else None,
               codes_total=[f.get('codes_total') for f in fr],
               missing_count=[f.get('missing_count') for f in fr],
               stale_count=[f.get('stale_count') for f in fr],
               items_n=[f.get('items_n') for f in fr],
               nonnull_codes=[f.get('nonnull_codes') for f in fr],
               frame_bytes=[f.get('frame_bytes') for f in fr])
    full = [f for f in fr if f.get('missing_count') == 0 and f.get('nonnull_codes') == f.get('codes_total')]
    out['first_full_frame_s'] = round(full[0]['t'] - rec['start'], 2) if full else None
    out['first_frame_s'] = round(fr[0]['t'] - rec['start'], 2)
    out['frames_head'] = [{'t_rel': round(f['t'] - rec['start'], 2), 'missing': f.get('missing_count'),
                           'stale': f.get('stale_count'), 'nonnull': f.get('nonnull_codes'),
                           'items_n': f.get('items_n'), 'bytes': f.get('frame_bytes')} for f in fr[:8]]
    out['n_full_frames'] = len(full)
    out['window_s'] = round(rec['end'] - rec['start'], 2)
    dp = rec['depth_present']
    out['n_codes_with_depth'] = sum(1 for v in dp.values() if v['present'] > 0)
    out['n_codes_without_depth'] = sum(1 for v in dp.values() if v['present'] == 0 and v['absent'] > 0)
    out['depth_zero_only_codes'] = rec['depth_zero_only']
    return out


def run_case(label, fields, duration, keep_raw_depth_for=None):
    print(f'\n===== {label}: {len(CODES)} codes, fields={fields}, {duration}s =====', flush=True)
    m0 = health()
    st, resp = api('POST', '/stream/subscriptions', {'codes': CODES, 'fields': fields})
    print('CREATE', st, json.dumps(resp, ensure_ascii=False)[:600], flush=True)
    sid = resp.get('sid') if isinstance(resp, dict) else None
    if not sid:
        return {'label': label, 'create_failed': resp, 'create_status': st}
    time.sleep(1.0)
    _, gstat = api('GET', f'/stream/subscriptions/{sid}')
    sampler = Sampler()
    sampler.start()
    rec = sse_run(sid, duration, keep_raw_depth_for)
    sampler.stop.set()
    sampler.join(timeout=5)
    m1 = health()
    an = analyze(rec)
    an['create'] = resp
    an['group_status'] = gstat
    tick_ms = [s[1].get('stream_tick_duration_ms') for s in sampler.samples]
    lag = [s[1].get('stream_refresh_lag_ticks') for s in sampler.samples]
    an['tick_ms_samples'] = tick_ms
    an['lag_samples'] = lag
    num = [x for x in tick_ms if isinstance(x, (int, float))]
    an['tick_ms_max'] = max(num) if num else None
    an['tick_ms_avg'] = round(sum(num) / len(num), 1) if num else None
    lagv = [x for x in lag if isinstance(x, (int, float))]
    an['lag_max'] = max(lagv) if lagv else None
    keys = ['stream_tick_degraded_total', 'stream_tick_slip_total', 'stream_frame_dropped_total',
            'stream_slow_client_total', 'http_503_total', 'upstream_fetch_total', 'upstream_fail_total']
    d = {}
    for k in keys:
        va, vb = m0.get(k), m1.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            d[k] = {kk: vb.get(kk, 0) - va.get(kk, 0) for kk in sorted(set(va) | set(vb))}
        else:
            d[k] = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else {'before': va, 'after': vb}
    an['metrics_delta'] = d
    an['metrics_after'] = {k: m1.get(k) for k in
                           ['stream_tick_duration_ms', 'stream_refresh_lag_ticks',
                            'stream_frame_peak_bytes', 'stream_queue_bytes', 'stream_frame_distinct',
                            'stream_slow_client_total', 'stream_frame_dropped_total']}
    if an.get('window_s'):
        fetch = d.get('upstream_fetch_total') or {}
        if isinstance(fetch, dict):
            an['fetch_rate_per_s'] = {k: round(v / an['window_s'], 2) for k, v in fetch.items()}
    print('RESULT', json.dumps(an, ensure_ascii=False)[:3500], flush=True)
    print('RAW_DEPTH', json.dumps(rec['raw_depth_sample'], ensure_ascii=False)[:2500], flush=True)
    print('LAST_ITEM_KEYS', json.dumps({k: rec['last_items'].get(k) for k in (keep_raw_depth_for or [])},
                                       ensure_ascii=False)[:1500], flush=True)
    st3, dresp = api('DELETE', f'/stream/subscriptions/{sid}')
    print('DELETE', st3, json.dumps(dresp, ensure_ascii=False)[:150], flush=True)
    an['delete_status'] = st3
    an['raw_depth_sample'] = rec['raw_depth_sample']
    an['last_item_keys'] = {k: rec['last_items'].get(k) for k in (keep_raw_depth_for or [])}
    return an


def probe_depth():
    codes = ['sh600519', 'bj430047', 'sh000001']
    print(f'\n===== 4C depth probe: {codes}, quote, 16s =====', flush=True)
    st, resp = api('POST', '/stream/subscriptions', {'codes': codes, 'fields': ['quote']})
    print('CREATE', st, json.dumps(resp, ensure_ascii=False)[:400], flush=True)
    sid = resp.get('sid') if isinstance(resp, dict) else None
    if not sid:
        return {'create_failed': resp}
    rec = sse_run(sid, 16, keep_raw_depth_for=set(codes))
    fr = [f for f in rec['frames'] if f.get('event') == 'quote']
    out = {'n_frames': len(fr), 'present': rec['depth_present'],
           'zero_only': rec['depth_zero_only'], 'raw_depth_sample': rec['raw_depth_sample'],
           'last_item_keys': {c: rec['last_items'].get(c) for c in codes}}
    print('4C_RESULT', json.dumps(out, ensure_ascii=False)[:3000], flush=True)
    st3, dresp = api('DELETE', f'/stream/subscriptions/{sid}')
    print('DELETE', st3, json.dumps(dresp, ensure_ascii=False)[:150], flush=True)
    out['delete_status'] = st3
    return out


def main():
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    out = {'n_codes': len(CODES), 't_start': time.strftime('%Y-%m-%d %H:%M:%S')}
    out['health_before'] = health()
    out['A'] = run_case('A_quote_50', ['quote'], dur, keep_raw_depth_for=set(CODES[:5]))
    time.sleep(3)
    out['C'] = probe_depth()
    time.sleep(3)
    out['B'] = run_case('B_3field_50', ['quote', 'fundflow', 'timeline'], dur)
    out['health_after'] = health()
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    print(f'\nWROTE {OUT}', flush=True)


if __name__ == '__main__':
    main()
