#!/usr/bin/env python3
"""AC-E4 spike causality: does the periodic tail spike follow
``cache._CACHE_SWEEP_INTERVAL``?

Tests-only helper (no prod edits).  Starts the REAL BoundedThreadPoolServer +
RSSHandler in-process (the ``tests/test_server_http.py`` pattern) and
monkeypatches ``cache._CACHE_SWEEP_INTERVAL`` so the sweep cadence is under the
experiment's control — the "period-following" test: if the observed tail spike
moves with the constant, the sweep is causal; if the period stays ~60 s, it is
not.

Two modes
  timing  Direct distribution of ``cache._sweep_expired()`` over populated
          dicts (2000 expired / 2000 fresh / realistic ~65).  Its magnitude is
          compared against the observed spike amplitude.
  period  In-process HTTP load, 5 s-bucket P99 + a sweep-event log (time,
          duration, entries removed) so bucket spikes can be tied to sweeps.

Usage
  python3 tests/ac_e4_sweep_causality.py --mode timing \
      --samples 200 --report-json /tmp/opencode/ac_e4_sweep_timing.json
  python3 tests/ac_e4_sweep_causality.py --mode period --interval 60 \
      --seconds 150 --report-json /tmp/opencode/ac_e4_sweep_p60.json
"""

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # repo root → china_finance_rss
sys.path.insert(0, _HERE)                      # sibling harnesses

import ac_e4_verify as v

from china_finance_rss import cache as cache_mod
from china_finance_rss import server as srv
from china_finance_rss.server import BoundedThreadPoolServer, RSSHandler

T0 = 0.0                 # experiment epoch (monotonic)
SWEEP_DELAY = 0.0        # injected extra lock-hold per sweep (positive control)
SWEEP_EVENTS = []        # [{t, dur_ms, hold_ms, removed, size_before}]
DRIVER_ERRS = [0]


class _FakeResponse:
    """Minimal urlopen() context manager (test_server.py pattern)."""

    def __init__(self, body):
        self._b = body.encode() if isinstance(body, str) else body
        self.status = 200

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _pct(vals, p):
    return v.ms(v.pct(vals, p))


def _fill(n, expired, now):
    """n-entry OrderedDict of URL-cache-shaped entries."""
    d = {}
    for i in range(n):
        d['http://u.test/%d' % i] = {
            'data': 'x', 'time': now - (100 if expired else 0),
            'last_access': now, 'expires_at': now - 1 if expired else now + 10 ** 6}
    return d


def timing_mode(a):
    """Time the real `_sweep_expired` on representative dict sizes."""
    real = cache_mod._sweep_expired
    now = time.time()
    cases = [
        ('url2000_all_expired', 2000, True),
        ('url2000_none_expired', 2000, False),
        ('url800_all_expired', 800, True),
        ('url65_realistic', 65, True),
    ]
    out = {'mode': 'timing', 'samples_per_case': a.samples, 'cases': []}
    for name, n, expired in cases:
        ts, removed = [], 0
        dicts = [_fill(n, expired, now) for _ in range(a.samples)]
        for d in dicts:
            t0 = time.perf_counter()
            removed = real(d)
            ts.append(time.perf_counter() - t0)      # seconds (ms via _pct)
        out['cases'].append({
            'case': name, 'entries': n, 'expired': expired,
            'removed': removed, 'samples': len(ts),
            'p50_ms': _pct(ts, .50), 'p95_ms': _pct(ts, .95),
            'p99_ms': _pct(ts, .99), 'max_ms': _pct(ts, 1.0),
            'mean_ms': round(statistics.fmean(ts), 5),
        })
    return out


