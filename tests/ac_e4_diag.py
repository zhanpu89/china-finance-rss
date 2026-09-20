#!/usr/bin/env python3
"""AC-E4 diagnostic: connect-vs-response split, time buckets, per-path tail.

Tests-only. Reuses helpers from tests/ac_e4_verify.py (no prod imports).
Answers: is the P99 drift server-side or a client-side TIME_WAIT artifact?

Usage:
  python3 tests/ac_e4_diag.py --formal-seconds 300 --max-rate 200 --bucket 30 \
      --report-json /tmp/opencode/ac_e4_diag.json
"""

import argparse
import http.client
import json
import os
import random
import threading
import time
import urllib.parse

import ac_e4_verify as v


def fetch_split(url, timeout=10.0):
    """GET -> (status, err, total, connect, response). connect/response may be None."""
    t0 = time.monotonic()
    try:
        u = urllib.parse.urlsplit(url)
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
        t1 = time.monotonic()
        conn.connect()
        t2 = time.monotonic()
        path = u.path + (('?' + u.query) if u.query else '')
        conn.request('GET', path, headers={'User-Agent': 'Mozilla/5.0'})
        r = conn.getresponse()
        r.read()
        t3 = time.monotonic()
        conn.close()
        return (r.status, '', t3 - t0, t2 - t1, t3 - t2)
    except Exception as e:
        return (0, '%s: %s' % (type(e).__name__, str(e)[:80]),
                time.monotonic() - t0, None, None)


def sockstat():
    try:
        with open('/proc/net/sockstat') as f:
            for line in f:
                if line.startswith('TCP:'):
                    return line.strip()
    except Exception as e:
        return 'error: %s' % e
    return 'n/a'


def run_split(base, pool, concurrency, seconds, max_rate, label, mid_cb=None):
    samples = []
    t0 = time.monotonic()
    deadline = t0 + seconds
    pacer = v.Pacer(max_rate, t0)
    stop = threading.Event()
    lk = threading.Lock()

    def worker():
        while not stop.is_set():
            if not pacer.acquire(deadline):
                return
            st = time.monotonic()
            if st >= deadline:
                return
            path = random.choice(pool)
            status, err, total, cx, resp = fetch_split(base + path)
            with lk:
                samples.append((st - t0, cx, resp, total, status, err, path))

    ths = [threading.Thread(target=worker, daemon=True)
           for _ in range(max(1, concurrency))]
    for t in ths:
        t.start()
    if mid_cb:
        threading.Timer(seconds / 2.0, mid_cb).start()
    for t in ths:
        t.join()
    stop.set()
    return {'label': label, 'elapsed': time.monotonic() - t0, 'samples': samples,
            'concurrency': concurrency, 'seconds': seconds, 'max_rate': max_rate}


def pctl(vals, p):
    return v.ms(v.pct(vals, p))


def window(samples, w0, w1):
    s = [x for x in samples if w0 <= x[0] < w1]
    ok = [x for x in s if x[4] == 200]
    tot = [x[3] for x in ok]
    cx = [x[1] for x in ok if x[1] is not None]
    rp = [x[2] for x in ok if x[2] is not None]
    return {'window_sec': [w0, w1], 'n': len(s), 'errors': len(s) - len(ok),
            'total_p50_ms': pctl(tot, .50), 'total_p95_ms': pctl(tot, .95),
            'total_p99_ms': pctl(tot, .99), 'total_max_ms': v.ms(max(tot) if tot else None),
            'connect_p50_ms': pctl(cx, .50), 'connect_p99_ms': pctl(cx, .99),
            'connect_max_ms': v.ms(max(cx) if cx else None),
            'resp_p50_ms': pctl(rp, .50), 'resp_p99_ms': pctl(rp, .99),
            'resp_max_ms': v.ms(max(rp) if rp else None)}


def buckets(samples, bucket):
    out = []
    t = 0
    while t * bucket < max((x[0] for x in samples), default=0):
        s = [x for x in samples if t * bucket <= x[0] < (t + 1) * bucket]
        ok = [x for x in s if x[4] == 200]
        tot = [x[3] for x in ok]
        cx = [x[1] for x in ok if x[1] is not None]
        out.append({'from_s': t * bucket, 'n': len(s),
                    'errors': len(s) - len(ok),
                    'p50_ms': pctl(tot, .50), 'p95_ms': pctl(tot, .95),
                    'p99_ms': pctl(tot, .99),
                    'connect_p99_ms': pctl(cx, .99),
                    'max_ms': v.ms(max(tot) if tot else None)})
        t += 1
    return out


