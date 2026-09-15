#!/usr/bin/env python3
"""Load test for China Finance RSS Bridge.

Usage:
    python3 loadtest.py http://8.134.137.143:8053
    python3 loadtest.py http://8.134.137.143:8053 --duration 30
    python3 loadtest.py http://8.134.137.143:8053 --report report.md
"""

import sys
import json
import time
import math
import random
import urllib.request
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import stdev, mean


# ── Configuration ────────────────────────────────────────────────
DEFAULT_DURATION = 20       # seconds for sustained load test
CONCURRENT_WARMUP = 5        # concurrent requests for warmup
CONCURRENT_LOAD = 10         # concurrent requests for load test
REQUEST_TIMEOUT = 20         # per-request timeout (CDP endpoints need longer)
FETCH_TIMEOUT = 10           # timeout for non-CDP requests

# Stock codes for fund flow batch tests
STOCK_CODES = [
    'sh600519', 'sz000001', 'sz300059', 'sh600036', 'sz002415',
    'sh601318', 'sz000858', 'sh600900', 'sz002594', 'sh601012',
    'sz300750', 'sh600276', 'sz000333', 'sh601166', 'sz002304',
    'sh600887', 'sz002714', 'sh600585', 'sz000651', 'sh601398',
    'sz300015', 'sh600309', 'sz002475', 'sh601088', 'sz300124',
    'sh600690', 'sz002236', 'sh601899', 'sz000568', 'sh600438',
]

# Endpoints to test — (path, name, category)
ENDPOINTS = [
    ('/', '首页', 'basic'),
    ('/healthz', '健康检查', 'basic'),
    ('/opml.xml', 'OPML订阅列表', 'basic'),
    ('/cls/hotplate', '板块热点', 'api'),
    ('/stock/fundflow?code=sh600519', '资金流向-单只', 'api'),
    ('/stock/fundflow?code=sh600519,sz000001,sz300139', '资金流向-批量3', 'api'),
    ('/stock/fundflow?code=' + ','.join(STOCK_CODES[:10]), '资金流向-批量10', 'api'),
    ('/stock/fundflow?code=' + ','.join(STOCK_CODES), '资金流向-批量30', 'api'),
    ('/stock/timeline?code=sh600519', '分时图-单只', 'api'),
    ('/stock/timeline?code=sh600519,sz000001,sz300139', '分时图-批量3', 'api'),
    ('/stock/timeline?code=' + ','.join(STOCK_CODES[:10]), '分时图-批量10', 'api'),
    ('/stock/announcement?code=sh600519', '公告-单只', 'api'),
    ('/stock/announcement?code=sh600519,sz000001,sz300139', '公告-批量3', 'api'),
    ('/stock/announcement?code=' + ','.join(STOCK_CODES[:10]), '公告-批量10', 'api'),
    ('/finance/market', '看盘数据', 'cdp'),
    ('/finance/timeline', '看盘分时图', 'cdp'),
    ('/quotation/market', '行情数据', 'cdp'),
    ('/market/timeline', '行情分时图', 'cdp'),
    ('/stock/data?code=sh600519', '个股详情', 'cdp'),
    ('/stock/f10?code=sh600519', 'F10概要', 'cdp'),
    ('/stock/basic_info?code=sh600519', '基本信息', 'cdp'),
]

# RSS feed paths — verified against live server (remove 404s)
RSS_FEEDS = [
    '/cls/telegraph', '/cls/important', '/cls/hotspot',
    '/jin10/flash', '/jin10/news',
    '/wallstreetcn/live', '/wallstreetcn/news',
]


# ── Helpers ──────────────────────────────────────────────────────

def fmt_size(n):
    if n < 1024:
        return f'{n}B'
    return f'{n/1024:.0f}KB'


def fmt_ms(sec):
    return f'{sec*1000:.0f}ms'


def fmt_pct(n, total):
    return f'{n}/{total}'


def endpoint_url(base, path):
    if path.startswith('http'):
        return path
    return base.rstrip('/') + path


