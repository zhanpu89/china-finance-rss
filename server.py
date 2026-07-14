#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""China Finance RSS Bridge

Lightweight RSS bridge server that converts Chinese financial news sources
into standard RSS 2.0 feeds.

Sources: CLS (财联社), Eastmoney (东方财富), THS (同花顺)

Usage:
    python server.py
    PORT=9000 python server.py

Dependencies:
    - websocket-client (optional, for CDP mode)
"""

import atexit
import json
import os
import random
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlencode

from cdp_engine import ensure_chrome, CDPEngine
from config import (
    PORT, CACHE_TTL, REQUEST_TIMEOUT, PUBLIC_BASE_URL, MAX_WORKERS,
    _MAX_BATCH_SIZE,
    _FINANCE_EXPECTED_KEYS, _QUOTATION_EXPECTED_KEYS,
    _HOTPLATE_BASE_URL, _HOTPLATE_HEADERS,
    cdp_engine, _china_trading_ttl,
)
from cache import fetch_json, feed_cache, _feed_cache_lock, _feed_fetch_locks, \
    _feed_fetch_locks_lock, MAX_FEED_CACHE_SIZE, CACHE_JITTER, _fill_missing
from utils import (
    generate_rss, generate_error_rss, generate_opml, count_rss_items,
    parse_cls_items, parse_jin10_items, parse_wallstreetcn_items,
    cls_sign_params, get_jin10_public_headers,
    strip_html, timestamp_to_rfc822, parse_china_datetime_to_rfc822, escape_xml,
)
from stock_api import (
    handle_cls_stock, handle_cls_stock_batch, handle_cls_fundflow,
    handle_cls_timeline, handle_cls_f10, handle_cls_basic_infos,
    handle_cls_announcement,
    fetch_cls_fundflow, fetch_cls_timeline,
    _fundflow_prefetch_loop, _timeline_prefetch_loop,
    _f10_prefetch_loop,
    _announcement_prefetch_loop,
)
from market_api import (
    handle_margin, handle_northbound, handle_northbound_history,
)


# ── Source handlers ────────────────────────────────────────────────────────

def handle_cls_telegraph(feed_url=None):
    """CLS Telegraph (财联社电报) - Real-time financial news flashes."""
    url = 'https://www.cls.cn/v1/roll/get_roll_list'
    params = {
        'refresh_type': 1, 'rn': 50, 'last_time': 0,
        'os': 'web', 'sv': '8.7.9', 'app': 'CailianpressWeb',
    }
    params['sign'] = cls_sign_params(params)
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/telegraph'}
    data = json.loads(fetch_json(f'{url}?{urlencode(params)}', headers))
    return generate_rss('财联社电报', 'https://www.cls.cn/telegraph',
                        '财联社实时快讯', parse_cls_items(data), feed_url=feed_url)


def handle_eastmoney_kuaixun(feed_url=None):
    """Eastmoney 7x24 News (东方财富快讯)."""
    url = 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kuaixun.eastmoney.com/'}
    data = fetch_json(url, headers)
    match = re.search(r'var ajaxResult=(\{.*\})', data, re.DOTALL)
    if not match:
        return generate_rss('东方财富快讯', 'https://kuaixun.eastmoney.com/',
                            '东方财富7x24快讯', [], feed_url=feed_url)
    result = json.loads(match.group(1))
    items = []
    for item in result.get('LivesList', []):
        showtime = item.get('showtime', '')
        try:
            pubdate = parse_china_datetime_to_rfc822(showtime)
        except Exception:
            pubdate = formatdate(timeval=None, localtime=False, usegmt=True)
        digest = item.get('digest', '')
        items.append({
            'title': item.get('title', ''),
            'link': item.get('url_w', '') or f"https://kuaixun.eastmoney.com/a/{item.get('newsid', '')}",
            'description': digest or item.get('title', ''),
            'pubDate': pubdate,
            'guid': f"eastmoney_{item.get('newsid', '')}"
        })
    return generate_rss('东方财富快讯', 'https://kuaixun.eastmoney.com/',
                        '东方财富7x24快讯', items, feed_url=feed_url)


def handle_ths_kuaixun(feed_url=None):
    """THS 7x24 News (同花顺快讯)."""
    url = 'https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=50'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://news.10jqka.com.cn/'
    }
    data = json.loads(fetch_json(url, headers))
    items = []
    for item in data.get('data', {}).get('list', []):
        digest = item.get('digest') or item.get('remark', '')
        items.append({
            'title': item.get('title', ''),
            'link': item.get('url', '') or f"https://news.10jqka.com.cn/{item.get('seq', '')}",
            'description': digest or item.get('title', ''),
            'pubDate': timestamp_to_rfc822(int(item.get('ctime', 0))),
            'guid': f"ths_{item.get('seq', '')}"
        })
    return generate_rss('同花顺快讯', 'https://news.10jqka.com.cn/',
                        '同花顺7x24快讯', items, feed_url=feed_url)


def handle_ths_longhu():
    """THS Longhu (同花顺龙虎榜) — full table with top5 buy/sell brokerages."""
    req = Request(
        'https://data.10jqka.com.cn/ifmarket/lhbtable',
        headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://data.10jqka.com.cn/market/longhu/',
            'X-Requested-With': 'XMLHttpRequest',
        })
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        stock_html = resp.read().decode('gbk', errors='replace')

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', stock_html, re.DOTALL)
    stocks = []
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 7:
            continue
        code = re.sub(r'<[^>]+>', '', cells[1]).strip()
        if not code.isdigit():
            continue
        stocks.append({
            'code': code,
            'name': re.sub(r'<[^>]+>', '', cells[2]).strip(),
            'price': re.sub(r'<[^>]+>', '', cells[3]).strip(),
            'change_pct': re.sub(r'<[^>]+>', '', cells[4]).strip(),
            'turnover': re.sub(r'<[^>]+>', '', cells[5]).strip(),
            'net_buy': re.sub(r'<[^>]+>', '', cells[6]).strip(),
        })

    page_req = Request(
        'https://data.10jqka.com.cn/market/longhu/',
        headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
    with urlopen(page_req, timeout=REQUEST_TIMEOUT) as resp:
        page_html = resp.read().decode('gbk', errors='replace')

    all_tables = re.findall(r'<table[^>]*>(.*?)</table>', page_html, re.DOTALL)
    broker_idx = 0
    for tbl in all_tables:
        ths = re.findall(r'<th[^>]*>(.*?)</th>', tbl, re.DOTALL)
        if not ths:
            continue
        label = re.sub(r'<[^>]+>', '', ths[0]).strip()
        if '买入金额最大的前5名营业部' not in label and '卖出金额最大的前5名营业部' not in label:
            continue
        entries = []
        for bro_row in re.findall(r'<tr[^>]*>(.*?)</tr>', tbl, re.DOTALL):
            bro_cells = re.findall(r'<td[^>]*>(.*?)</td>', bro_row, re.DOTALL)
            if len(bro_cells) < 4:
                continue
            name = re.sub(r'<[^>]+>', '', bro_cells[0])
            name = next((p for p in name.split('\n') if p.strip()), '').strip()
            if not name or name == '营业部名称':
                continue
            entries.append({
                'name': name,
                'buy': re.sub(r'<[^>]+>', '', bro_cells[1]).strip() + '万',
                'sell': re.sub(r'<[^>]+>', '', bro_cells[2]).strip() + '万',
                'net': re.sub(r'<[^>]+>', '', bro_cells[3]).strip() + '万',
            })
        if not entries:
            continue
        kind = 'buy_top5' if '买入' in label else 'sell_top5'
        stock_idx = broker_idx // 2
        if stock_idx < len(stocks):
            stocks[stock_idx][kind] = entries
        broker_idx += 1
    return {'data': stocks, 'total': len(stocks)}


def handle_jin10_flash(feed_url=None):
    """Jin10 7x24 flash news (金十快讯)."""
    url = 'https://flash-api.jin10.com/get_flash_list?channel=-8200&limit=50'
    data = json.loads(fetch_json(url, get_jin10_public_headers()))
    return generate_rss('金十快讯', 'https://www.jin10.com/',
                        '金十数据7x24快讯', parse_jin10_items(data), feed_url=feed_url)


def handle_wallstreetcn_live(feed_url=None):
    """Wallstreetcn 7x24 live news (华尔街见闻快讯)."""
    url = 'https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&client=pc&limit=50'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json,text/plain,*/*',
        'Referer': 'https://wallstreetcn.com/live',
    }
    data = json.loads(fetch_json(url, headers))
    return generate_rss('华尔街见闻快讯', 'https://wallstreetcn.com/live',
                        '华尔街见闻7x24快讯', parse_wallstreetcn_items(data), feed_url=feed_url)


# ── CDP-based JSON handlers ────────────────────────────────────────────────

def handle_finance_market(feed_url=None):
    """CLS Finance Market Data (财联社看盘) via Chrome CDP."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')
    if not page:
        return {'error': 'Finance page not initialized.'}
    data = page.get_data()
    ws_raw = data.pop('__ws__', None)
    data.pop('timeline', None)
    result = {}
    _fill_missing(result, data, _FINANCE_EXPECTED_KEYS)
    if ws_raw:
        result['ws_count'] = len(ws_raw)
        result['ws_latest'] = ws_raw[-5:] if ws_raw else []
    return result


