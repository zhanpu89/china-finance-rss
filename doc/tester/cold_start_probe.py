#!/usr/bin/env python3
"""Cold-start SSE probe (tester — cold-process first-subscriber latency).

Measures, on a freshly (re)started process:
  create-send -> first full frame  (missing_count==0 && stale_count==0)
  connect     -> first frame / first full frame
  per-round stream_tick_duration_ms evolution (fine healthz sampling)
  degraded / slip / lag / upstream deltas

Run: python3 doc/tester/cold_start_probe.py --label cold1 --fields quote --dur 24
"""
import argparse
import http.client
import json
import os
import socket
import threading
import time

HOST = '127.0.0.1'
STREAM_PORT = int(os.environ.get('SSE_STREAM_PORT', '8054'))
MAIN_PORT = int(os.environ.get('SSE_MAIN_PORT', '8053'))
CODES = json.load(open(os.environ.get(
    'SSE_BENCH_CODES', 'doc/tester/sse_codes50.json')))

METRIC_KEYS = ('stream_tick_duration_ms', 'stream_tick_degraded_total',
               'stream_tick_slip_total', 'stream_refresh_lag_ticks',
               'stream_queue_bytes', 'stream_frame_distinct',
               'stream_frame_dropped_total', 'http_503_total')


def api(method, path, body=None, timeout=30, port=STREAM_PORT):
    c = http.client.HTTPConnection(HOST, port, timeout=timeout)
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


class Sampler(threading.Thread):
    """Fine sampling for the first `fine_s` seconds, then coarse."""

    def __init__(self, t_zero, fine_s=10.0):
        super().__init__(daemon=True)
        self.samples = []
        self.stop = threading.Event()
        self.t_zero = t_zero
        self.fine_s = fine_s

    def run(self):
        while not self.stop.is_set():
            t = time.time()
            m = health()
            self.samples.append((round(t - self.t_zero, 3),
                                 {k: m.get(k) for k in METRIC_KEYS}))
            self.stop.wait(0.4 if (t - self.t_zero) < self.fine_s else 1.0)


def read_sse(sid, t_send, duration):
    """Return (frames, t_connect, headers). frames carry rel timestamps."""
    t_connect = time.time()
    sock = socket.create_connection((HOST, STREAM_PORT), timeout=30)
    sock.settimeout(duration + 30)
    sock.sendall((f"GET /stream/quote/{sid} HTTP/1.1\r\nHost: {HOST}\r\n"
                  "Accept: text/event-stream\r\nConnection: close\r\n\r\n"
                  ).encode())
    buf, frames = b'', []
    deadline = t_connect + duration
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        except OSError as e:
            frames.append({'error': f'recv {e}'})
            break
        if not chunk:
            frames.append({'error': 'closed by server'})
            break
        buf += chunk
        while b'\n\n' in buf:
            block, _, buf = buf.partition(b'\n\n')
            txt = block.decode('utf-8', 'replace').strip()
            if not txt:
                continue
            now = time.time()
            ev = {'rel_send': round(now - t_send, 3),
                  'rel_conn': round(now - t_connect, 3)}
            for line in txt.splitlines():
                if line.startswith('event:'):
                    ev['event'] = line[6:].strip()
                elif line.startswith('data:'):
                    ev['data'] = line[5:].strip()
            if ev.get('event') == 'quote' and 'data' in ev:
                try:
                    d = json.loads(ev['data'])
                except Exception as e:
                    ev['error'] = f'json {e}'
                    frames.append(ev)
                    continue
                items = d.get('items') or {}
                ev['codes_total'] = d.get('codes_total')
                ev['items_n'] = len(items)
                ev['missing_count'] = d.get('missing_count')
                ev['stale_count'] = d.get('stale_count', 0)
                ev['nonnull_codes'] = sum(
                    1 for row in items.values() if row and any(
                        v is not None for v in row.values()))
                ev['ts'] = d.get('ts')
                ev['bytes'] = len(ev['data'])
                frames.append(ev)
            elif ev.get('event') == 'ping':
                ev['ping'] = True
                frames.append(ev)
    try:
        sock.close()
    except Exception:
        pass
    return frames, t_connect


