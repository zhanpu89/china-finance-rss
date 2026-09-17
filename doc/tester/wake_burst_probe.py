#!/usr/bin/env python3
"""Wake / no-burst probe (tester — cold-start wake verification).

Two questions the cold-start wake fix must answer:

  Q1  A new subscription on an *idle* process refreshes immediately
      (not after the L1 baseline grid wait).
  Q2  Adding a subscription while the loop is ACTIVE never produces an extra
      off-grid round ("no burst": never two frames < 1 tick apart from two
      different rounds).  `--concurrent` exercises exactly that: conn1 is
      live, conn2 joins 1.2 s later; conn1's cadence must stay on its grid.

Round identity comes from a 0.2 s sample of the `stream_tick_duration_ms`
gauge (each round overwrites it at its end), so the number of rounds in the
window is counted independently of the frames.

Run: python3 doc/tester/wake_burst_probe.py --concurrent --dur 22
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
    except Exception:
        return {}


class Sampler(threading.Thread):
    def __init__(self, t_zero):
        super().__init__(daemon=True)
        self.samples, self.stop, self.t_zero = [], threading.Event(), t_zero

    def run(self):
        while not self.stop.is_set():
            t = time.time()
            m = health()
            self.samples.append((round(t - self.t_zero, 3),
                                 m.get('stream_tick_duration_ms'),
                                 m.get('stream_tick_degraded_total'),
                                 m.get('stream_tick_slip_total'),
                                 m.get('stream_refresh_lag_ticks')))
            self.stop.wait(0.2)


def reader(sid, t_zero, out, key, duration):
    sock = socket.create_connection((HOST, STREAM_PORT), timeout=30)
    sock.settimeout(duration + 30)
    sock.sendall((f"GET /stream/quote/{sid} HTTP/1.1\r\nHost: {HOST}\r\n"
                  "Accept: text/event-stream\r\nConnection: close\r\n\r\n"
                  ).encode())
    buf, frames = b'', []
    deadline = t_zero + duration
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
        except (socket.timeout, OSError):
            break
        if not chunk:
            break
        buf += chunk
        while b'\n\n' in buf:
            block, _, buf = buf.partition(b'\n\n')
            txt = block.decode('utf-8', 'replace').strip()
            if not txt:
                continue
            ev = {'t': round(time.time() - t_zero, 3)}
            for line in txt.splitlines():
                if line.startswith('event:'):
                    ev['event'] = line[6:].strip()
                elif line.startswith('data:'):
                    ev['data'] = line[5:].strip()
            if ev.get('event') == 'quote' and 'data' in ev:
                d = json.loads(ev['data'])
                ev['missing'] = d.get('missing_count')
                ev['stale'] = d.get('stale_count', 0)
                ev['bytes'] = len(ev['data'])
                frames.append(ev)
            elif ev.get('event') == 'ping':
                frames.append({'t': ev['t'], 'ping': True})
    try:
        sock.close()
    except Exception:
        pass
    out[key] = frames


def rounds(samples):
    """Distinct consecutive gauge values = completed rounds (in order)."""
    out, prev = [], None
    for t, v, dg, sl, lag in samples:
        if v != prev:
            out.append({'t': t, 'ms': v, 'degraded': dg, 'slip': sl, 'lag': lag})
            prev = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--concurrent', action='store_true')
    ap.add_argument('--dur', type=float, default=22.0)
    ap.add_argument('--out', default='/tmp/wake_burst.json')
    a = ap.parse_args()
    res = {'concurrent': a.concurrent, 'dur': a.dur}

    # No list endpoint exists: require the caller to have left no live group
    # (a connectionless group carries no demand, so the loop is idle either
    # way).  The 3 s settle lets the loop enter its interruptible idle wait.
    time.sleep(3.0)

    t_zero = time.time()
    sampler = Sampler(t_zero)
    sampler.start()
    out = {}
    st1, r1 = api('POST', '/stream/subscriptions',
                  {'codes': CODES[:25], 'fields': ['quote']})
    res['sid1'], res['create1_status'] = r1.get('sid'), st1
    th1 = threading.Thread(target=reader, args=(r1['sid'], t_zero, out, 'c1',
                                                a.dur))
    th1.start()
    if a.concurrent:
        time.sleep(1.2)
        st2, r2 = api('POST', '/stream/subscriptions',
                      {'codes': CODES[25:], 'fields': ['quote']})
        res['sid2'], res['create2_status'] = r2.get('sid'), st2
        res['t_create2'] = round(time.time() - t_zero, 3)
        th2 = threading.Thread(target=reader, args=(r2['sid'], t_zero, out,
                                                    'c2', a.dur - 1.2))
        th2.start()
        th2.join(timeout=a.dur + 30)
    th1.join(timeout=a.dur + 30)
    sampler.stop.set()
    sampler.join(timeout=5)

    for key in ('c1', 'c2'):
        fr = out.get(key) or []
        q = [f for f in fr if not f.get('ping')]
        rec = {'n_frames': len(q), 'n_ping': len(fr) - len(q)}
        if q:
            ts = [f['t'] for f in q]
            iv = [round(b - a_, 3) for a_, b in zip(ts, ts[1:])]
            rec.update({'first_t': ts[0], 'frames_t': ts,
                        'intervals': iv,
                        'interval_min': min(iv) if iv else None,
                        'interval_max': max(iv) if iv else None,
                        'intervals_lt_2s': [{'i': i + 2, 'gap': v,
                                             'at': ts[i + 1]}
                                            for i, v in enumerate(iv)
                                            if v < 2.0],
                        'missing_max': max(f['missing'] for f in q),
                        'stale_max': max(f['stale'] for f in q)})
        res[key] = rec
    rs = rounds(sampler.samples)
    res['rounds'] = rs
    res['n_rounds'] = len(rs)
    res['round_ms'] = [r['ms'] for r in rs]
    res['degraded_end'] = sampler.samples[-1][2] if sampler.samples else None
    res['slip_end'] = sampler.samples[-1][3] if sampler.samples else None
    res['lag_max'] = max((s[4] for s in sampler.samples
                          if isinstance(s[4], (int, float))), default=None)
    res['lag_samples_tail'] = [s[4] for s in sampler.samples][-12:]
    for key in ('sid1', 'sid2'):
        if res.get(key):
            res[f'delete_{key}'] = api(
                'DELETE', f"/stream/subscriptions/{res[key]}")[0]
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f"\nWROTE {a.out}")


if __name__ == '__main__':
    main()
