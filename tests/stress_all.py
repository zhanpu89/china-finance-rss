#!/usr/bin/env python3
"""Comprehensive stress test — all endpoints except news & 龙虎榜.

Requirements:
  - All responses ≤15s
  - No data cross-contamination
  - Memory stable <1.5G
  - Thread-safe

Usage:
    python tests/stress_all.py [--concurrency N] [--requests N] [--url URL]

Requires server running (default http://localhost:8053).
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = os.environ.get('STRESS_URL', 'http://localhost:8053')
MAX_LATENCY = 15.0

STOCK_CODES = [
    'sh600519', 'sz000001', 'sz300999', 'sh601318', 'sz002415',
    'sh600036', 'sz300750', 'sz000858', 'sh601012', 'sz002594',
    'sh600276', 'sz300059', 'sz002230', 'sh601899', 'sz000002',
    'sh600030', 'sh600887', 'sz300015', 'sh601166', 'sz002714',
    'sh600900', 'sz002475', 'sh600309', 'sz000651', 'sh600585',
]

ENDPOINTS = {
    'basic_info':   '/stock/basic_info',
    'f10':          '/stock/f10',
    'stock_data':   '/stock/data',
    'fundflow':     '/stock/fundflow',
    'timeline':     '/stock/timeline',
    'announcement': '/stock/announcement',
}

GLOBAL_ENDPOINTS = {
    'finance/market':     '/finance/market',
    'finance/timeline':   '/finance/timeline',
    'quotation/market':   '/quotation/market',
    'market/timeline':    '/market/timeline',
    'cls/hotplate':       '/cls/hotplate',
}

def fetch_json(url, timeout=30):
    start = time.time()
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        body = resp.read()
        elapsed = time.time() - start
        data = json.loads(body)
        return elapsed, 200, data
    except urllib.error.HTTPError as e:
        return time.time() - start, e.code, {'error': f'HTTP {e.code}'}
    except Exception as e:
        return time.time() - start, -1, {'error': f'{type(e).__name__}: {e}'}


def check_endpoint(endpoint, code, data):
    """Validate response for a given endpoint+code. Returns (ok, errors)."""
    errors = []
    if data is None or data is False:
        errors.append('null/false response')
        return False, errors
    if 'error' in data:
        errors.append(f"server_error: {data['error']}")
        return False, errors

    if endpoint == '/stock/basic_info':
        result = data.get(code)
        if result is None:
            errors.append('null result for code')
        else:
            if not isinstance(result, dict):
                errors.append(f'not dict: {type(result).__name__}')
                return False, errors
            if not result.get('sector_name'):
                errors.append('missing sector_name')
            d = result.get('data')
            if isinstance(d, dict):
                secu = d.get('secu_code', '')
                if secu.upper() != code.upper():
                    errors.append(f'code mismatch: req={code}, got={secu}')
    elif endpoint == '/stock/f10':
        result = data.get(code)
        if result is None:
            errors.append('null result for code')
        elif not isinstance(result, dict):
            errors.append(f'not dict: {type(result).__name__}')
        else:
            bi = result.get('basic_info') or {}
            if not bi.get('SecuCode'):
                errors.append('missing SecuCode in basic_info')
            elif bi['SecuCode'].upper() != code.upper():
                errors.append(f'code mismatch: req={code}, got={bi["SecuCode"]}')
    elif endpoint == '/stock/data':
        result = data.get(code)
        if result is None:
            errors.append('null result for code')
        elif not isinstance(result, dict):
            errors.append(f'not dict: {type(result).__name__}')
        else:
            for key in ('stock_detail', 'stock_plate', 'articles', 'stock_announcement'):
                if key not in result:
                    errors.append(f'missing key: {key}')
    elif endpoint in ('/stock/fundflow', '/stock/timeline', '/stock/announcement'):
        result = data.get(code)
        if result is None:
            errors.append('null result for code')
        elif result is False:
            errors.append('false result')
    elif endpoint == '/finance/market':
        for key in ('advance_decline', 'articles', 'market_sentiment', 'anchor', 'live_refresh'):
            if key not in data:
                errors.append(f'missing key: {key}')
    elif endpoint == '/finance/timeline':
        if not isinstance(data, dict):
            errors.append(f'not dict: {type(data).__name__}')
    elif endpoint == '/quotation/market':
        for key in ('stock_ranking', 'hot_plate', 'stock_ipo', 'index_home', 'bj_stock_info'):
            if key not in data:
                errors.append(f'missing key: {key}')
    elif endpoint == '/market/timeline':
        if not isinstance(data, dict):
            errors.append(f'not dict: {type(data).__name__}')
    elif endpoint == '/cls/hotplate':
        for key in ('plate_industry', 'plate_concept', 'plate_area', 'hot_plates'):
            if key not in data:
                errors.append(f'missing key: {key}')

    return len(errors) == 0, errors


def run_stress(concurrency, total_stock_requests, global_requests):
    """Run stress test: stock endpoints + global endpoints concurrently."""
    results = []

    codes = (STOCK_CODES * (total_stock_requests // len(STOCK_CODES) + 1))[:total_stock_requests]

    def stock_task(endpoint, code):
        url = f'{BASE_URL}{endpoint}?code={code}'
        elapsed, status, data = fetch_json(url, timeout=MAX_LATENCY + 5)
        if status != 200:
            return {'endpoint': endpoint, 'code': code, 'ok': False, 'elapsed': elapsed,
                    'errors': [f'HTTP {status}']}
        if 'error' in data:
            return {'endpoint': endpoint, 'code': code, 'ok': False, 'elapsed': elapsed,
                    'errors': [data['error']]}
        ok, errors = check_endpoint(endpoint, code, data)
        return {'endpoint': endpoint, 'code': code, 'ok': ok, 'elapsed': elapsed, 'errors': errors}

    def global_task(endpoint):
        url = f'{BASE_URL}{endpoint}'
        elapsed, status, data = fetch_json(url, timeout=MAX_LATENCY + 5)
        if status != 200:
            return {'endpoint': endpoint, 'code': '', 'ok': False, 'elapsed': elapsed,
                    'errors': [f'HTTP {status}']}
        if 'error' in data:
            return {'endpoint': endpoint, 'code': '', 'ok': False, 'elapsed': elapsed,
                    'errors': [data['error']]}
        ok, errors = check_endpoint(endpoint, '', data)
        return {'endpoint': endpoint, 'code': '', 'ok': ok, 'elapsed': elapsed, 'errors': errors}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for ep_name, ep_path in ENDPOINTS.items():
            for c in codes:
                futures[pool.submit(stock_task, ep_path, c)] = (ep_path, c)

        for g_name, g_path in GLOBAL_ENDPOINTS.items():
            for _ in range(global_requests):
                futures[pool.submit(global_task, g_path)] = (g_path, '')

        for f in as_completed(futures):
            r = f.result()
            results.append(r)

    results.sort(key=lambda x: x['elapsed'], reverse=True)
    return results


def print_results(results, label):
    total = len(results)
    ok = sum(1 for r in results if r['ok'])
    fail = total - ok
    times = [r['elapsed'] for r in results]
    times.sort()
    latency_fail = sum(1 for t in times if t > MAX_LATENCY)

    # Group by endpoint
    by_ep = {}
    for r in results:
        by_ep.setdefault(r['endpoint'], []).append(r)

    print(f'\n{"="*70}')
    print(f'Results: {label}')
    print(f'  Total: {total}  OK: {ok}  Fail: {fail}')
    if latency_fail:
        print(f'  ⚠ LATENCY >{MAX_LATENCY}s: {latency_fail}')
    if times:
        print(f'  Latency: min={times[0]:.3f}s  p50={times[len(times)//2]:.3f}s  '
              f'p95={times[int(len(times)*0.95)]:.3f}s  '
              f'p99={times[int(len(times)*0.99)]:.3f}s  '
              f'max={times[-1]:.3f}s')

    if by_ep:
        print(f'\n{"endpoint":<22} {"total":>6} {"ok":>5} {"fail":>5} {"p95(s)":>7} {"max(s)":>7}')
        print('-' * 52)
        for ep, recs in sorted(by_ep.items()):
            ep_ok = sum(1 for r in recs if r['ok'])
            ep_times = sorted([r['elapsed'] for r in recs])
            ep_max = ep_times[-1] if ep_times else 0
            ep_p95 = ep_times[int(len(ep_times)*0.95)] if len(ep_times) > 5 else ep_max
            print(f'{ep:<22} {len(recs):>6} {ep_ok:>5} {len(recs)-ep_ok:>5} '
                  f'{ep_p95:>7.3f} {ep_max:>7.3f}')

    all_errors = {}
    for r in results:
        if not r['ok'] and r.get('errors'):
            for e in r['errors']:
                all_errors.setdefault(e, []).append(f'{r["endpoint"]}/{r["code"]}')
    if all_errors:
        print(f'\n  Error breakdown ({len(all_errors)} unique):')
        for err, ctx in sorted(all_errors.items(), key=lambda x: -len(x[1])):
            print(f'    [{len(ctx)}x] {err}')
            for c in ctx[:3]:
                print(f'      → {c}')
    print()

    return ok == total and latency_fail == 0


def get_memory_mb():
    try:
        import subprocess
        r = subprocess.run(
            ['docker', 'stats', 'china-finance-rss', '--no-stream', '--format', '{{.MemUsage}}'],
            capture_output=True, text=True, timeout=5)
        out = r.stdout.strip()
        if 'MiB' in out:
            return float(out.split('/')[0].strip().replace('MiB', ''))
        if 'GiB' in out:
            return float(out.split('/')[0].strip().replace('GiB', '')) * 1024
    except:
        pass
    try:
        with open('/proc/1/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except:
        pass
    return None


def wait_for_server(url, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            if resp.status == 200:
                return True
        except:
            pass
        time.sleep(2)
    return False


def main():
    concurrency = 15
    total_stock = 60
    global_req = 60

    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--concurrency' and i + 1 < len(args):
            concurrency = int(args[i + 1])
        if a == '--requests' and i + 1 < len(args):
            total_stock = int(args[i + 1])
            global_req = total_stock

    print(f'Comprehensive Stress Test — All non-news endpoints')
    print(f'  Concurrency: {concurrency}')
    print(f'  Stock-limited endpoints: {len(ENDPOINTS)} × {total_stock} = {len(ENDPOINTS)*total_stock} requests')
    print(f'  Global endpoints: {len(GLOBAL_ENDPOINTS)} × {global_req} = {len(GLOBAL_ENDPOINTS)*global_req} requests')
    print(f'  Allowable max latency: {MAX_LATENCY}s')
    print(f'  Server: {BASE_URL}')
    print()

    if not wait_for_server(f'{BASE_URL}/healthz'):
        print('ERROR: Server not reachable')
        sys.exit(1)
    print('Server reachable')

    # Track memory before
    mem_before = get_memory_mb()
    print(f'Memory before: {mem_before:.0f} MiB' if mem_before else 'Memory: N/A')

    total_req = len(ENDPOINTS) * total_stock + len(GLOBAL_ENDPOINTS) * global_req
    n_warmup = max(5, total_req // 10)
    warmup_codes = STOCK_CODES[:5]

    print(f'\nWarmup phase ({n_warmup} requests)...')
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = []
        for ep in ENDPOINTS.values():
            for c in warmup_codes:
                futs.append(pool.submit(fetch_json, f'{BASE_URL}{ep}?code={c}', MAX_LATENCY + 5))
        for g in GLOBAL_ENDPOINTS.values():
            futs.append(pool.submit(fetch_json, f'{BASE_URL}{g}', MAX_LATENCY + 5))
        for _ in range(global_req // 5):
            for g in GLOBAL_ENDPOINTS.values():
                futs.append(pool.submit(fetch_json, f'{BASE_URL}{g}', MAX_LATENCY + 5))
        for f in as_completed(futs):
            pass
    print('Warmup done')

    # Memory check after warmup
    mem_warm = get_memory_mb()
    if mem_warm:
        print(f'Memory after warmup: {mem_warm:.0f} MiB')

    print(f'\nStress phase ({total_req} requests)...')
    results = run_stress(concurrency, total_stock, global_req)
    print('Stress done')

    mem_stress = get_memory_mb()
    print(f'Memory after stress: {mem_stress:.0f} MiB' if mem_stress else 'Memory: N/A')
    if mem_before and mem_stress:
        delta = mem_stress - mem_before
        print(f'Memory delta: {delta:+.0f} MiB {"⚠ OVER LIMIT!" if delta > 100 else "✓"}')
        if mem_stress > 1536:
            print('⚠ TOTAL MEMORY > 1.5 GiB!')
    print()

    success = print_results(results, f'{total_req} requests, concurrency={concurrency}')

    print()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
