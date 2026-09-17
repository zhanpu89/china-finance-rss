#!/usr/bin/env python3
"""Frame-dedup runtime probe (BUG-冷启动-01 send-layer dedup).

Read-only SSE + subscription CRUD.  Measures, per run:
  * first-frame latency (create->first / connect->first)
  * the full adjacent-frame **interval series** + every sub-2s interval
  * content churn: each frame's dedup signature (`_frame_signature` reproduced
    byte-for-byte: raw JSON minus the leading ``ts`` field) — distinct count and
    the number of *consecutive* frames whose content is byte-identical (must be
    0 per the fix's guarantee ④), plus per-code value churn between frames
  * first full frame (missing==0 && stale==0), lag/degraded/slip/dropped deltas

Modes:
  cold3   create a 3-domain 50-code group, connect, record --dur seconds
  quote   create a quote-only 50-code group, main client + optional newcomer
          (--newcomer-after S): a second client joins the *live* sid mid-stream
          and we measure connect -> first frame (must be <= 1 tick even when
          the content is unchanged).

Run: python3 doc/tester/dedup_probe.py --mode cold3 --dur 60 --out /tmp/x.json
"""
import argparse
import hashlib
import http.client
import json
import os
import socket
import threading
import time

HOST = '127.0.0.1'
STREAM_PORT = 8054
MAIN_PORT = 8053
CODES = json.load(open(os.environ.get(
    'SSE_BENCH_CODES', 'doc/tester/sse_codes50.json')))

METRIC_KEYS = ('stream_tick_duration_ms', 'stream_tick_degraded_total',
               'stream_tick_slip_total', 'stream_refresh_lag_ticks',
               'stream_frame_dropped_total', 'stream_slow_client_total',
               'stream_frame_distinct', 'stream_queue_bytes', 'http_503_total')


def api(method, path, body=None, timeout=30):
    c = http.client.HTTPConnection(HOST, STREAM_PORT, timeout=timeout)
    hdr = {'Content-Type': 'application/json'} if body is not None else {}
    c.request(method, path,
              body=json.dumps(body) if body is not None else None, headers=hdr)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, (json.loads(raw) if raw else {})


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


def frame_sig(raw):
    """Exact reproduction of stream._frame_signature (raw JSON minus ts)."""
    b = raw.encode('utf-8')
    if b[:len(b'{"ts":')] == b'{"ts":':
        comma = b.find(b',', len(b'{"ts":'))
        if comma != -1:
            b = b[comma + 1:]
    return hashlib.blake2b(b, digest_size=8).hexdigest()


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples = []
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.samples.append((time.time(), health()))
            self.stop.wait(1.0)