def period_mode(a):
    """In-process server + HTTP load; 5 s-bucket P99 + sweep event log."""
    global T0, SWEEP_DELAY
    SWEEP_DELAY = a.sweep_delay_ms / 1000.0
    urls = ['http://up.test/drv/%d' % i for i in range(a.urls)]
    payload = '{"pad":"' + 'a' * a.payload_bytes + '"}'
    real_sweep = cache_mod._sweep_expired

    def sweep(d):
        t = time.monotonic() - T0
        n0 = len(d)
        if SWEEP_DELAY:
            time.sleep(SWEEP_DELAY)
        s = time.monotonic()
        removed = real_sweep(d)
        dur = (time.monotonic() - s) * 1000.0
        SWEEP_EVENTS.append({'t': round(t, 4), 'dur_ms': round(dur, 4),
                             'hold_ms': round(dur + SWEEP_DELAY * 1000.0, 4),
                             'removed': removed, 'size_before': n0})
        return removed

    def driver():
        try:
            body = cache_mod.fetch_json(random.choice(urls), ttl=a.ttl)
        except Exception:
            DRIVER_ERRS[0] += 1
            return {'error': 'fetch'}
        return {'n': len(body)}

    # ── fresh state ────────────────────────────────────────────────────────
    cache_mod.cache.clear()
    cache_mod._negative.clear()
    cache_mod._fetch_inflight.clear()
    cache_mod._cache_stats = {'hit': 0, 'miss': 0}
    now = time.time()
    for i in range(a.cache_size):                 # stay-fresh scan ballast
        cache_mod.cache['http://pre.test/%d' % i] = {
            'data': 'pre', 'time': now, 'last_access': now,
            'expires_at': now + 10 ** 6}
    cache_mod._CACHE_SWEEP_INTERVAL = a.interval
    cache_mod._last_cache_sweep = time.time()     # first sweep at ~t=interval

    httpd = BoundedThreadPoolServer(('127.0.0.1', 0), RSSHandler,
                                    max_workers=a.workers)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % httpd.server_port

    samples, sizes = [], []
    stop = threading.Event()
    T0 = time.monotonic()
    deadline = T0 + a.seconds
    pacer = v.Pacer(a.max_rate, T0)
    lk = threading.Lock()

    def worker():
        while not stop.is_set():
            if not pacer.acquire(deadline):
                return
            st = time.monotonic()
            if st >= deadline:
                return
            status, err, lat = v.fetch(base + '/finance/market')
            with lk:
                samples.append((st - T0, lat, status, err))

    def monitor():
        while not stop.is_set():
            sizes.append((round(time.monotonic() - T0, 2),
                          len(cache_mod.cache)))
            time.sleep(1.0)

    with mock.patch.dict(srv._PANEL_HANDLERS, {'/finance/market': driver}), \
         mock.patch.object(
             cache_mod, 'urlopen',
             side_effect=lambda req, timeout=None: _FakeResponse(payload)), \
         mock.patch.object(cache_mod, '_sweep_expired', side_effect=sweep):
        threading.Thread(target=monitor, daemon=True).start()
        ths = [threading.Thread(target=worker, daemon=True)
               for _ in range(a.concurrency)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        stop.set()
    elapsed = time.monotonic() - T0
    httpd.shutdown()
    httpd.server_close()

    return _summarize(a, samples, sizes, elapsed)


def _summarize(a, samples, sizes, elapsed):
    ok = [x[1] for x in samples if x[2] == 200]
    status_counts = {}
    for x in samples:
        status_counts[str(x[2])] = status_counts.get(str(x[2]), 0) + 1
    buckets = []
    n = int(elapsed // a.bucket) + 1
    for i in range(n):
        lo, hi = i * a.bucket, (i + 1) * a.bucket
        bs = [x for x in samples if lo <= x[0] < hi]
        bok = [x[1] for x in bs if x[2] == 200]
        ev = [e for e in SWEEP_EVENTS if lo <= e['t'] < hi]
        buckets.append({
            'from_s': lo, 'n': len(bs), 'errors': len(bs) - len(bok),
            'p50_ms': _pct(bok, .50), 'p95_ms': _pct(bok, .95),
            'p99_ms': _pct(bok, .99), 'max_ms': _pct(bok, 1.0),
            'over_20ms': len([x for x in bok if x > 0.020]),
            'sweeps': len(ev),
            'sweep_hold_ms': round(sum(e['hold_ms'] for e in ev), 4),
            'sweep_removed': sum(e['removed'] for e in ev)})
    ev_times = [e['t'] for e in SWEEP_EVENTS]
    gaps = [round(ev_times[i + 1] - ev_times[i], 3)
            for i in range(len(ev_times) - 1)]
    p99s = [b['p99_ms'] for b in buckets if b['n'] > 0]
    med = statistics.median(p99s) if p99s else None
    spikes = [b['from_s'] for b in buckets
              if med and b['p99_ms'] and b['p99_ms'] > 1.5 * med]
    return {
        'mode': 'period', 'interval_set': a.interval, 'ttl': a.ttl,
        'cache_size_seed': a.cache_size, 'sweep_delay_ms': a.sweep_delay_ms,
        'concurrency': a.concurrency, 'max_rate': a.max_rate,
        'seconds': a.seconds, 'elapsed': round(elapsed, 2),
        'total': len(samples), 'errors': len(samples) - len(ok),
        'driver_fetch_errors': DRIVER_ERRS[0],
        'status_counts': status_counts,
        'rps': round(len(samples) / elapsed, 2) if elapsed else 0,
        'p50_ms': _pct(ok, .50), 'p95_ms': _pct(ok, .95),
        'p99_ms': _pct(ok, .99), 'max_ms': _pct(ok, 1.0),
        'buckets': buckets,
        'sweeps': SWEEP_EVENTS,
        'sweep_count': len(SWEEP_EVENTS),
        'sweep_gaps_s': gaps,
        'bucket_p99_median_ms': med,
        'spike_buckets': spikes,
        'cache_size_series': sizes,
    }


def _print_period(rep):
    print('== interval_set=%ss ttl=%ss cache_seed=%d sweep_delay=%sms '
          'c=%d rate=%s =='
          % (rep['interval_set'], rep['ttl'], rep['cache_size_seed'],
             rep['sweep_delay_ms'], rep['concurrency'], rep['max_rate']))
    print('   %.1f req/s  err=%d  driver_err=%d  p50=%s p95=%s p99=%s max=%s ms'
          % (rep['rps'], rep['errors'], rep['driver_fetch_errors'],
             rep['p50_ms'], rep['p95_ms'], rep['p99_ms'], rep['max_ms']))
    print('   sweeps=%d gaps(s)=%s' % (rep['sweep_count'], rep['sweep_gaps_s']))
    print('   bucket_p99_median=%s ms  spike_buckets=%s'
          % (rep['bucket_p99_median_ms'], rep['spike_buckets']))
    print('   t(s)  n     err  p50    p95    p99    max    >20ms sweeps '
          'hold_ms removed')
    for b in rep['buckets']:
        print('   %4d %5d %4d %6s %6s %6s %6s   %3d    %d    %8s %d'
              % (b['from_s'], b['n'], b['errors'], b['p50_ms'], b['p95_ms'],
                 b['p99_ms'], b['max_ms'], b['over_20ms'], b['sweeps'],
                 b['sweep_hold_ms'], b['sweep_removed']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('timing', 'period'), default='period')
    ap.add_argument('--samples', type=int, default=200)
    ap.add_argument('--interval', type=float, default=60.0,
                    help='value written into cache._CACHE_SWEEP_INTERVAL '
                         '(1e9 effectively disables the periodic sweep)')
    ap.add_argument('--ttl', type=float, default=20.0)
    ap.add_argument('--seconds', type=int, default=150)
    ap.add_argument('--concurrency', type=int, default=8)
    ap.add_argument('--max-rate', type=float, default=150.0)
    ap.add_argument('--workers', type=int, default=20)
    ap.add_argument('--urls', type=int, default=48)
    ap.add_argument('--payload-bytes', type=int, default=900)
    ap.add_argument('--cache-size', type=int, default=0)
    ap.add_argument('--sweep-delay-ms', type=float, default=0.0)
    ap.add_argument('--bucket', type=float, default=5.0)
    ap.add_argument('--report-json', default='/tmp/opencode/ac_e4_sweep.json')
    a = ap.parse_args()

    rep = timing_mode(a) if a.mode == 'timing' else period_mode(a)
    rep['started'] = time.strftime('%Y-%m-%d %H:%M:%S')
    os.makedirs(os.path.dirname(a.report_json) or '.', exist_ok=True)
    with open(a.report_json, 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    if a.mode == 'timing':
        for c in rep['cases']:
            print('   %-22s n=%-5d removed=%-5d p50=%-8s p95=%-8s '
                  'p99=%-8s max=%-8s ms'
                  % (c['case'], c['entries'], c['removed'], c['p50_ms'],
                     c['p95_ms'], c['p99_ms'], c['max_ms']))
    else:
        _print_period(rep)
    print('   report: %s' % a.report_json)


if __name__ == '__main__':
    main()