def handle_cls_quotation(feed_url=None):
    """CLS Quotation Market Data (财联社行情) via Chrome CDP."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_quotation')
    if not page:
        return {'error': 'Quotation page not initialized.'}
    data = page.get_data()
    data.pop('timeline', None)
    result = {}
    _fill_missing(result, data, _QUOTATION_EXPECTED_KEYS)
    return result


def handle_market_timeline():
    """CLS Market Index Timeline (指数分时图) — from quotation CDP page."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_quotation')
    if not page:
        return {'error': 'Quotation page not initialized.'}
    return page.get_data().get('timeline')


def handle_finance_timeline():
    """CLS Finance Market Timeline — from finance CDP page."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')
    if not page:
        return {'error': 'Finance page not initialized.'}
    return page.get_data().get('timeline')


# ── Hotplate ───────────────────────────────────────────────────────────────

def handle_cls_hotplate(feed_url=None):
    """CLS Hotplate Data (财联社板块) — uses same sign mechanism as telegraph."""
    result = {}
    hot_plates = None
    _BASE_TTL, _STAGGER = _china_trading_ttl()
    _TTL_OFFSETS = {'industry': 0, 'concept': _STAGGER, 'area': _STAGGER * 2}
    for ptype in ('industry', 'concept', 'area'):
        params = {
            'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
            'type': ptype, 'way': 'change', 'page': 1, 'rever': 1,
        }
        params['sign'] = cls_sign_params(params)
        url = f'{_HOTPLATE_BASE_URL}?{urlencode(params)}'
        try:
            raw = json.loads(fetch_json(url, _HOTPLATE_HEADERS,
                                        ttl=_BASE_TTL + _TTL_OFFSETS[ptype]))
            data = raw.get('data') or raw
            result[f'plate_{ptype}'] = data
            if hot_plates is None:
                mfd = data.get('main_fund_diff') or {}
                top = mfd.get('top_main_fund_diff') or []
                last = mfd.get('last_main_fund_diff') or []
                if top or last:
                    hot_plates = top + last
        except Exception as e:
            result[f'plate_{ptype}'] = {'error': str(e)}
    if hot_plates:
        result['hot_plates'] = hot_plates
    return result


# ── Route table ─────────────────────────────────────────────────────────────

ROUTES = {
    '/cls/telegraph': {
        'handler': handle_cls_telegraph,
        'name': 'CLS Telegraph (财联社电报)',
        'title': '财联社电报',
        'link': 'https://www.cls.cn/telegraph',
        'description': '财联社实时快讯',
    },
    '/eastmoney/kuaixun': {
        'handler': handle_eastmoney_kuaixun,
        'name': 'Eastmoney News (东方财富快讯)',
        'title': '东方财富快讯',
        'link': 'https://kuaixun.eastmoney.com/',
        'description': '东方财富7x24快讯',
    },
    '/ths/kuaixun': {
        'handler': handle_ths_kuaixun,
        'name': 'THS News (同花顺快讯)',
        'title': '同花顺快讯',
        'link': 'https://news.10jqka.com.cn/',
        'description': '同花顺7x24快讯',
    },
    '/jin10/flash': {
        'handler': handle_jin10_flash,
        'name': 'Jin10 Flash (金十快讯)',
        'title': '金十快讯',
        'link': 'https://www.jin10.com/',
        'description': '金十数据7x24快讯',
    },
    '/wallstreetcn/live': {
        'handler': handle_wallstreetcn_live,
        'name': 'Wallstreetcn Live (华尔街见闻快讯)',
        'title': '华尔街见闻快讯',
        'link': 'https://wallstreetcn.com/live',
        'description': '华尔街见闻7x24快讯',
    },
}


# ── Health payload ──────────────────────────────────────────────────────────

def build_health_payload(base_url, check_sources=False):
    """Build a JSON-serializable health payload."""
    feeds = []
    status = 'ok'

    for path, info in ROUTES.items():
        entry = {
            'name': info['name'],
            'path': path,
            'url': base_url + path,
            'status': 'configured',
        }
        if check_sources:
            try:
                xml = info['handler'](feed_url=base_url + path)
                entry['status'] = 'ok'
                entry['items'] = count_rss_items(xml)
            except Exception as exc:
                entry['status'] = 'error'
                entry['error'] = str(exc)
                status = 'degraded'
        feeds.append(entry)

    feeds.append({'name': 'CLS Finance Market (财联社看盘)',
                  'path': '/finance/market',
                  'url': base_url + '/finance/market',
                  'status': 'requires_chrome_cdp'})
    feeds.append({'name': 'CLS Quotation Market (财联社行情)',
                  'path': '/quotation/market',
                  'url': base_url + '/quotation/market',
                  'status': 'requires_chrome_cdp'})
    feeds.append({'name': 'CLS Stock Detail (财联社个股详情)',
                  'path': '/stock/data',
                  'url': base_url + '/stock/data',
                  'status': 'requires_chrome_cdp'})
    feeds.append({'name': 'CLS Stock Fund Flow (财联社个股资金流向)',
                  'path': '/stock/fundflow',
                  'url': base_url + '/stock/fundflow',
                  'status': 'configured'})
    feeds.append({'name': 'CLS Hotplate (财联社板块)',
                  'path': '/cls/hotplate',
                  'url': base_url + '/cls/hotplate',
                  'status': 'configured'})
    feeds.append({'name': 'CLS Stock Timeline (个股分时图)',
                  'path': '/stock/timeline',
                  'url': base_url + '/stock/timeline',
                  'status': 'configured'})
    feeds.append({'name': 'CLS Stock F10 (个股F10财务概要)',
                  'path': '/stock/f10',
                  'url': base_url + '/stock/f10',
                  'status': 'configured'})
    feeds.append({'name': 'CLS Stock Basic Info (个股基本信息)',
                  'path': '/stock/basic_info',
                  'url': base_url + '/stock/basic_info',
                  'status': 'requires_chrome_cdp'})
    feeds.append({'name': 'Market Margin (融资融券)',
                  'path': '/market/margin',
                  'url': base_url + '/market/margin',
                  'status': 'configured'})
    feeds.append({'name': 'Market Northbound (北向资金)',
                  'path': '/market/northbound',
                  'url': base_url + '/market/northbound',
                  'status': 'configured'})
    feeds.append({'name': 'Market Northbound History (北向资金历史)',
                  'path': '/market/northbound/history',
                  'url': base_url + '/market/northbound/history',
                  'status': 'configured'})

    return {'status': status, 'cache_ttl': CACHE_TTL,
            'request_timeout': REQUEST_TIMEOUT, 'feeds': feeds}


# ── HTTP Server ─────────────────────────────────────────────────────────────

class RSSHandler(BaseHTTPRequestHandler):
    """HTTP request handler for RSS feeds."""

    timeout = 30

    def log_error(self, format, *args):
        if format == 'Request timed out: %r':
            return
        self.log_message(format, *args)

    def log_date_time_string(self):
        from time import strftime, gmtime
        return strftime('%d/%b/%Y %H:%M:%S', gmtime(time.time() + 28800))

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def do_HEAD(self):
        try:
            self._handle_request(write_body=False)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        try:
            self._handle_request(write_body=True)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_request(self, write_body=True):
        parsed = urlparse(self.path)
        path = parsed.path
        base_url = self._base_url()

        if path == '/':
            self._serve_index(write_body=write_body)
            return
        if path == '/opml.xml':
            self._send_text(200, 'text/x-opml; charset=utf-8',
                            generate_opml(base_url, ROUTES), write_body=write_body)
            return
        if path == '/healthz':
            query = parse_qs(parsed.query)
            check_sources = query.get('check', ['0'])[0] in ('1', 'true', 'yes')
            payload = build_health_payload(base_url, check_sources=check_sources)
            status_code = 503 if payload['status'] == 'degraded' else 200
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            self._send_text(status_code, 'application/json; charset=utf-8',
                            body, cache=False, write_body=write_body)
            return
        if path == '/finance/market':
            self._send_json(handle_finance_market(), write_body=write_body)
            return
        if path == '/finance/timeline':
            self._send_json(handle_finance_timeline(), write_body=write_body)
            return
        if path == '/quotation/market':
            self._send_json(handle_cls_quotation(), write_body=write_body)
            return
        if path == '/market/timeline':
            self._send_json(handle_market_timeline(), write_body=write_body)
            return
        if path == '/stock/data':
            self._handle_stock_batch(parsed, handle_cls_stock_batch, write_body=write_body)
            return
        if path == '/stock/fundflow':
            self._handle_stock_batch(parsed, handle_cls_fundflow, write_body=write_body)
            return
        if path == '/stock/timeline':
            self._handle_stock_batch(parsed, handle_cls_timeline, write_body=write_body)
            return
        if path == '/stock/f10':
            self._handle_stock_batch(parsed, handle_cls_f10, write_body=write_body)
            return
        if path == '/stock/basic_info':
            self._handle_stock_batch(parsed, handle_cls_basic_infos, write_body=write_body)
            return
        if path == '/stock/announcement':
            self._handle_stock_batch(parsed, handle_cls_announcement, write_body=write_body)
            return
        if path == '/cls/hotplate':
            self._send_json(handle_cls_hotplate(), write_body=write_body)
            return
        if path == '/ths/longhu':
            body = json.dumps(handle_ths_longhu(), ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=False, write_body=write_body)
            return
        if path == '/market/margin':
            params = parse_qs(parsed.query)
            market = params.get('market', ['99'])[0]
            self._send_json(handle_margin(market), write_body=write_body)
            return
        if path == '/market/northbound':
            self._send_json(handle_northbound(), write_body=write_body)
            return
        if path == '/market/northbound/history':
            params = parse_qs(parsed.query)
            period = params.get('period', ['day'])[0]
            self._send_json(handle_northbound_history(period), write_body=write_body)
            return
        if path in ROUTES:
            self._serve_feed(path, base_url, write_body=write_body)
            return

        self.send_error(404, 'Not Found. Visit / for available feeds.')

    def _handle_stock_batch(self, parsed, handler, write_body=True):
        params = parse_qs(parsed.query)
        if 'code' not in params:
            self._send_error('Missing ?code= parameter. Usage: /stock/...?code=sh600519 or ...?code=sh600519,sz000001')
            return
        codes_str = params['code'][0]
        stock_codes = [c.strip() for c in codes_str.split(',') if c.strip()]
        if not stock_codes:
            self._send_error('No valid stock codes provided.')
            return
        if len(stock_codes) > _MAX_BATCH_SIZE:
            stock_codes = stock_codes[:_MAX_BATCH_SIZE]
        data = handler(stock_codes)
        if len(stock_codes) == 1:
            body = json.dumps({stock_codes[0]: data.get(stock_codes[0])},
                              ensure_ascii=False, indent=2)
        else:
            body = json.dumps(data, ensure_ascii=False, indent=2)
        self._send_text(200, 'application/json; charset=utf-8',
                        body, cache=True, write_body=write_body)

    def _send_error(self, msg):
        body = json.dumps({'error': msg}, ensure_ascii=False, indent=2)
        self._send_text(400, 'application/json; charset=utf-8',
                        body, cache=False, write_body=True)

    def _send_json(self, data, write_body=True):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self._send_text(200, 'application/json; charset=utf-8',
                        body, cache=True, write_body=write_body)

    def _get_or_fetch_feed(self, path, fetch_func):
        """Thread-safe feed cache with stampede protection and LRU eviction."""
        now = time.time()
        with _feed_cache_lock:
            cached = feed_cache.get(path)
            if cached and now < cached['expires_at']:
                return cached['xml']

        with _feed_fetch_locks_lock:
            if path not in _feed_fetch_locks:
                _feed_fetch_locks[path] = threading.Lock()
            lock = _feed_fetch_locks[path]

        with lock:
            with _feed_cache_lock:
                cached = feed_cache.get(path)
                if cached and time.time() < cached['expires_at']:
                    return cached['xml']
            try:
                xml = fetch_func()
            except Exception:
                _feed_fetch_locks.pop(path, None)
                raise
            with _feed_cache_lock:
                if len(feed_cache) >= MAX_FEED_CACHE_SIZE:
                    oldest = min(feed_cache, key=lambda k: feed_cache[k]['time'])
                    del feed_cache[oldest]
                    _feed_fetch_locks.pop(oldest, None)
                feed_cache[path] = {
                    'xml': xml, 'time': time.time(),
                    'expires_at': time.time() + CACHE_TTL * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))
                }
        return xml

    def _serve_feed(self, path, base_url, write_body=True):
        handler = ROUTES[path]['handler']
        feed_url = base_url + path
        try:
            xml = self._get_or_fetch_feed(path, lambda: handler(feed_url=feed_url))
        except Exception as exc:
            info = ROUTES[path]
            xml = generate_error_rss(info['title'], info['link'],
                                     info['description'], exc, feed_url=feed_url)
        self._send_text(200, 'application/rss+xml; charset=utf-8',
                        xml, write_body=write_body)

    def _base_url(self):
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL
        proto = self.headers.get('X-Forwarded-Proto', 'http').split(',')[0].strip()
        host = self.headers.get('X-Forwarded-Host') or self.headers.get('Host')
        return f'{proto}://{host or f"localhost:{PORT}"}'.rstrip('/')

    def _send_text(self, status_code, content_type, body, cache=True, write_body=True):
        body_bytes = body.encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body_bytes)))
        if cache:
            self.send_header('Cache-Control', f'public, max-age={CACHE_TTL}')
        self.end_headers()
        if write_body:
            self.wfile.write(body_bytes)

    def _serve_index(self, write_body=True):
        """Serve a simple index page listing available feeds in a table."""
        lines = ['<html><head><title>China Finance RSS Bridge</title>',
                 '<style>',
                 'body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:960px;margin:2em auto;padding:0 1em;background:#fafafa;color:#333}',
                 'h1{color:#111}',
                 'table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1);border-radius:6px;overflow:hidden}',
                 'th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #eee}',
                 'th{background:#f0f4f8;font-weight:600;white-space:nowrap}',
                 'tr:hover{background:#f5f8ff}',
                 'a{color:#2563eb;text-decoration:none}',
                 'a:hover{text-decoration:underline}',
                 '.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;font-weight:500}',
                 '.tag-rss{background:#dcfce7;color:#166534}',
                 '.tag-json{background:#dbeafe;color:#1e40af}',
                 '.tag-cdp{background:#fef3c7;color:#92400e}',
                 '.tag-none{background:#f3f4f6;color:#6b7280}',
                 '.section{margin:1.5em 0 .5em;font-size:1.1em;font-weight:600;color:#444}',
                 '</style></head>',
                 '<body><h1>🇨🇳 China Finance RSS Bridge</h1>',
                 '<table>',
                 '<tr><th>Name</th><th>Endpoint</th><th>Example</th><th>Type</th><th>CDP</th></tr>']
        # RSS feed routes
        for path, info in ROUTES.items():
            lines.append(
                f'<tr><td>{info["name"]}</td>'
                f'<td><a href="{path}">{path}</a></td>'
                f'<td>–</td>'
                f'<td><span class="tag tag-rss">RSS</span></td>'
                f'<td><span class="tag tag-none">–</span></td></tr>')
        # JSON API endpoints
        json_apis = [
            ('/finance/market', 'Finance Market Data (财联社看盘)', '/finance/market', True),
            ('/finance/timeline', 'Finance Timeline (分时图)', '/finance/timeline', True),
            ('/quotation/market', 'Quotation Market Data (行情)', '/quotation/market', True),
            ('/market/timeline', 'Market Index Timeline (指数分时图)', '/market/timeline', True),
            ('/cls/hotplate', 'Hotplate (板块)', '/cls/hotplate', False),
            ('/ths/longhu', 'THS Longhu (龙虎榜)', '/ths/longhu', False),
            ('/stock/data', 'Stock Detail (个股详情)', '/stock/data?code=sz300139', True),
            ('/stock/fundflow', 'Stock Fund Flow (资金流向)', '/stock/fundflow?code=sh600519', False),
            ('/stock/timeline', 'Stock Timeline (个股分时图)', '/stock/timeline?code=sh600519', False),
            ('/stock/f10', 'Stock F10 (个股财务概要)', '/stock/f10?code=sh600519', False),
            ('/stock/basic_info', 'Stock Basic Info (个股基本信息)', '/stock/basic_info?code=sh600519', True),
            ('/stock/announcement', 'Stock Announcement (个股公告)', '/stock/announcement?code=sh600519', False),
            ('/market/margin', 'Market Margin (融资融券)', '/market/margin?market=99', False),
            ('/market/northbound', 'Market Northbound (北向资金)', '/market/northbound', False),
            ('/market/northbound/history', 'Market Northbound History (北向资金历史)',
             '/market/northbound/history?period=day', False),
        ]
        for path, name, example, needs_cdp in json_apis:
            cdp_tag = '<span class="tag tag-cdp">CDP</span>' if needs_cdp else '<span class="tag tag-none">–</span>'
            lines.append(
                f'<tr><td>{name}</td>'
                f'<td><a href="{path}">{path}</a></td>'
                f'<td><a href="{example}">Try</a></td>'
                f'<td><span class="tag tag-json">JSON</span></td>'
                f'<td>{cdp_tag}</td></tr>')
        lines.append('</table>')
        lines.append('<p style="margin-top:1em;font-size:13px;color:#888">'
                     '<a href="/opml.xml">📡 Import OPML</a> &middot; '
                     '<a href="/healthz?check=1">❤️ Source check</a>'
                     ' &middot; Add any RSS URL to your reader.</p>')
        lines.append('</body></html>')
        html = '\n'.join(lines)
        self._send_text(200, 'text/html; charset=utf-8', html,
                        cache=False, write_body=write_body)


class BoundedThreadPoolServer(ThreadingHTTPServer):
    """HTTPServer with a fixed-size thread pool instead of per-request threads."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, max_workers=MAX_WORKERS, **kwargs):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def process_request(self, request, client_address):
        self.executor.submit(self.process_request_thread, request, client_address)

    def server_close(self):
        self.executor.shutdown(wait=False)
        super().server_close()