def per_path(samples):
    agg = {}
    for x in samples:
        d = agg.setdefault(x[6], {'n': 0, 'err': 0, 'tot': [], 'cx': []})
        d['n'] += 1
        if x[4] != 200:
            d['err'] += 1
        else:
            d['tot'].append(x[3])
            if x[1] is not None:
                d['cx'].append(x[1])
    out = {}
    for k, d in agg.items():
        out[k] = {'n': d['n'], 'err': d['err'],
                  'p50_ms': pctl(d['tot'], .50), 'p95_ms': pctl(d['tot'], .95),
                  'p99_ms': pctl(d['tot'], .99),
                  'max_ms': v.ms(max(d['tot']) if d['tot'] else None),
                  'connect_p99_ms': pctl(d['cx'], .99)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8053')
    ap.add_argument('--warm-seconds', type=int, default=8)
    ap.add_argument('--warm-concurrency', type=int, default=4)
    ap.add_argument('--formal-seconds', type=int, default=300)
    ap.add_argument('--concurrency', type=int, default=10)
    ap.add_argument('--max-rate', type=float, default=200.0)
    ap.add_argument('--cooldown', type=int, default=20)
    ap.add_argument('--bucket', type=int, default=30)
    ap.add_argument('--report-json', default='/tmp/opencode/ac_e4_diag.json')
    a = ap.parse_args()

    pool = v.build_pool(True)
    rep = {'ac': 'AC-E4-diag', 'base': a.base, 'sockstat': {}, 'snapshots': {},
           'buckets': [], 'windows': {}, 'per_path': {}, 'formal': None}

    print('[0] warm %ss ...' % a.warm_seconds)
    w = run_split(a.base, pool, a.warm_concurrency, a.warm_seconds, None, 'warm')
    rep['warm_summary'] = {'n': len(w['samples']), 'elapsed': round(w['elapsed'], 2)}
    rep['sockstat']['initial'] = sockstat()
    rep['snapshots']['initial'] = {'healthz': v.snapshot_healthz(a.base),
                                   'docker': v.docker_stats()}
    if a.cooldown:
        print('[1] cooldown %ss ...' % a.cooldown)
        time.sleep(a.cooldown)

    def mid_cb():
        rep['sockstat']['mid'] = sockstat()
        rep['snapshots']['mid'] = {'healthz': v.snapshot_healthz(a.base),
                                   'docker': v.docker_stats()}
        print('    [mid] sockstat=%s' % rep['sockstat']['mid'])

    print('[2] formal %ss c=%d cap=%s ...' % (a.formal_seconds, a.concurrency,
                                              a.max_rate))
    rep['sockstat']['pre_formal'] = sockstat()
    rep['snapshots']['pre_formal'] = {'healthz': v.snapshot_healthz(a.base),
                                      'docker': v.docker_stats()}
    res = run_split(a.base, pool, a.concurrency, a.formal_seconds, a.max_rate,
                    'formal', mid_cb=mid_cb)
    rep['sockstat']['post_formal'] = sockstat()
    rep['sockstat']['post_formal_5s'] = (time.sleep(5), sockstat())[1]
    rep['snapshots']['post_formal'] = {'healthz': v.snapshot_healthz(a.base),
                                       'docker': v.docker_stats()}

    s = res['samples']
    ok = [x for x in s if x[4] == 200]
    rep['formal'] = {'n': len(s), 'errors': len(s) - len(ok),
                     'rps_over_elapsed': round(len(s) / res['elapsed'], 2),
                     'elapsed': round(res['elapsed'], 2),
                     'status_counts': _counts(s)}
    rep['windows'] = {
        'A_0_120': window(s, 0, 120),
        'B_120_300': window(s, 120, a.formal_seconds),
        'C_0_60': window(s, 0, 60),
        'D_60_120': window(s, 60, 120),
    }
    A, B = rep['windows']['A_0_120'], rep['windows']['B_120_300']
    rep['p99_ratio'] = (round(B['total_p99_ms'] / A['total_p99_ms'], 4)
                        if A['total_p99_ms'] and B['total_p99_ms'] else None)
    rep['connect_p99_ratio'] = (
        round(B['connect_p99_ms'] / A['connect_p99_ms'], 4)
        if A['connect_p99_ms'] and B['connect_p99_ms'] else None)
    rep['resp_p99_ratio'] = (
        round(B['resp_p99_ms'] / A['resp_p99_ms'], 4)
        if A['resp_p99_ms'] and B['resp_p99_ms'] else None)
    rep['buckets'] = buckets(s, a.bucket)
    rep['per_path'] = per_path(s)

    os.makedirs(os.path.dirname(a.report_json) or '.', exist_ok=True)
    with open(a.report_json, 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    print('== windows ==')
    for k in ('C_0_60', 'D_60_120', 'A_0_120', 'B_120_300'):
        w = rep['windows'][k]
        print('  %-10s n=%d tot p50=%s p95=%s p99=%s max=%s | cx p99=%s | resp p99=%s'
              % (k, w['n'], w['total_p50_ms'], w['total_p95_ms'], w['total_p99_ms'],
                 w['total_max_ms'], w['connect_p99_ms'], w['resp_p99_ms']))
    print('  p99 ratio B/A      = %s' % rep['p99_ratio'])
    print('  connect p99 B/A    = %s' % rep['connect_p99_ratio'])
    print('  response p99 B/A   = %s' % rep['resp_p99_ratio'])
    print('== buckets ==')
    for b in rep['buckets']:
        print('  t=%4ds n=%-6d err=%d p50=%s p95=%s p99=%s cx99=%s max=%s'
              % (b['from_s'], b['n'], b['errors'], b['p50_ms'], b['p95_ms'],
                 b['p99_ms'], b['connect_p99_ms'], b['max_ms']))
    print('== report: %s ==' % a.report_json)


def _counts(s):
    c = {}
    for x in s:
        c[str(x[4])] = c.get(str(x[4]), 0) + 1
    return c


if __name__ == '__main__':
    main()
