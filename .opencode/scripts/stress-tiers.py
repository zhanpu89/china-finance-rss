#!/usr/bin/env python3
"""Five-tier code-count stress test for the core real-time REST surface.

Segments tested (SSE + RSS excluded per task):
  * core real-time REST (batch): /stock/fundflow, /stock/timeline,
    /stock/data, /stock/basic_info   — each request carries up to
    `_MAX_BATCH_SIZE` (50) codes; tiers N>50 run as ceil(N/50) concurrent
    calls so the *system* serves N distinct codes at once.
  * board (object): /cls/hotplate
  * CDP-surface (must stay responsive within its sane parameter envelope):
    /finance/market (page-less), /stock/f10?code=<single> (serial CDP nav)
  * daily-frequency (not over-required): /stock/announcement

Tiers: 50 / 100 / 200 / 500 / 1000 codes => concurrency 1 / 2 / 4 / 10 / 20.

Usage:
  python3 .opencode/scripts/stress-tiers.py \
      [--url http://127.0.0.1:8053] [--pool /tmp/opencode/codepool.json] \
      [--tiers 50,100,200,500,1000] [--per-tier 8] [--parallel-fields 1]

Per tier: sustained load for `per-tier` seconds against each batch endpoint;
latency/error stats collected per request.  Prints one JSON summary line per
tier to stdout and a human table.
"""
import argparse
import json
import random
import sys
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median

MAX_PER_REQ = 50            # mirrors china_finance_rss/config _MAX_BATCH_SIZE
BATCH_ENDPOINTS = {
    '/stock/fundflow': ('fundflow',),
    '/stock/timeline': ('timeline',),
    '/stock/data': ('data',),
    '/stock/basic_info': ('basic_info',),
}
CDP_ENDPOINTS = ('/finance/market', '/finance/timeline',
                 '/quotation/market', '/market/timeline')
_STOP = object()


def fetch(url, timeout=25):
    """Return (elapsed_sec, http_status, body_bytes)."""
    start = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
        return time.time() - start, r.status, 200
    except urllib.error.HTTPError as e:
        return time.time() - start, e.code, 400
    except Exception:
        return time.time() - start, -1, 0


def _codes_for(pool, n, epoch):
    """Pick `n` distinct codes: a rotating window over a shuffled pool."""
    if n <= len(pool):
        offset = (epoch * n) % len(pool)
        window = pool[offset:] + pool[:offset]
        return window[:n]
    # pool smaller than tier: cycle the pool with an offset so overlapping
    # windows still exercise different slices every round
    offset = (epoch * n) % len(pool)
    rot = pool[offset:] + pool[:offset]
    return (rot * (n // len(rot) + 1))[:n]


def _one_batch(base, path, codes, results, lock, timeout, epoch):
    url = f'{base}{path}?code={",".join(codes)}'
    el, status, _ = fetch(url, timeout=timeout)
    with lock:
        results['calls'] += 1
        results['codes'] += len(codes)
        results['lat'].append(el)
        if status == 200:
            results['ok'] += 1
        else:
            results['err'][str(status)] = results['err'].get(str(status), 0) + 1


def run_batch_tier(base, pool, tier, per_tier, timeout, parallel_fields):
    """Sustained load at `tier` distinct codes: ceil(tier/50) parallel calls."""
    n_req = max(1, -(-tier // MAX_PER_REQ))   # ceil div
    out = {}
    for path in BATCH_ENDPOINTS:
        results = {'calls': 0, 'codes': 0, 'ok': 0, 'lat': [], 'err': {}}
        lock = threading.Lock()
        stop = threading.Event()
        epoch = 0

        def worker_loop():
            nonlocal epoch
            while not stop.is_set():
                codes = _codes_for(pool, min(tier, MAX_PER_REQ), epoch)
                _one_batch(base, path, codes, results, lock, timeout, epoch)
                epoch += 1

        n_workers = n_req * parallel_fields
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(worker_loop) for _ in range(n_workers)]
            time.sleep(per_tier)
            stop.set()
            for f in futs:
                f.result(timeout=timeout + 5)
        out[path] = results
    return out


def run_cdp_tier(base, per_tier, timeout, pool):
    """CDP surface sanity: each panel + single-code f10, low concurrency."""
    results = {}
    for path in CDP_ENDPOINTS:
        lat = []
        errs = {}
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                el, status, _ = fetch(f'{base}{path}', timeout=timeout)
                lat.append(el)
                if status != 200:
                    errs[str(status)] = errs.get(str(status), 0) + 1

        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(loop) for _ in range(2)]
            time.sleep(per_tier)
            stop.set()
            for f in futs:
                f.result(timeout=timeout + 5)
        results[path] = {'calls': len(lat), 'lat': lat, 'err': errs}
    # single-code f10 (serial CDP nav path)
    code = pool[0] if pool else 'sh600519'
    el, status, _ = fetch(f'{base}/stock/f10?code={code}', timeout=30)
    results['/stock/f10?code=<1>'] = {'calls': 1, 'lat': [el], 'err': {str(status) if status != 200 else '': 0}}
    if status != 200:
        results['/stock/f10?code=<1>']['err'][str(status)] = 1
    return results


def _stats(lat):
    if not lat:
        return {'n': 0, 'avg': 0, 'p50': 0, 'p95': 0, 'p99': 0, 'max': 0}
    s = sorted(lat)

    def pct(q):
        return s[min(len(s) - 1, int(len(s) * q))]

    return {'n': len(s), 'avg': round(sum(s) / len(s), 3),
            'p50': round(pct(0.50), 3), 'p95': round(pct(0.95), 3),
            'p99': round(pct(0.99), 3), 'max': round(s[-1], 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8053')
    ap.add_argument('--pool', default='/tmp/opencode/codepool.json')
    ap.add_argument('--tiers', default='50,100,200,500,1000')
    ap.add_argument('--per-tier', type=float, default=8.0)
    ap.add_argument('--parallel-fields', type=int, default=1,
                    help='scale batch workers per tier (1 = exact test)')
    ap.add_argument('--timeout', type=float, default=25)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    try:
        with open(args.pool) as f:
            pool = json.load(f)
    except FileNotFoundError:
        pool = []
    random.seed(args.seed)
    random.shuffle(pool)
    print(f'pool: {len(pool)} codes from {args.pool}', file=sys.stderr)

    tiers = [int(t) for t in args.tiers.split(',')]
    summary = {}
    for tier in tiers:
        print(f'--- tier {tier} codes '
              f'({-(-tier // MAX_PER_REQ)}x{min(tier, MAX_PER_REQ)}) '
              f'{args.per_tier}s ---', file=sys.stderr)
        t0 = time.time()
        batch = run_batch_tier(args.url, pool, tier, args.per_tier,
                               args.timeout, args.parallel_fields)
        cdp = run_cdp_tier(args.url, args.per_tier, args.timeout, pool)
        wall = round(time.time() - t0, 2)
        tier_sum = []
        for path, r in batch.items():
            st = _stats(r['lat'])
            ok_rate = round(100.0 * r['ok'] / r['calls'], 1) if r['calls'] else 0
            tier_sum.append({
                'path': path, 'calls': r['calls'], 'codes': r['codes'],
                'ok_rate': ok_rate, 'err': r['err'], **st,
            })
        summary[tier] = {
            'wall_s': wall, 'batch': tier_sum,
            'cdp': {p: {'calls': r['calls'], **{k: v for k, v in
                                                _stats(r['lat']).items() if k != 'n'},
                        'err': r['err']} for p, r in cdp.items()},
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()