# ── CDP init ────────────────────────────────────────────────────────────────

def init_cdp():
    """Initialize CDP engine with persistent CLS pages."""
    global cdp_engine
    try:
        print('[CDP] init_cdp started')
        if not ensure_chrome():
            print('  ✗ Chrome not available. CDP endpoints will return errors.')
            return
        cdp_engine = CDPEngine()
        # Chrome may still be starting — retry connect up to 15s
        for attempt in range(15):
            if cdp_engine.start():
                print(f'[CDP] connected on attempt {attempt+1}')
                break
            time.sleep(1)
        else:
            print('  ✗ Failed to connect to Chrome CDP after 15s.')
            return
        cdp_engine.add_page('cls_finance', 'https://www.cls.cn/finance')
        cdp_engine.add_page('cls_quotation', 'https://www.cls.cn/quotation')
        cdp_engine.add_page('cls_stock', 'https://www.cls.cn/stock?code=sz300139', heartbeat=False)
        for i in range(2, 15):
            cdp_engine.add_page(f'cls_stock_{i}', 'https://www.cls.cn/stock?code=sz300139', heartbeat=False)
        cdp_engine.add_page('cls_f10', 'https://www.cls.cn/stock?code=sz300139', heartbeat=False)
        print('  ✓ CDP engine ready — finance, quotation, 14 stock pages & F10')
        import config
        config.cdp_engine = cdp_engine
    except Exception as e:
        import traceback
        print(f'  ✗ init_cdp error: {e}')
        traceback.print_exc()


