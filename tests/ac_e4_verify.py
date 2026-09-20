#!/usr/bin/env python3
"""AC-E4 sustained-throughput verification (tests-only helper, no prod imports).

Verifies PRD AC-E4 (doc/prd/perf-stability-optimization.md:81):
  >=100 req/s sustained 5 min, error rate == 0,
  P99(last 3 min) <= 1.2 * P99(first 2 min).

Request semantics mirror tests/loadtest.py (urllib, UA header only, no gzip).
Adds: per-second req/s+error series; two-window P50/P95/P99; /healthz?check=0
snapshots before/after; `docker stats --no-stream` at start/mid/end.

Usage:
  python3 tests/ac_e4_verify.py --base http://127.0.0.1:8053 \
      --probe-concurrency 4,10 --probe-seconds 30 \
      --formal-seconds 300 --max-rate 200 --cooldown 65 \
      --report-json /tmp/opencode/ac_e4.json
"""

import argparse
import json
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request

CODES = ['sh600519', 'sz000001', 'sz300059', 'sh600036', 'sz002415',
         'sh601318', 'sz000858', 'sh600900', 'sz002594', 'sh601012']
RSS_FEEDS = ['/cls/telegraph', '/eastmoney/kuaixun']


def build_pool(with_rss=True):
    """Weighted mixed-read pool: SCN-1 snapshot polling + SCN-4 panel + RSS."""
    pool = []
    for c in CODES:
        pool += ['/stock/data?code=%s' % c] * 6
        pool += ['/stock/basic_info?code=%s' % c] * 4
        pool += ['/stock/timeline?code=%s' % c] * 5
        pool += ['/stock/fundflow?code=%s' % c] * 5
    pool += ['/cls/hotplate'] * 15
    pool += ['/market/margin'] * 6
    pool += ['/healthz?check=0'] * 10
    if with_rss:
        for f in RSS_FEEDS:
            pool += [f] * 10
    return pool


def fetch(url, timeout=10.0):
    """Single GET -> (status, errdetail, latency). status 0 == transport error."""
    t = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return (r.status, '', time.monotonic() - t)
    except urllib.error.HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return (e.code, '', time.monotonic() - t)
    except Exception as e:
        return (0, '%s: %s' % (type(e).__name__, str(e)[:90]),
                time.monotonic() - t)


def snapshot_healthz(base):
    try:
        with urllib.request.urlopen(base + '/healthz?check=0', timeout=20.0) as r:
            doc = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)[:120]}
    m = doc.get('metrics', {})
    uf = m.get('upstream_fail_total') or {}
    return {
        'cache_hit_ratio': m.get('cache_hit_ratio'),
        'http_503_total': m.get('http_503_total'),
        'http_304_total': m.get('http_304_total'),
        'cache_entries': m.get('cache_entries'),
        'upstream_timeout': uf.get('upstream_timeout'),
        'upstream_error': uf.get('upstream_error'),
        'negative_cache_size': m.get('negative_cache_size'),
        'upstream_fetch_total': m.get('upstream_fetch_total'),
    }


def docker_stats():
    try:
        out = subprocess.run(
            ['docker', 'stats', '--no-stream', '--format',
             '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}',
             'china-finance-rss'],
            capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return 'error: %s' % e


def pct(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def ms(v):
    return None if v is None else round(v * 1000.0, 3)


class Pacer(object):
    """Optional token-bucket rate cap (req/s); rate None == uncapped."""

    def __init__(self, rate, t0):
        self.rate = rate
        self.t0 = t0
        self.n = 0
        self.lk = threading.Lock()

    def acquire(self, deadline):
        if not self.rate:
            return time.monotonic() < deadline
        while True:
            now = time.monotonic()
            if now >= deadline:
                return False
            with self.lk:
                if self.n < self.rate * (now - self.t0):
                    self.n += 1
                    return True
            time.sleep(0.001)


def run_load(base, pool, concurrency, seconds, max_rate=None, label='run',
             mid_cb=None):
    samples = []
    stop = threading.Event()
    t0 = time.monotonic()
    deadline = t0 + seconds
    pacer = Pacer(max_rate, t0)
    lk = threading.Lock()

    def worker():
        while not stop.is_set():
            if not pacer.acquire(deadline):
                return
            st = time.monotonic()
            if st >= deadline:
                return
            path = random.choice(pool)
            status, err, lat = fetch(base + path)
            with lk:
                samples.append((st - t0, lat, status, err, path))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, concurrency))]
    for t in threads:
        t.start()
    if mid_cb is not None:
        threading.Timer(seconds / 2.0, mid_cb).start()
    for t in threads:
        t.join()
    stop.set()
    return {'label': label, 'concurrency': concurrency, 'seconds': seconds,
            'max_rate': max_rate, 'elapsed': time.monotonic() - t0,
            'samples': samples}