class SSEClient(threading.Thread):
    def __init__(self, sid, dur, label):
        super().__init__(daemon=True)
        self.sid = sid
        self.dur = dur
        self.label = label
        self.t_connect = None
        self.frames = []
        self.errors = []
        self.ready = threading.Event()

    def run(self):
        self.t_connect = time.time()
        try:
            sock = socket.create_connection((HOST, STREAM_PORT), timeout=30)
            sock.settimeout(self.dur + 30)
            sock.sendall((f"GET /stream/quote/{self.sid} HTTP/1.1\r\n"
                          f"Host: {HOST}\r\nAccept: text/event-stream\r\n"
                          "Connection: close\r\n\r\n").encode())
            self.ready.set()
            buf = b''
            deadline = self.t_connect + self.dur
            while time.time() < deadline:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    break
                except OSError as e:
                    self.errors.append(f'recv {e}')
                    break
                if not chunk:
                    self.errors.append('closed by server')
                    break
                buf += chunk
                while b'\n\n' in buf:
                    block, _, buf = buf.partition(b'\n\n')
                    txt = block.decode('utf-8', 'replace').strip()
                    if not txt:
                        continue
                    now = time.time()
                    ev = {'rel_conn': round(now - self.t_connect, 3)}
                    for line in txt.splitlines():
                        if line.startswith('event:'):
                            ev['event'] = line[6:].strip()
                        elif line.startswith('data:'):
                            ev['data'] = line[5:].strip()
                    if ev.get('event') == 'quote' and 'data' in ev:
                        try:
                            d = json.loads(ev['data'])
                        except Exception:
                            continue
                        items = d.get('items') or {}
                        ev['sig'] = frame_sig(ev['data'])
                        ev['ts'] = d.get('ts')
                        ev['codes_total'] = d.get('codes_total')
                        ev['fields'] = d.get('fields')
                        ev['items_n'] = len(items)
                        ev['missing_count'] = d.get('missing_count')
                        ev['stale_count'] = d.get('stale_count', 0)
                        ev['nonnull_codes'] = sum(
                            1 for row in items.values() if row and any(
                                v is not None for v in row.values()))
                        ev['bytes'] = len(ev['data'])
                        # compact per-code value signature (churn detection)
                        ev['code_sig'] = {
                            c: hashlib.blake2b(
                                json.dumps([(k, str(v)) for k, v in
                                            sorted((row or {}).items())
                                            if v is not None],
                                           ensure_ascii=False).encode(),
                                digest_size=6).hexdigest()
                            for c, row in items.items()}
                        self.frames.append(ev)
                    elif ev.get('event') == 'ping':
                        ev['ping'] = True
                        self.frames.append(ev)
            sock.close()
        except Exception as e:
            self.errors.append(f'conn {e}')
        finally:
            self.ready.set()


def summarize(cli, t_create=None):
    q = [f for f in cli.frames if f.get('event') == 'quote']
    out = {'label': cli.label, 'sid': cli.sid,
           'errors': cli.errors, 'n_quote': len(q),
           'n_ping': sum(1 for f in cli.frames if f.get('ping'))}
    if not q:
        return out
    out['first_frame_rel_conn'] = q[0]['rel_conn']
    if t_create is not None:
        out['first_frame_rel_create'] = round(
            cli.t_connect - t_create + q[0]['rel_conn'], 3)
    full = [f for f in q if f.get('missing_count') == 0
            and f.get('stale_count') == 0]
    out['first_full_rel_conn'] = full[0]['rel_conn'] if full else None
    out['n_full'] = len(full)
    ts = [f['rel_conn'] for f in q]
    iv = [round(b - a, 3) for a, b in zip(ts, ts[1:])]
    out['intervals'] = iv
    out['interval_min'] = min(iv) if iv else None
    out['interval_max'] = max(iv) if iv else None
    out['interval_avg'] = round(sum(iv) / len(iv), 3) if iv else None
    out['intervals_lt_2s'] = [{'after_frame': i + 2, 'interval': v,
                               'at_rel_conn': ts[i + 1]}
                              for i, v in enumerate(iv) if v < 2.0]
    sigs = [f['sig'] for f in q]
    out['distinct_content_sigs'] = len(set(sigs))
    out['consecutive_identical_content'] = sum(
        1 for a, b in zip(sigs, sigs[1:]) if a == b)
    churn = []
    for a, b in zip(q, q[1:]):
        sa, sb = a.get('code_sig') or {}, b.get('code_sig') or {}
        keys = set(sa) | set(sb)
        churn.append(sum(1 for k in keys if sa.get(k) != sb.get(k)))
    out['code_churn_per_transition'] = churn
    out['max_code_churn'] = max(churn) if churn else 0
    out['missing_counts'] = [f.get('missing_count') for f in q]
    out['stale_counts'] = [f.get('stale_count') for f in q]
    out['items_n'] = [f.get('items_n') for f in q]
    out['frame_bytes'] = [f.get('bytes') for f in q]
    out['frames_head'] = [{k: f.get(k) for k in
                           ('rel_conn', 'missing_count', 'stale_count',
                            'items_n', 'nonnull_codes', 'bytes', 'sig')}
                          for f in q[:10]]
    return out