# ── Main entry point ────────────────────────────────────────────────────────

def main():
    def _signal_handler(signum, frame):
        print(f'[exit] received signal {signum} ({signal.Signals(signum).name})')
        sys.exit(0)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    @atexit.register
    def _shutdown():
        if cdp_engine:
            cdp_engine.shutdown()

    from utils import warm_jin10_headers
    threading.Thread(target=warm_jin10_headers, daemon=True).start()
    threading.Thread(target=init_cdp, daemon=True).start()
    threading.Thread(target=_fundflow_prefetch_loop, daemon=True).start()
    threading.Thread(target=_timeline_prefetch_loop, daemon=True).start()
    threading.Thread(target=_f10_prefetch_loop, daemon=True).start()
    threading.Thread(target=_announcement_prefetch_loop, daemon=True).start()

    print(f'China Finance RSS Bridge running on http://localhost:{PORT}')
    print(f'Cache TTL: {CACHE_TTL}s | Timeout: {REQUEST_TIMEOUT}s')
    print('Available feeds:')
    for path, info in ROUTES.items():
        print(f'  http://localhost:{PORT}{path}  — {info["name"]}')
    print(f'\nUtilities:')
    print(f'  http://localhost:{PORT}/finance/market  — Finance Market Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/finance/timeline  — Finance Timeline (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/quotation/market  — Quotation Market Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/market/timeline  — Market Index Timeline (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/cls/hotplate  — Hotplate Data (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/stock/data  — Stock Detail Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/stock/fundflow  — Stock Fund Flow (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/stock/timeline  — Stock Timeline (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/stock/f10  — Stock F10 Financial Summary (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/stock/basic_info  — Stock Basic Info (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/stock/announcement  — Stock Announcement (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/market/margin  — Market Margin (融资融券, JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/market/northbound  — Market Northbound (北向资金, JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/market/northbound/history  — Market Northbound History (北向资金历史, JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/opml.xml  — OPML subscription list')
    print(f'  http://localhost:{PORT}/healthz?check=1  — Source health check')
    print(f'Visit http://localhost:{PORT}/ for the web index.\n')

    server = BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
