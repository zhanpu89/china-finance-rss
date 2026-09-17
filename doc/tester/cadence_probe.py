#!/usr/bin/env python3
"""Decisive cadence probe (BUG-冷启动-01 follow-up).

Is the observed 8s quote beat a *skipped (deduped) 4s round* rather than a
slower push loop?  While one quote-only group streams, sample at 0.25s:
  * `stream_tick_duration_ms` gauge  -> the push loop's round cadence
  * GET /stream/subscriptions/<sid> `.last_push_ts` -> a REAL send
  * raw SSE frame arrivals

If `last_push_ts` advances ~every 8s while the tick gauge updates ~every 4s,
the intervening 4s rounds were content-unchanged and dropped by send-layer dedup.
Read-only: SSE + subscription CRUD.
"""
import http.client
import json
import socket
import threading
import time

HOST = '127.0.0.1'
SP = 8054
MP = 8053
CODES = json.load(open('doc/tester/sse_codes50.json'))


def api(method, path, body=None):
    c = http.client.HTTPConnection(HOST, SP, timeout=10)
    hdr = {'Content-Type': 'application/json'} if body is not None else {}
    c.request(method, path,
              body=json.dumps(body) if body is not None else None, headers=hdr)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, (json.loads(raw) if raw else {})


def metric(k):
    c = http.client.HTTPConnection(HOST, MP, timeout=10)
    c.request('GET', '/healthz?check=0')
    r = c.getresponse()
    d = json.loads(r.read())
    c.close()
    return d.get('metrics', d).get(k)


def main():
    st, resp = api('POST', '/stream/subscriptions',
                   {'codes': CODES, 'fields': ['quote']})
    sid = resp['sid']
    print('sid', sid, st)
    sock = socket.create_connection((HOST, SP), timeout=20)
    sock.settimeout(20)
    sock.sendall((f"GET /stream/quote/{sid} HTTP/1.1\r\nHost: {HOST}\r\n"
                  "Accept: text/event-stream\r\nConnection: close\r\n\r\n"
                  ).encode())
    frames = []
    t0 = time.time()

    def reader():
        buf = b''
        while time.time() - t0 < 20:
            try:
                ch = sock.recv(65536)
            except Exception:
                break
            if not ch:
                break
            buf += ch
            while b'\n\n' in buf:
                block, _, buf = buf.partition(b'\n\n')
                if b'event: quote' in block:
                    frames.append(round(time.time() - t0, 2))

    threading.Thread(target=reader, daemon=True).start()
    series = []
    while time.time() - t0 < 20:
        series.append((round(time.time() - t0, 2),
                       metric('stream_tick_duration_ms'),
                       api('GET', f'/stream/subscriptions/{sid}')[1]
                       .get('last_push_ts')))
        time.sleep(0.25)
    sock.close()
    print('FRAMES rel:', frames)
    print('intervals:', [round(b - a, 2) for a, b in zip(frames, frames[1:])])
    tick_ch, push_ch = [], []
    pt = pl = None
    for now, tick, lpt in series:
        if tick != pt:
            tick_ch.append(now)
            pt = tick
        if lpt != pl:
            push_ch.append(now)
            pl = lpt
    print('tick_duration_ms changes at:', tick_ch)
    print('last_push_ts changes at:', push_ch)
    print('tick #changes', len(tick_ch), 'push #changes', len(push_ch))
    api('DELETE', f'/stream/subscriptions/{sid}')
    print('deleted', sid)


if __name__ == '__main__':
    main()