def summarize(res):
    s = res['samples']
    total = len(s)
    ok = [x[1] for x in s if x[2] == 200]
    dur = res['elapsed'] or 1.0
    status_counts, err_kinds, per_sec = {}, {}, {}
    for x in s:
        status_counts[str(x[2])] = status_counts.get(str(x[2]), 0) + 1
        if x[2] != 200 and x[3]:
            err_kinds[x[3]] = err_kinds.get(x[3], 0) + 1
        b = per_sec.setdefault(int(x[0]), [0, 0])
        b[0] += 1
        if x[2] != 200:
            b[1] += 1
    return {
        'label': res['label'], 'concurrency': res['concurrency'],
        'seconds': res['seconds'], 'max_rate': res['max_rate'],
        'elapsed': round(dur, 3), 'total': total,
        'errors': total - len(ok),
        'error_rate': round((total - len(ok)) / total, 6) if total else 0,
        'rps_over_seconds': round(total / res['seconds'], 2) if res['seconds'] else 0,
        'rps_over_elapsed': round(total / dur, 2),
        'status_counts': status_counts, 'error_kinds': err_kinds,
        'p50_ms': ms(pct(ok, .50)), 'p95_ms': ms(pct(ok, .95)),
        'p99_ms': ms(pct(ok, .99)), 'max_ms': ms(max(ok, default=None)),
        'per_second': [{'sec': k, 'rps': per_sec[k][0], 'err': per_sec[k][1]}
                       for k in sorted(per_sec)],
    }