def fetch(url, timeout=REQUEST_TIMEOUT):
    """Single HTTP GET request, returns (status, data, elapsed)."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = resp.read()
        elapsed = time.time() - t0
        return (resp.status, data, elapsed)
    except urllib.error.HTTPError as e:
        data = e.read()
        elapsed = time.time() - t0
        return (e.code, data, elapsed)
    except Exception as e:
        elapsed = time.time() - t0
        return (0, str(e).encode(), elapsed)


def fetch_with_timeout(path, base, timeout):
    """Wrapper for fetch with path resolution."""
    url = endpoint_url(base, path)
    return fetch(url, timeout=timeout)


def fetch_with_warmup(base, path, warmup=CONCURRENT_WARMUP):
    """Warm up cache, then return a single clean measurement."""
    url = endpoint_url(base, path)
    # Warmup requests
    with ThreadPoolExecutor(max_workers=warmup) as ex:
        list(ex.map(lambda _: fetch(url), range(warmup)))
    # Clean measurement
    return fetch(url)


def batch_fetch(base, paths, max_workers=CONCURRENT_LOAD, count=1):
    """Fetch a list of paths concurrently, returns list of results."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for _ in range(count):
            urls = [endpoint_url(base, p) for p in paths]
            futures = {ex.submit(fetch, u): u for u in urls}
            for f in as_completed(futures):
                results.append(f.result())
    return results


# ── Report ───────────────────────────────────────────────────────

class Report:
    def __init__(self, base_url):
        self.base_url = base_url
        self.sections = []

    def add(self, title, lines=None):
        self.sections.append((title, lines or []))

    def append(self, lines):
        if self.sections:
            self.sections[-1][1].extend(lines)

    def print(self):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print('=' * 70)
        print('  压测报告 - China Finance RSS Bridge')
        print(f'  目标: {self.base_url}')
        print(f'  时间: {timestamp}')
        print('=' * 70)
        print()

        for title, lines in self.sections:
            print(f'【{title}】')
            if lines:
                for line in lines:
                    print(f'  {line}')
            print()

    def markdown(self):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        md = []
        md.append('# 压测报告 - China Finance RSS Bridge')
        md.append(f'- **目标**: {self.base_url}')
        md.append(f'- **时间**: {timestamp}')
        md.append('')

        for title, lines in self.sections:
            md.append(f'## {title}')
            if lines:
                for line in lines:
                    md.append(line)
            md.append('')

        return '\n'.join(md)


# ── Test Scenarios ──────────────────────────────────────────────

def test_basic_endpoints(base, report):
    """Test all endpoints sequentially with warmup."""
    results = []
    for path, name, cat in ENDPOINTS:
        url = endpoint_url(base, path)
        status, data, elapsed = fetch_with_warmup(base, path)
        line = (cat, name, status, len(data), elapsed)
        results.append(line)
        mark = '✅' if status == 200 else '❌'
        cdp_tag = ' [CDP]' if cat == 'cdp' else ''
        report.append(f'  {mark} {name:12s} {status:3d} {fmt_size(len(data)):>6s} {fmt_ms(elapsed):>8s}{cdp_tag}')

    # Summary
    ok = sum(1 for r in results if r[2] == 200)
    cdp_ok = sum(1 for r in results if r[2] == 200 and r[0] == 'cdp')
    cdp_total = sum(1 for r in results if r[0] == 'cdp')
    basic_ok = sum(1 for r in results if r[2] == 200 and r[0] != 'cdp')
    basic_total = sum(1 for r in results if r[0] != 'cdp')
    report.append(f'  ──')
    report.append(f'  非CDP端点: {basic_ok}/{basic_total} ✅  CDP端点: {cdp_ok}/{cdp_total}  (需Chrome)')


def test_rss_feeds(base, report):
    """Test all RSS feed endpoints."""
    results = []
    for path in RSS_FEEDS:
        url = endpoint_url(base, path)
        status, data, elapsed = fetch_with_warmup(base, path)
        results.append((path, status, len(data), elapsed))
        mark = '✅' if status == 200 else '❌'
        report.append(f'  {mark} {path:25s} {status:3d} {fmt_size(len(data)):>6s} {fmt_ms(elapsed):>8s}')

    ok = sum(1 for r in results if r[1] == 200)
    report.append(f'  ──')
    report.append(f'  RSS端点: {ok}/{len(results)}')