def deltas(m0, m1):
    out = {}
    for k in METRIC_KEYS:
        a, b = m0.get(k), m1.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[k] = round(b - a, 3)
        else:
            out[k] = {'before': a, 'after': b}
    return out


def create(fields):
    """POST the group, retrying while the stream port is still binding."""
    for attempt in range(200):
        t = time.time()
        try:
            st, resp = api('POST', '/stream/subscriptions',
                           {'codes': CODES, 'fields': fields})
            return t, st, resp
        except OSError:
            if attempt == 199:
                raise
            time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['cold3', 'quote'], required=True)
    ap.add_argument('--dur', type=float, default=60.0)
    ap.add_argument('--newcomer-after', type=float, default=6.0)
    ap.add_argument('--out', default='/tmp/dedup_probe.json')
    a = ap.parse_args()
    fields = ['quote', 'fundflow', 'timeline'] if a.mode == 'cold3' else ['quote']

    res = {'mode': a.mode, 'fields': fields, 'n_codes': len(CODES),
           'dur': a.dur}
    m0 = health()
    sampler = Sampler()
    sampler.start()
    t_create, st, resp = create(fields)
    res['create_status'] = st
    res['create_resp'] = resp
    sid = resp.get('sid') if isinstance(resp, dict) else None
    if not sid:
        sampler.stop.set()
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    res['create_done_rel'] = round(time.time() - t_create, 3)

    main_cli = SSEClient(sid, a.dur, 'main')
    main_cli.start()
    main_cli.ready.wait(timeout=10)

    new_cli = None
    if a.mode == 'quote':
        time.sleep(a.newcomer_after)
        new_cli = SSEClient(sid, max(a.dur - a.newcomer_after - 1, 5), 'newcomer')
        new_cli.start()

    main_cli.join(timeout=a.dur + 15)
    if new_cli:
        res['newcomer'] = summarize(new_cli)
        # strongest evidence: newcomer's first frame content == main's last
        # frame content (i.e. it was sent although unchanged)
        mq = [f for f in main_cli.frames if f.get('event') == 'quote']
        nq = [f for f in new_cli.frames if f.get('event') == 'quote']
        if mq and nq:
            res['newcomer']['first_sig'] = nq[0]['sig']
            res['newcomer']['dup_of_last_main_frame'] = (
                nq[0]['sig'] == mq[-1]['sig'])
            res['newcomer']['last_main_sig'] = mq[-1]['sig']
    sampler.stop.set()
    sampler.join(timeout=5)

    res['main'] = summarize(main_cli, t_create)
    m1 = health()
    res['metric_delta'] = deltas(m0, m1)
    tick = [s[1].get('stream_tick_duration_ms') for s in sampler.samples
            if isinstance(s[1].get('stream_tick_duration_ms'), (int, float))]
    lag = [s[1].get('stream_refresh_lag_ticks') for s in sampler.samples
           if isinstance(s[1].get('stream_refresh_lag_ticks'), (int, float))]
    res['tick_ms_max'] = max(tick) if tick else None
    res['lag_max'] = max(lag) if lag else None
    res['sid'] = sid
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(f'\nWROTE {a.out}')
    m = res['main']
    print(f"\nSUMMARY {a.mode}: frames={m.get('n_quote')} "
          f"first_rel_conn={m.get('first_frame_rel_conn')} "
          f"first_full={m.get('first_full_rel_conn')} "
          f"min_iv={m.get('interval_min')} max_iv={m.get('interval_max')} "
          f"iv_lt2s={m.get('intervals_lt_2s')} "
          f"consec_identical={m.get('consecutive_identical_content')} "
          f"max_churn={m.get('max_code_churn')}")
    if new_cli:
        n = res['newcomer']
        print(f"NEWCOMER: conn->first={n.get('first_frame_rel_conn')}s "
              f"dup_of_last={n.get('dup_of_last_main_frame')}")


if __name__ == '__main__':
    main()
