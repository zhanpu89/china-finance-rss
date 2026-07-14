#!/usr/bin/env python3
"""Stress test for /stock/basic_info — concurrent, validate sector_name & no cross-contamination.

Usage:
    python tests/stress_basic_info.py [--concurrency N] [--requests N] [--url URL] [--all-endpoints]

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
    'sh600519',  # 贵州茅台 → 食品饮料
    'sz000001',  # 平安银行 → 银行
    'sz300999',  # 金龙鱼 → 食品饮料
    'sh601318',  # 中国平安 → 保险
    'sz002415',  # 海康威视 → 计算机
    'sh600036',  # 招商银行 → 银行
    'sz300750',  # 宁德时代 → 电力设备
    'sz000858',  # 五粮液 → 食品饮料
    'sh601012',  # 隆基绿能 → 电力设备
    'sz002594',  # 比亚迪 → 汽车
    'sh600276',  # 恒瑞医药 → 医药生物
    'sz300059',  # 东方财富 → 非银金融
    'sz002230',  # 科大讯飞 → 计算机
    'sh601899',  # 紫金矿业 → 有色金属
    'sz000002',  # 万科A → 房地产
    'sh600030',  # 中信证券 → 非银金融
    'sh600887',  # 伊利股份 → 食品饮料
    'sz300015',  # 爱尔眼科 → 医药生物
    'sh601166',  # 兴业银行 → 银行
    'sz002714',  # 牧原股份 → 农林牧渔
    'sh600900',  # 长江电力 → 公用事业
    'sz002475',  # 立讯精密 → 电子
    'sh600309',  # 万华化学 → 基础化工
    'sz000651',  # 格力电器 → 家用电器
    'sh600585',  # 海螺水泥 → 建筑材料
]

ENDPOINTS = {
    'basic_info': '/stock/basic_info',
}

# Expected sectors (申万一级行业) — approximate, used as sanity check
EXPECTED_SECTORS = {
    'sh600519': '食品饮料',
    'sz000001': '银行',
    'sh601318': '保险',
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


def check_basic_info(code, result_data):
    """Validate a single /stock/basic_info response. Returns (ok, errors_list)."""
    errors = []
    if result_data is None:
        return False, ['null response']
    if not isinstance(result_data, dict):
        return False, [f'not dict: {type(result_data).__name__}']
    if 'error' in result_data:
        return False, [f"server error: {result_data['error']}"]
    # Must have sector_name
    sector = result_data.get('sector_name')
    if not sector:
        errors.append('missing sector_name')
    elif not isinstance(sector, str) or len(sector) < 2:
        errors.append(f'invalid sector_name: {sector!r}')
    # Must have data dict
    d = result_data.get('data')
    if not isinstance(d, dict):
        errors.append(f'missing data dict')
    else:
        # Verify secu_code matches
        secu = d.get('secu_code', '')
        if secu.upper() != code.upper():
            errors.append(f'code mismatch: requested={code}, got={secu}')
    # If we know the expected sector, verify it
    if code in EXPECTED_SECTORS:
        expected = EXPECTED_SECTORS[code]
        if sector != expected:
            errors.append(f'sector mismatch: expected={expected}, got={sector}')
    return len(errors) == 0, errors


def run_basic_info_stress(concurrency, total_requests):
    codes = (STOCK_CODES * (total_requests // len(STOCK_CODES) + 1))[:total_requests]
    results = []

    print(f'\n{"="*70}')
    print(f'Stress Test: /stock/basic_info')
    print(f'  Concurrency: {concurrency}  |  Requests: {total_requests}  |  Stocks: {len(STOCK_CODES)}')
    print(f'  Max allowed latency: {MAX_LATENCY}s')
    print(f'  URL: {BASE_URL}')
    print(f'{"="*70}')
    print(f'{"code":<12} {"ok":<4} {"time":<7} {"latency_ok":<10} {"errors"}')
    print(f'{"-"*70}')

    def task(code):
        elapsed, status, data = fetch_json(f'{BASE_URL}/stock/basic_info?code={code}', timeout=MAX_LATENCY + 5)
        if status != 200:
            return {'code': code, 'ok': False, 'elapsed': elapsed, 'errors': [f'HTTP {status}']}
        # data is {code: {result}} or {error: ...}
        if 'error' in data:
            return {'code': code, 'ok': False, 'elapsed': elapsed, 'errors': [data['error']]}
        result = data.get(code)
        ok, errors = check_basic_info(code, result)
        return {'code': code, 'ok': ok, 'elapsed': elapsed, 'errors': errors, 'result': result}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        fut = {pool.submit(task, c): c for c in codes}
        for f in as_completed(fut):
            r = f.result()
            results.append(r)

    results.sort(key=lambda x: x['elapsed'], reverse=True)
    return results


def run_multi_endpoint_stress(concurrency, total_requests):
    """Run all endpoints concurrently with varied stock codes."""
    codes = (STOCK_CODES * (total_requests // len(STOCK_CODES) + 1))[:total_requests]
    results = []

    print(f'\n{"="*70}')
    print(f'Stress Test: ALL stock endpoints')
    print(f'  Concurrency: {concurrency}  |  Requests: {total_requests}  |  Stocks: {len(STOCK_CODES)}')
    print(f'  Max allowed latency: {MAX_LATENCY}s')
    print(f'  URL: {BASE_URL}')
    print(f'{"="*70}')
    print(f'{"endpoint":<20} {"code":<12} {"ok":<4} {"time":<7} {"errors"}')
    print(f'{"-"*70}')

    endpoint_paths = {
        'basic_info': '/stock/basic_info',
        'f10': '/stock/f10',
        'fundflow': '/stock/fundflow',
        'timeline': '/stock/timeline',
        'stock_data': '/stock/data',
    }

    def task(path, code):
        url = f'{BASE_URL}{path}?code={code}'
        elapsed, status, data = fetch_json(url, timeout=MAX_LATENCY + 5)
        if status != 200:
            return {'endpoint': path, 'code': code, 'ok': False, 'elapsed': elapsed, 'errors': [f'HTTP {status}']}
        if 'error' in data:
            return {'endpoint': path, 'code': code, 'ok': False, 'elapsed': elapsed, 'errors': [data['error']]}
        # basic_info specific check
        errors = []
        if path == '/stock/basic_info':
            result = data.get(code)
            if result is None:
                errors.append('null result for code')
            elif not result.get('sector_name'):
                errors.append('missing sector_name')
            # Verify secu_code matches (no cross-contamination)
            secu = ((result or {}).get('data') or {}).get('secu_code') or ''
            if secu.upper() != code.upper():
                errors.append(f'code mismatch: code={code}, got_secu={secu}')
        else:
            if not data.get(code):
                errors.append('null result for code')
        return {'endpoint': path, 'code': code, 'ok': len(errors) == 0, 'elapsed': elapsed, 'errors': errors}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        fut = {}
        for path in endpoint_paths.values():
            for c in codes[:max(3, total_requests // len(endpoint_paths))]:
                fut[pool.submit(task, path, c)] = (path, c)
        for f in as_completed(fut):
            r = f.result()
            results.append(r)

    results.sort(key=lambda x: x['elapsed'], reverse=True)
    return results


def print_summary(results, label):
    total = len(results)
    ok = sum(1 for r in results if r['ok'])
    fail = total - ok
    times = [r['elapsed'] for r in results]
    times.sort()

    latency_fail = sum(1 for t in times if t > MAX_LATENCY)

    print(f'\n{"="*70}')
    print(f'Results: {label}')
    print(f'{"="*70}')
    print(f'  Total:     {total}')
    print(f'  OK:        {ok}')
    print(f'  Fail:      {fail}')
    if latency_fail:
        print(f'  ⚠ LATENCY >{MAX_LATENCY}s: {latency_fail}')
    if times:
        print(f'  Latency:   min={times[0]:.3f}s  p50={times[len(times)//2]:.3f}s  '
              f'p95={times[int(len(times)*0.95)]:.3f}s  '
              f'p99={times[int(len(times)*0.99)]:.3f}s  '
              f'max={times[-1]:.3f}s')

    # Collect all unique errors
    all_errors = {}
    for r in results:
        if not r['ok'] and r.get('errors'):
            for e in r['errors']:
                all_errors[e] = all_errors.get(e, 0) + 1
    if all_errors:
        print(f'\n  Error breakdown:')
        for err, count in sorted(all_errors.items(), key=lambda x: -x[1]):
            print(f'    {err}: {count}')

    return ok == total and latency_fail == 0


def memory_usage():
    """Return RSS in MB."""
    try:
        with open(f'/proc/{os.getpid()}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except:
        pass
    try:
        import subprocess
        r = subprocess.run(['ps', '-o', 'rss=', '-p', '1'], capture_output=True, text=True, timeout=3)
        if r.stdout.strip():
            return int(r.stdout.strip()) / 1024
    except:
        pass
    return None


def main():
    concurrency = 15
    total_requests = 60
    all_endpoints = False

    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--concurrency' and i + 1 < len(args):
            concurrency = int(args[i + 1])
        if a == '--requests' and i + 1 < len(args):
            total_requests = int(args[i + 1])
        if a == '--all-endpoints':
            all_endpoints = True

    mem_before = memory_usage()
    print(f'Memory before: {mem_before:.0f} MB' if mem_before else 'Memory: N/A')

    if all_endpoints:
        results = run_multi_endpoint_stress(concurrency, total_requests)
    else:
        results = run_basic_info_stress(concurrency, total_requests)

    mem_after = memory_usage()
    print(f'Memory after:  {mem_after:.0f} MB' if mem_after else 'Memory: N/A')
    if mem_before and mem_after:
        delta = mem_after - mem_before
        print(f'Memory delta:  {delta:+.0f} MB {"⚠" if delta > 100 else "✓"}')

    success = print_summary(results, 'basic_info stress' if not all_endpoints else 'multi-endpoint')
    print()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