def _batch_test(base, report, endpoint, label, sizes):
    """Generic batch scalability test for any stock batch endpoint."""
    report.append(f'  [{label}]')
    report.append(f'  {"批量":>6s}  {"状态":>4s} {"大小":>8s} {"延迟":>8s} {"数据":>6s}')
    report.append(f'  {"─"*40}')
    for n in sizes:
        codes = ','.join(STOCK_CODES[:n])
        path = f'{endpoint}?code={codes}'
        status, data, elapsed = fetch_with_warmup(base, path)
        try:
            body = json.loads(data)
            count = len(body) if isinstance(body, dict) else 0
            nulls = sum(1 for v in body.values() if v is None) if isinstance(body, dict) else 0
            detail = f'{count}只'
            if nulls:
                detail += f' ({nulls}null)'
        except:
            detail = 'parse err'
        mark = '✅' if status == 200 else '❌'
        report.append(f'  {mark} {n:>3d}只  {status:3d} {fmt_size(len(data)):>8s} {fmt_ms(elapsed):>8s} {detail}')
    report.append('')


def test_fundflow_batch(base, report):
    """Test fund flow batch endpoint with increasing batch sizes."""
    _batch_test(base, report, '/stock/fundflow', '资金流向', [1, 3, 5, 10, 20, 30])


def test_timeline_batch(base, report):
    """Test timeline batch endpoint with increasing batch sizes."""
    _batch_test(base, report, '/stock/timeline', '分时图', [1, 3, 5, 10])


def test_announcement_batch(base, report):
    """Test announcement batch endpoint with increasing batch sizes."""
    _batch_test(base, report, '/stock/announcement', '公告', [1, 3, 5, 10])