def summarize(fr, t_connect):
    quote = [f for f in fr if f.get('event') == 'quote']
    out = {'n_quote_frames': len(quote),
           'n_ping': sum(1 for f in fr if f.get('ping')),
           'errors': [f['error'] for f in fr if 'error' in f]}
    if not quote:
        return out
    out['first_frame_rel_send'] = quote[0]['rel_send']
    out['first_frame_rel_conn'] = quote[0]['rel_conn']
    full = [f for f in quote
            if f.get('missing_count') == 0 and f.get('stale_count') == 0]
    out['first_full_rel_send'] = full[0]['rel_send'] if full else None
    out['first_full_rel_conn'] = full[0]['rel_conn'] if full else None
    out['n_full_frames'] = len(full)
    out['frames_head'] = [{k: f.get(k) for k in
                           ('rel_send', 'rel_conn', 'missing_count',
                            'stale_count', 'items_n', 'codes_total',
                            'nonnull_codes', 'bytes')} for f in quote[:12]]
    ts = [f['rel_send'] for f in quote]
    iv = [round(b - a, 3) for a, b in zip(ts, ts[1:])]
    out['intervals'] = iv
    out['interval_min'] = min(iv) if iv else None
    out['interval_max'] = max(iv) if iv else None
    out['intervals_lt_2s'] = [{'after_frame': i + 2, 'interval': v,
                               'at_rel_send': ts[i + 1]}
                              for i, v in enumerate(iv) if v < 2.0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', default='cold')
    ap.add_argument('--fields', default='quote')
    ap.add_argument('--dur', type=float, default=24.0)
    ap.add_argument('--out', default='/tmp/cold_start_out.json')
    a = ap.parse_args()
    fields = [f for f in a.fields.split(',') if f]
    res = {'label': a.label, 'fields': fields, 'n_codes': len(CODES)}

    res['health_before'] = {k: health().get(k) for k in METRIC_KEYS}
    res['upstream_before'] = health().get('upstream_fetch_total')

    # The stream port may bind a few ms after /healthz answers (push_loop and
    # run_stream_server are daemon threads started just before serve_forever).
    # A refused POST never reached the server, so re-arming t_send is faithful.
    for attempt in range(200):
        t_send = time.time()
        try:
            st, resp = api('POST', '/stream/subscriptions',
                           {'codes': CODES, 'fields': fields}, timeout=30)
            break
        except OSError as e:
            if attempt == 199:
                raise
            time.sleep(0.05)
    sampler = Sampler(t_send)
    sampler.start()
    res['create_status'] = st
    res['create_resp'] = resp
    res['t_create_done'] = round(time.time() - t_send, 3)
    sid = resp.get('sid') if isinstance(resp, dict) else None
    if not sid:
        sampler.stop.set()
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    frames, t_connect = read_sse(sid, t_send, a.dur)
    sampler.stop.set()
    sampler.join(timeout=5)
    res['t_connect_rel_send'] = round(t_connect - t_send, 3)
    res['sse'] = summarize(frames, t_connect)
    res['samples'] = sampler.samples
    m1 = health()
    res['health_after'] = {k: m1.get(k) for k in METRIC_KEYS}
    ub, ua = res['upstream_before'] or {}, m1.get('upstream_fetch_total') or {}
    res['upstream_delta'] = {k: ua.get(k, 0) - ub.get(k, 0)
                             for k in sorted(set(ub) | set(ua))}
    ticks = [(s[0], s[1]['stream_tick_duration_ms']) for s in sampler.samples
             if isinstance(s[1].get('stream_tick_duration_ms'), (int, float))]
    res['tick_ms_series'] = ticks
    res['tick_ms_max'] = max((v for _, v in ticks), default=None)
    res['tick_ms_first_round'] = max(
        (v for t, v in ticks if t <= 10.0), default=None)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f'\nWROTE {a.out}')
    print(f"\nSUMMARY {a.label}: create->first={res['sse'].get('first_frame_rel_send')}s "
          f"create->first_full={res['sse'].get('first_full_rel_send')}s "
          f"conn->first_full={res['sse'].get('first_full_rel_conn')}s "
          f"first_round_tick_ms={res['tick_ms_first_round']} "
          f"min_interval={res['sse'].get('interval_min')} "
          f"degraded_d={res['health_after']['stream_tick_degraded_total']-res['health_before']['stream_tick_degraded_total']} "
          f"slip_d={res['health_after']['stream_tick_slip_total']-res['health_before']['stream_tick_slip_total']}")


if __name__ == '__main__':
    main()
