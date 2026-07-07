"""Stress test for China Finance RSS Bridge.

Tests all endpoints under concurrent load to find thread exhaustion,
CDP navigation deadlocks, and memory leaks.

Usage:
    python tests/stress_test.py [--total 2000] [--concurrent 30] [--pids]
"""

import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error

BASE = 'http://localhost:8053'
TOTAL = 2000
CONCURRENT = 30
TIMEOUT = 30

ENDPOINTS = [
    # RSS feeds (no CDP needed)
    '/cls/telegraph',
    '/eastmoney/kuaixun',
    '/ths/kuaixun',
    '/jin10/flash',
    '/wallstreetcn/live',
    # JSON endpoints (no CDP needed)
    '/cls/hotplate',
    '/stock/fundflow?code=sh600519',
    '/stock/fundflow?code=sh600519,sz000001,bk0720',
    '/stock/timeline?code=sh600519',
    '/stock/timeline?code=sh600519,sz000001',
    '/stock/f10?code=sh600519',
    # JSON endpoints (CDP needed)
    '/stock/data?code=sh600519',
    '/stock/data?code=sz000001',
    '/stock/data?code=sh000001',
    '/finance/market',
    '/finance/timeline',
    '/quotation/market',
    '/market/timeline',
]

ERRORS = []
LOCK = threading.Lock()
OK = 0
FAIL = 0
TIMES = []


def fetch(url):
    global OK, FAIL
    try:
        start = time.time()
        resp = urllib.request.urlopen(url, timeout=TIMEOUT)
        elapsed = time.time() - start
        body = resp.read()
        resp.close()
        with LOCK:
            OK += 1
            TIMES.append(elapsed)
        if resp.status != 200:
            with LOCK:
                ERRORS.append(f'{url} → {resp.status}')
        return body
    except Exception as e:
        with LOCK:
            FAIL += 1
            ERRORS.append(f'{url} → {e}')
        return None


def check_chrome_pids():
    """Return number of Chrome processes."""
    try:
        count = 0
        for entry in os.listdir('/proc/'):
            if not entry.isdigit():
                continue
            try:
                with open(f'/proc/{entry}/cmdline', 'rb') as f:
                    cmd = f.read()
                if b'chrome' in cmd or b'chromium' in cmd or b'headless' in cmd:
                    count += 1
            except (IOError, OSError):
                pass
        return count
    except Exception:
        return -1


def worker(weights):
    while True:
        with LOCK:
            if not weights:
                return
            url = weights.pop(0)
        fetch(BASE + url)


def main():
    global TOTAL, CONCURRENT
    if '--total' in sys.argv:
        TOTAL = int(sys.argv[sys.argv.index('--total') + 1])
    if '--concurrent' in sys.argv:
        CONCURRENT = int(sys.argv[sys.argv.index('--concurrent') + 1])

    print(f'Stress Test: {TOTAL} requests, {CONCURRENT} concurrent')
    print(f'Target: {BASE}')
    print(f'Endpoints: {len(ENDPOINTS)}')
    print()

    # warm up
    print('Warming up (waiting for CDP pages to initialize)...')
    fetch(BASE + '/cls/telegraph')
    fetch(BASE + '/stock/data?code=sh600519')
    time.sleep(5)

    # Build weighted request list
    weights = []
    for _ in range(TOTAL):
        weights.append(ENDPOINTS[_ % len(ENDPOINTS)])

    pids_before = check_chrome_pids()
    print(f'Chrome PIDs before: {pids_before}')
    print()

    start = time.time()
    threads = []
    for _ in range(CONCURRENT):
        t = threading.Thread(target=worker, args=(weights,))
        t.daemon = True
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    pids_after = check_chrome_pids()
    total = OK + FAIL
    rate = total / elapsed if elapsed > 0 else 0

    print()
    print('=' * 50)
    print(f'  Total:      {total}')
    print(f'  OK:         {OK}')
    print(f'  Fail:       {FAIL}')
    print(f'  Elapsed:    {elapsed:.1f}s')
    print(f'  Rate:       {rate:.0f} req/s')
    print(f'  Chrome PIDs: {pids_before} → {pids_after}')
    if TIMES:
        times_sorted = sorted(TIMES)
        avg = sum(TIMES) / len(TIMES)
        p50 = times_sorted[len(times_sorted) // 2]
        p99 = times_sorted[int(len(times_sorted) * 0.99)]
        print(f'  Avg time:   {avg*1000:.0f}ms')
        print(f'  P50:        {p50*1000:.0f}ms')
        print(f'  P99:        {p99*1000:.0f}ms')
        worst = max(TIMES)
        print(f'  Worst:      {worst*1000:.0f}ms')
    print('=' * 50)

    if ERRORS:
        print(f'\nErrors ({len(ERRORS)}):')
        for err in ERRORS[:30]:
            print(f'  {err}')
        if len(ERRORS) > 30:
            print(f'  ... and {len(ERRORS) - 30} more')

    # Final sanity: check server still responds
    try:
        resp = urllib.request.urlopen(BASE + '/healthz', timeout=10)
        body = json.loads(resp.read())
        resp.close()
        print(f'\nFinal healthz: status={body.get("status")}')
    except Exception as e:
        print(f'\nFinal healthz FAILED: {e}')
        sys.exit(1)

    if FAIL > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