def window_stats(res, w0, w1):
    s = [x for x in res['samples'] if w0 <= x[0] < w1]
    ok = [x[1] for x in s if x[2] == 200]
    return {'window_sec': [w0, w1], 'n': len(s),
            'errors': len(s) - len(ok),
            'p50_ms': ms(pct(ok, .50)), 'p95_ms': ms(pct(ok, .95)),
            'p99_ms': ms(pct(ok, .99)), 'max_ms': ms(max(ok, default=None))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8053')
    ap.add_argument('--probe-concurrency', default='4,10')
    ap.add_argument('--probe-seconds', type=int, default=30)
    ap.add_argument('--formal-seconds', type=int, default=300)
    ap.add_argument('--max-rate', type=float, default=200.0)
    ap.add_argument('--cooldown', type=int, default=65)
    ap.add_argument('--warm-seconds', type=int, default=8)
    ap.add_argument('--control-seconds', type=int, default=0)
    ap.add_argument('--control-rate', type=float, default=0.0)
    ap.add_argument('--report-json', default='/tmp/opencode/ac_e4.json')
    a = ap.parse_args()

    pool = build_pool(True)
    uniq = sorted(set(pool))
    rep = {
        'ac': 'AC-E4',
        'base': a.base,
        'started': time.strftime('%Y-%m-%d %H:%M:%S'),
        'assertion': ('>=100 req/s over %ds, error_rate==0, '
                      'P99(120..%ds) <= 1.2 * P99(0..120)'
                      % (a.formal_seconds, a.formal_seconds)),
        'pool': {'weighted_size': len(pool), 'unique_urls': len(uniq),
                 'unique': uniq},
        'caveats': [
            'client-side end-to-end latency (PRD §3 handler-time excludes RTT);'
            ' loopback RTT negligible, includes TCP setup because server is'
            ' HTTP/1.0 without keep-alive',
            'no Accept-Encoding/gzip, matching tests/loadtest.py',
            'formal run rate-capped (--max-rate) to bound client ephemeral-port'
            ' churn; uncapped capacity shown by probes',
        ],
        'snapshots': {}, 'probes': [], 'warm': None, 'formal': None,
        'windows': {}, 'control': None, 'decision': {},
    }

    print('[0] warmup %ss c=4 ...' % a.warm_seconds)
    rep['warm'] = summarize(run_load(a.base, pool, 4, a.warm_seconds, None, 'warm'))
    rep['snapshots']['initial'] = {'healthz': snapshot_healthz(a.base),
                                   'docker': docker_stats()}
    print('    warm: %s req/s err=%d' % (rep['warm']['rps_over_elapsed'],
                                         rep['warm']['errors']))

    probes = []
    for c in [int(x) for x in a.probe_concurrency.split(',') if x.strip()]:
        print('[1] probe c=%d for %ss ...' % (c, a.probe_seconds))
        p = summarize(run_load(a.base, pool, c, a.probe_seconds, None,
                               'probe-c%d' % c))
        probes.append(p)
        print('    c=%d -> %s req/s  err=%d  p99=%sms'
              % (c, p['rps_over_elapsed'], p['errors'], p['p99_ms']))
    rep['probes'] = probes

    chosen = min(20, max([p['concurrency'] for p in probes] or [10]))
    rep['formal_concurrency'] = chosen
    rep['max_rate'] = a.max_rate

    if a.cooldown > 0:
        print('[2] cooldown %ss (drain TIME_WAIT) ...' % a.cooldown)
        time.sleep(a.cooldown)

    rep['snapshots']['pre_formal'] = {'healthz': snapshot_healthz(a.base),
                                      'docker': docker_stats()}

    def mid_cb():
        rep['snapshots']['mid_formal'] = {'healthz': snapshot_healthz(a.base),
                                          'docker': docker_stats()}
        print('    [mid] snapshot taken')

    print('[3] FORMAL %ss c=%d cap=%s req/s ...' % (a.formal_seconds, chosen,
                                                    a.max_rate))
    fres = run_load(a.base, pool, chosen, a.formal_seconds, a.max_rate,
                    'formal', mid_cb=mid_cb)
    rep['formal'] = summarize(fres)
    rep['snapshots']['post_formal'] = {'healthz': snapshot_healthz(a.base),
                                       'docker': docker_stats()}

    A = window_stats(fres, 0, 120)
    B = window_stats(fres, 120, a.formal_seconds)
    ratio = None
    if A['p99_ms'] and B['p99_ms']:
        ratio = round(B['p99_ms'] / A['p99_ms'], 4)
    rep['windows'] = {'A_first2min': A, 'B_last3min': B,
                      'p99_ratio_B_over_A': ratio}

    rate = rep['formal']['rps_over_seconds']
    err_rate = rep['formal']['error_rate']
    passed = bool(rate >= 100 and err_rate == 0 and ratio is not None
                  and ratio <= 1.2)
    rep['decision'] = {
        'threshold_rps': 100,
        'measured_rps_over_300s': rate,
        'measured_rps_over_elapsed': rep['formal']['rps_over_elapsed'],
        'error_rate': err_rate,
        'p99_A_ms': A['p99_ms'], 'p99_B_ms': B['p99_ms'],
        'p99_ratio': ratio, 'p99_ratio_limit': 1.2,
        'checks': {'rps_ge_100': rate >= 100, 'errors_zero': err_rate == 0,
                   'p99_drift_le_20pct': (ratio is not None and ratio <= 1.2)},
        'verdict': 'PASS' if passed else 'FAIL',
    }

    if a.control_seconds > 0:
        print('[4] CONTROL (no RSS) %ss c=%d cap=%s ...'
              % (a.control_seconds, chosen, a.control_rate or a.max_rate))
        rep['control'] = summarize(
            run_load(a.base, build_pool(False), chosen, a.control_seconds,
                     a.control_rate or a.max_rate, 'control-no-rss'))

    os.makedirs(os.path.dirname(a.report_json) or '.', exist_ok=True)
    with open(a.report_json, 'w') as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    d = rep['decision']
    print('=' * 66)
    print('AC-E4 verdict: %s' % d['verdict'])
    print('  rate   : %.1f req/s (>=100: %s)' % (rate, d['checks']['rps_ge_100']))
    print('  errors : %d (rate=%.4f%%, zero: %s)'
          % (rep['formal']['errors'], err_rate * 100, d['checks']['errors_zero']))
    print('  P99 A  : %s ms | P99 B: %s ms | ratio %s (<=1.2: %s)'
          % (A['p99_ms'], B['p99_ms'], ratio, d['checks']['p99_drift_le_20pct']))
    print('  report : %s' % a.report_json)
    print('=' * 66)


if __name__ == '__main__':
    main()