def test_concurrent_blast(base, report):
    """Concurrent load test against key endpoints with sustained pressure."""
    targets = [
        ('/cls/hotplate', '板块热点', 15, 5),
        ('/stock/fundflow?code=' + ','.join(STOCK_CODES[:10]), '资金流向-批量10', 20, 5),
        ('/stock/timeline?code=' + ','.join(STOCK_CODES[:10]), '分时图-批量10', 20, 5),
        ('/stock/announcement?code=' + ','.join(STOCK_CODES[:10]), '公告-批量10', 20, 5),
    ]

    for path, name, req_count, concurrency in targets:
        url = endpoint_url(base, path)

        # Warmup
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            list(ex.map(lambda _: fetch(url), range(concurrency * 2)))

        # Sustained blast
        report.append(f'  [{name}] {req_count}次请求 × {concurrency}并发')
        results = []
        t_start = time.time()
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(fetch, url) for _ in range(req_count)]
            for f in as_completed(futures):
                results.append(f.result())
        wall_time = time.time() - t_start

        # Statistics
        success = [r for r in results if r[0] == 200]
        failed = [r for r in results if r[0] != 200]
        times = sorted([r[2] for r in success])
        if times:
            avg = mean(times)
            p50 = times[len(times) // 2]
            p95 = times[int(len(times) * 0.95)]
            p99 = times[int(len(times) * 0.99)]
            mx = max(times)
            std = stdev(times) if len(times) > 1 else 0
            rps = len(success) / wall_time if wall_time > 0 else 0
            report.append(f'    成功率: {len(success)}/{len(results)}')
            report.append(f'    延迟:   avg={fmt_ms(avg)}  p50={fmt_ms(p50)}  p95={fmt_ms(p95)}  p99={fmt_ms(p99)}  max={fmt_ms(mx)}')
            report.append(f'    吞吐:   {rps:.0f} req/s  (耗时 {wall_time:.1f}s)')
            report.append(f'    抖动:   σ={fmt_ms(std)}')
        if failed:
            report.append(f'    ❌ 失败: {len(failed)}/{len(results)}')


def test_sustained_load(base, report, duration=DEFAULT_DURATION):
    """Sustained mixed load — fixed rate, no backlog."""
    report.append(f'  持续 {duration}s 混合压力（非CDP端点）')
    report.append(f'  端点池: 板块热点 + 首页 + 健康检查 + OPML + 资金流向(随机)')

    # Build endpoint pool
    pool = [
        '/',
        '/healthz',
        '/opml.xml',
        '/cls/hotplate',
    ]
    for _ in range(4):
        k = random.randint(1, 10)
        codes = ','.join(random.sample(STOCK_CODES, k))
        pool.append(f'/stock/fundflow?code={codes}')
        pool.append(f'/stock/timeline?code={codes}')
    for _ in range(4):
        k = random.randint(1, 5)
        codes = ','.join(random.sample(STOCK_CODES, k))
        pool.append(f'/stock/announcement?code={codes}')

    # Warmup
    with ThreadPoolExecutor(max_workers=CONCURRENT_LOAD) as ex:
        list(ex.map(lambda p: fetch(endpoint_url(base, p), 10), pool[:6]))

    # Sequential mixed load: fire one batch, wait, fire next, wait
    results = []
    t_end = time.time() + duration
    batch_size = CONCURRENT_LOAD
    interval = 1.0  # one batch per second
    next_tick = time.time()
    total_planned = 0

    with ThreadPoolExecutor(max_workers=CONCURRENT_LOAD) as ex:
        while time.time() < t_end:
            paths = [random.choice(pool) for _ in range(batch_size)]
            total_planned += len(paths)
            batch_results = list(ex.map(lambda p: fetch(endpoint_url(base, p), 10), paths))
            results.extend(batch_results)
            # Progress tick
            now = time.time()
            if now > next_tick:
                ok = sum(1 for r in batch_results if r[0] == 200)
                print(f'    batch: {len(batch_results)} req, {ok} ok, {now-t_end+duration:.0f}s remaining')
                next_tick = now + 5
            # Rate limit: sleep if ahead of schedule
            elapsed = time.time() - (t_end - duration)
            expected_batches = elapsed / interval
            actual_batches = total_planned / batch_size
            if actual_batches > expected_batches + 0.5:
                time.sleep(0.2)

    success = [r for r in results if r[0] == 200]
    failed = [r for r in results if r[0] != 200]
    times = sorted([r[2] for r in success])
    if times:
        avg = mean(times)
        mx = max(times)
        rps = len(success) / duration if duration > 0 else 0
        report.append(f'  总请求: {len(results)} 成功: {len(success)} 失败: {len(failed)}')
        report.append(f'  吞吐:   {rps:.1f} req/s  avg={fmt_ms(avg)}  max={fmt_ms(mx)}')
    print(f'    持续压力完成: {len(results)} req, OK={len(success)}')


# ── Main ─────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        sys.exit(1)

    base_url = args[0]
    duration = DEFAULT_DURATION

    # Parse optional args
    report_path = None
    for i, a in enumerate(args[1:]):
        if a == '--duration' and i + 2 < len(args):
            duration = int(args[i + 2])
        elif a == '--report' and i + 2 < len(args):
            report_path = args[i + 2]

    report = Report(base_url)

    # ── Phase 1: Basic endpoints ──
    print('[1/6] 基础端点测试...')
    report.add('一、基础端点测试')
    test_basic_endpoints(base_url, report)

    # ── Phase 2: Fund flow batch scalability ──
    print('[2/6] 资金流向批量伸缩测试...')
    report.add('二、资金流向批量伸缩测试')
    test_fundflow_batch(base_url, report)

    # ── Phase 3: Timeline batch scalability ──
    print('[3/6] 分时图批量伸缩测试...')
    report.add('三、分时图批量伸缩测试')
    test_timeline_batch(base_url, report)

    # ── Phase 4: Announcement batch scalability ──
    print('[4/6] 公告批量伸缩测试...')
    report.add('四、公告批量伸缩测试')
    test_announcement_batch(base_url, report)

    # ── Phase 5: Concurrent blast ──
    print('[5/6] 并发压力测试...')
    report.add('五、并发压力测试')
    test_concurrent_blast(base_url, report)

    # ── Phase 6: Sustained load ──
    print(f'[6/6] 持续混合压力测试 ({duration}s)...')
    report.add('六、持续混合压力测试')
    test_sustained_load(base_url, report, duration=duration)

    # ── Output ──
    print()
    report.print()

    if report_path:
        with open(report_path, 'w') as f:
            f.write(report.markdown())
        print(f'报告已保存: {report_path}')

    # Return exit code
    all_results = []
    for _, lines in report.sections:
        for line in lines:
            if '❌' in line and 'CDP' not in line:
                print(f'WARN: Non-CDP endpoint failed: {line}')
                return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
