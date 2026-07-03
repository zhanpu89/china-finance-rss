#!/usr/bin/env python3
"""Stress test for /stock/data?code=XXX — one-shot CDP stock page.

Usage:
    python tests/stress_stock.py [--concurrency N] [--total N]
"""

import json
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

STOCK_CODES = [
    'sz300139',  # 福星晓程 (default)
    'sh600519',  # 贵州茅台
    'sz000001',  # 平安银行
    'sz300999',  # 金龙鱼
    'sh601318',  # 中国平安
    'sz002415',  # 海康威视
    'sh600036',  # 招商银行
    'sz300750',  # 宁德时代
    'sz000858',  # 五粮液
    'sh601012',  # 隆基绿能
    'sz002594',  # 比亚迪
    'sh600276',  # 恒瑞医药
    'sz300059',  # 东方财富
    'sz002230',  # 科大讯飞
    'sh601899',  # 紫金矿业
]

BASE_URL = 'http://localhost:8053'


def fetch_stock(code, timeout=30):
    url = f'{BASE_URL}/stock/data?code={code}'
    start = time.time()
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        body = resp.read()
        elapsed = time.time() - start
        data = json.loads(body)
        if 'error' in data:
            return {'code': code, 'ok': False, 'elapsed': elapsed, 'error': data['error']}
        bi = (data.get('basic_info') or {}).get('data') or {}
        actual_code = bi.get('secu_code', '')
        return {
            'code': code, 'ok': True, 'elapsed': elapsed,
            'keys': list(data.keys()),
            'actual_code': actual_code,
            'matched': actual_code == code,
        }
    except urllib.error.HTTPError as e:
        return {'code': code, 'ok': False, 'elapsed': time.time() - start, 'error': f'HTTP {e.code}'}
    except Exception as e:
        return {'code': code, 'ok': False, 'elapsed': time.time() - start, 'error': f'{type(e).__name__}: {e}'}


def main():
    concurrency = 3
    total = 15

    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--concurrency' and i + 1 < len(args):
            concurrency = int(args[i + 1])
        if a == '--total' and i + 1 < len(args):
            total = int(args[i + 1])

    codes = (STOCK_CODES * (total // len(STOCK_CODES) + 1))[:total]

    print(f'Stock CDP stress test  —  {total} requests, concurrency={concurrency}')
    print(f'{"=" * 60}')
    print(f'{"code":<14} {"ok":<4} {"elapsed":<8} {"keys":<6} {"note"}')
    print(f'{"-" * 60}')

    ok = 0
    fail = 0
    times = []
    mismatches = []

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        fut = {pool.submit(fetch_stock, c): c for c in codes}
        for f in as_completed(fut):
            r = f.result()
            times.append(r['elapsed'])
            if r['ok']:
                ok += 1
                note = ''
                if not r['matched']:
                    mismatches.append(r)
                    note = f"code mismatch: got {r['actual_code']}"
                print(f'{r["code"]:<14} {"✓":<4} {r["elapsed"]:<8.2f} {len(r["keys"]):<6} {note}')
            else:
                fail += 1
                print(f'{r["code"]:<14} {"✗":<4} {r["elapsed"]:<8.2f} {"":<6} {r["error"]}')

    print(f'{"=" * 60}')
    if times:
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        p99 = times[int(len(times) * 0.99)]
        print(f'Total: {ok + fail}  |  OK: {ok}  |  Fail: {fail}')
        print(f'Latency:  min={times[0]:.2f}s  p50={p50:.2f}s  p95={p95:.2f}s  p99={p99:.2f}s  max={times[-1]:.2f}s')
    if mismatches:
        print(f'\n⚠  {len(mismatches)} stock code mismatches:')
        for m in mismatches:
            print(f'  {m["code"]} → returned {m["actual_code"]}')


if __name__ == '__main__':
    main()
