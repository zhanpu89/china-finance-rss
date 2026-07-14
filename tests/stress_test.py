#!/usr/bin/env python3
"""Stress test for China Finance RSS Bridge.

Tests all endpoints (except 龙虎榜 daily endpoint) under concurrent load.
Reports latency distribution and error rates.
Run: python tests/stress_test.py [host:port]
"""
import json
import sys
import threading
import time as tm
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8053'
WARMUP_TIMEOUT = 60
CONCURRENCY = 20
ITERATIONS = 3  # run 3 iterations to see caching effects

ENDPOINTS = {
    # RSS feed endpoints (REST, no CDP)
    'cls_telegraph':     (f'{BASE}/cls/telegraph', 'rss'),
    'eastmoney_kuaixun': (f'{BASE}/eastmoney/kuaixun', 'rss'),
    'ths_kuaixun':       (f'{BASE}/ths/kuaixun', 'rss'),
    'jin10_flash':       (f'{BASE}/jin10/flash', 'rss'),
    'wallstreetcn_live': (f'{BASE}/wallstreetcn/live', 'rss'),

    # JSON-REST endpoints (no CDP)
    'cls_hotplate':      (f'{BASE}/cls/hotplate', 'json'),

    # CDP heartbeat pages (read-only, no navigation)
    'finance_market':    (f'{BASE}/finance/market', 'json'),
    'finance_timeline':  (f'{BASE}/finance/timeline', 'json'),
    'quotation_market':  (f'{BASE}/quotation/market', 'json'),
    'market_timeline':   (f'{BASE}/market/timeline', 'json'),

    # CDP navigate_stock pages (serialized via _navigate_lock)
    'stock_data':        (f'{BASE}/stock/data?code=sh600519', 'json'),
    'stock_basic_info':  (f'{BASE}/stock/basic_info?code=sh600519', 'json'),
    'stock_f10':         (f'{BASE}/stock/f10?code=sh600519', 'json'),

    # REST + CDP evaluate_fetch (no navigation)
    'stock_fundflow':    (f'{BASE}/stock/fundflow?code=sh600519', 'json'),
    'stock_timeline':    (f'{BASE}/stock/timeline?code=sh600519', 'json'),

    # Batch endpoints
    'stock_basic_info_batch':  (f'{BASE}/stock/basic_info?code=sh600519,sh000001,sz000001,sh601318,sz399001', 'json'),
    'stock_f10_batch':         (f'{BASE}/stock/f10?code=sh600519,sh000001,sz000001,sh601318,sz399001', 'json'),
    'stock_fundflow_batch':    (f'{BASE}/stock/fundflow?code=sh600519,sh000001,sz000001,sh601318,sz399001', 'json'),
    'stock_timeline_batch':    (f'{BASE}/stock/timeline?code=sh600519,sh000001,sz000001,sh601318,sz399001', 'json'),
}


def fetch(url, timeout=30):
    start = tm.time()
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        body = resp.read()
        resp.close()
        elapsed = tm.time() - start
        return elapsed, resp.status, body
    except Exception as e:
        return tm.time() - start, -1, str(e)


def warmup():
    print('Warming up...')
    for name, (url, _) in ENDPOINTS.items():
        # Don't warm up batch or CDP navigate endpoints individually
        if any(s in name for s in ('batch', 'f10', 'basic_info', 'fundflow', 'stock_data', 'stock_timeline')):
            continue
        try:
            elapsed, status, body = fetch(url, WARMUP_TIMEOUT)
            if status == 200:
                print(f'  {name}: {elapsed:.1f}s OK')
            else:
                print(f'  {name}: {elapsed:.1f}s status={status}')
        except Exception as e:
            print(f'  {name}: FAILED ({e})')
        tm.sleep(0.2)
    # Warm up stock navigate endpoints sequentially (they share the same CDP page)
    stock_urls = [
        f'{BASE}/stock/data?code=sh600519',
        f'{BASE}/stock/basic_info?code=sh600519',
        f'{BASE}/stock/f10?code=sh600519',
    ]
    for url in stock_urls:
        try:
            elapsed, status, body = fetch(url, WARMUP_TIMEOUT)
            print(f'  stock_warmup: {elapsed:.1f}s OK' if status == 200 else f'  stock_warmup: {elapsed:.1f}s FAIL')
        except Exception as e:
            print(f'  stock_warmup: FAILED ({e})')
        tm.sleep(1)


def run_test(iteration):
    print(f'\n=== Iteration {iteration+1}/{ITERATIONS} ===')
    results = {}
    lock = threading.Lock()

    def test_endpoint(name, url, fmt):
        elapsed, status, body = fetch(url)
        error = None
        if status != 200:
            error = f'status={status}'
        elif fmt == 'json':
            try:
                data = json.loads(body)
                if isinstance(data, dict) and 'error' in data:
                    error = f"error='{data['error']}'"
            except json.JSONDecodeError:
                error = 'invalid json'
        elif fmt == 'rss':
            if not body.startswith(b'<?xml') and b'<rss' not in body:
                # Check for error RSS
                if b'error' in body and b'Exception' in body:
                    error = 'rss error item'
        with lock:
            results.setdefault(name, []).append((elapsed, status, error))

    all_threads = []
    for name, (url, fmt) in ENDPOINTS.items():
        for _ in range(CONCURRENCY):
            t = threading.Thread(target=test_endpoint, args=(name, url, fmt))
            all_threads.append(t)

    start = tm.time()
    for t in all_threads:
        t.start()
    for t in all_threads:
        t.join()
    wall = tm.time() - start

    # Report
    print(f'Wall time: {wall:.1f}s  ({sum(1 for _ in all_threads)} requests total)')
    for name in ENDPOINTS:
        entries = results.get(name, [])
        if not entries:
            print(f'  {name}: NO RESULTS')
            continue
        times = [e[0] for e in entries]
        errors = [(i, e[2]) for i, e in enumerate(entries) if e[2] or e[1] != 200]
        avg = sum(times) / len(times)
        p50 = sorted(times)[len(times)//2]
        p95 = sorted(times)[int(len(times)*0.95)]
        p99 = sorted(times)[int(len(times)*0.99)]
        max_t = max(times)
        err_count = len(errors)
        status_str = f'OK' if err_count == 0 else f'ERRS={err_count}'
        print(f'  {name:35s} avg={avg:.1f}s p50={p50:.1f}s p95={p95:.1f}s p99={p99:.1f}s max={max_t:.1f}s {status_str}')

    return results


if __name__ == '__main__':
    warmup()
    all_ok = True
    for i in range(ITERATIONS):
        results = run_test(i)
        for name in ENDPOINTS:
            entries = results.get(name, [])
            for e in entries:
                if e[2] or e[1] != 200:
                    print(f'FAIL: {name} returned error: {e[2]}')
                    all_ok = False
    sys.exit(0 if all_ok else 1)
