#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""China Finance RSS Bridge

Lightweight RSS bridge server that converts Chinese financial news sources
into standard RSS 2.0 feeds.

Sources: CLS (财联社), Eastmoney (东方财富), THS (同花顺), Xueqiu (雪球)

Usage:
    python server.py
    PORT=9000 python server.py

Dependencies:
    - websocket-client (optional, only for Xueqiu CDP mode)
"""

import atexit
import os
import json
import random
import re
import signal
import sys
import threading
import urllib.request
import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from html import unescape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlencode, urlparse
from datetime import datetime, timedelta, timezone
from time import time
from email.utils import formatdate
from xml.etree import ElementTree as ET

from cdp_engine import ensure_chrome, find_tab, execute_js, CDPEngine

# Configuration via environment variables
PORT = int(os.getenv('PORT', '8053'))
CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')  # Chrome DevTools Protocol URL
CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))  # Cache TTL in seconds (default: 5 min)
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '10'))
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')

# In-memory cache with thread safety
cache = {}
feed_cache = {}
jin10_public_headers = None
_cache_lock = threading.Lock()
_feed_cache_lock = threading.Lock()
_feed_fetch_locks = {}
_feed_fetch_locks_lock = threading.Lock()
_fetch_inflight = {}        # url -> threading.Event for cache stampede protection
MAX_CACHE_SIZE = 200
MAX_FEED_CACHE_SIZE = 100
CACHE_JITTER = 0.2  # ±20% random jitter on TTL to stagger expiry
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '10'))  # Max concurrent request threads


def _expires_at(ttl=None):
    """Return an absolute expiry timestamp with ±CACHE_JITTER random jitter.
    
    Args:
        ttl: Custom TTL in seconds (defaults to CACHE_TTL). Use per-URL TTL
             offsets to stagger expiry across related URLs.
    """
    base = (ttl if ttl is not None else CACHE_TTL)
    return time() + base * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))


def _cache_put(d, key, value, ttl=None):
    """Write to a cache dict with LRU eviction and jittered expiry.
    
    Args:
        ttl: Custom TTL override (defaults to CACHE_TTL in _expires_at).
    """
    with _cache_lock:
        if len(d) >= MAX_CACHE_SIZE:
            oldest = min(d, key=lambda k: d[k]['time'])
            del d[oldest]
        d[key] = {'data': value, 'time': time(), 'expires_at': _expires_at(ttl)}


def _cache_fresh(entry):
    """Check if a cache entry is still within its jittered expiry window."""
    return entry and time() < entry['expires_at']


def fetch_json(url, headers=None, ttl=None):
    """Fetch URL with in-memory cache and stampede protection.

    Uses a per-URL Event for leader election:
      - First thread to create the Event becomes leader and fetches upstream
      - Followers wait on the Event, then read from cache
      - If leader fails, the first follower after cleanup becomes the new leader
      - Follower fallback also writes to cache to prevent cascading misses

    Args:
        ttl: Custom TTL override for the cache entry (defaults to CACHE_TTL).
             Use per-URL offsets to stagger expiry across related URLs.
    """
    now = time()
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry):
            return entry['data']

    with _cache_lock:
        if url in _fetch_inflight:
            event = _fetch_inflight[url]
            is_leader = False
        else:
            _fetch_inflight[url] = threading.Event()
            event = _fetch_inflight[url]
            is_leader = True

    if is_leader:
        try:
            req = Request(url, headers=headers or {})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read().decode('utf-8')
            _cache_put(cache, url, data, ttl=ttl)
            return data
        finally:
            event.set()
            with _cache_lock:
                _fetch_inflight.pop(url, None)
    else:
        event.wait(timeout=REQUEST_TIMEOUT)
        with _cache_lock:
            entry = cache.get(url)
            if _cache_fresh(entry):
                return entry['data']
        req = Request(url, headers=headers or {})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read().decode('utf-8')
        _cache_put(cache, url, data, ttl=ttl)
        return data


def escape_xml(text):
    """Escape special XML characters."""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def timestamp_to_rfc822(ts):
    """Convert Unix timestamp to RFC 822 date string."""
    return formatdate(timeval=ts, localtime=False, usegmt=True)


def parse_china_datetime_to_rfc822(value):
    """Parse a China-local datetime string into an RFC 822 UTC date."""
    dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return formatdate(timeval=dt.timestamp(), localtime=False, usegmt=True)


def strip_html(text):
    """Strip simple HTML tags from upstream snippets."""
    text = re.sub(r'<[^>]+>', '', str(text or ''))
    return unescape(re.sub(r'\s+', ' ', text)).strip()


def clean_title(text, max_len=120):
    """Truncate title to first sentence, max max_len chars."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    for punct in ('。', '！', '？', '；', '\n'):
        idx = truncated.rfind(punct)
        if idx > max_len // 3:
            return text[:idx + 1]
    for punct in ('，', ', '):
        idx = truncated.rfind(punct)
        if idx > max_len // 3:
            return text[:idx]
    return truncated + '…'


def cls_serialize_sign_value(value, key):
    """Serialize a value the same way the CLS frontend signs params."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return f'{key}={value}'
    if isinstance(value, list):
        if not value:
            return f'{key}[]'
        return '&'.join(filter(None, (
            cls_serialize_sign_value(item, f'{key}[{index}]')
            for index, item in enumerate(value)
        )))
    if isinstance(value, dict):
        return '&'.join(filter(None, (
            cls_serialize_sign_value(value[item_key], f'{key}[{item_key}]')
            for item_key in sorted(value, key=lambda item: str(item).upper())
        )))
    return None


def cls_sign_params(params):
    """Sign CLS request params using the public web frontend algorithm."""
    serialized = '&'.join(filter(None, (
        cls_serialize_sign_value(params[key], key)
        for key in sorted(params, key=lambda item: str(item).upper())
    )))
    sha1_digest = hashlib.sha1(serialized.encode('utf-8')).hexdigest()
    return hashlib.md5(sha1_digest.encode('utf-8')).hexdigest()


def extract_jin10_public_app_id(bundle_text):
    """Extract Jin10's public frontend app id from its web bundle."""
    match = re.search(r'"x-app-id":"([^"]+)"', bundle_text)
    if not match:
        raise ValueError('Jin10 public app id not found in frontend bundle')
    return match.group(1)


def get_jin10_public_headers():
    """Build Jin10 headers from public frontend assets without hardcoded ids."""
    global jin10_public_headers
    with _cache_lock:
        if jin10_public_headers:
            return dict(jin10_public_headers)

    base_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.jin10.com/'}
    html = fetch_json('https://www.jin10.com/', base_headers)
    script_match = re.search(r'(?:https:)?//www\.jin10\.com/new/js/index\.[^"\']+\.js', html)
    if not script_match:
        script_match = re.search(r'/new/js/index\.[^"\']+\.js', html)
    if not script_match:
        raise ValueError('Jin10 frontend bundle not found')

    script_url = script_match.group(0)
    if script_url.startswith('//'):
        script_url = 'https:' + script_url
    elif script_url.startswith('/'):
        script_url = 'https://www.jin10.com' + script_url

    bundle = fetch_json(script_url, base_headers)
    app_id = extract_jin10_public_app_id(bundle)

    with _cache_lock:
        if jin10_public_headers:
            return dict(jin10_public_headers)
        jin10_public_headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://www.jin10.com/',
            'Origin': 'https://www.jin10.com',
            'x-app-id': app_id,
            'x-version': '1.0.0',
        }
    return dict(jin10_public_headers)


def generate_rss(title, link, description, items, feed_url=None):
    """Generate standard RSS 2.0 XML."""
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{escape_xml(title)}</title>
<link>{escape_xml(link)}</link>
<description>{escape_xml(description)}</description>
<lastBuildDate>{formatdate(timeval=None, localtime=False, usegmt=True)}</lastBuildDate>
'''
    if feed_url:
        xml += (f'<atom:link href="{escape_xml(feed_url)}" rel="self" '
                'type="application/rss+xml"/>\n')

    for item in items:
        xml += '<item>\n'
        xml += f'<title>{escape_xml(item["title"])}</title>\n'
        xml += f'<link>{escape_xml(item["link"])}</link>\n'
        xml += f'<description>{escape_xml(item["description"])}</description>\n'
        xml += f'<pubDate>{item["pubDate"]}</pubDate>\n'
        xml += f'<guid isPermaLink="false">{escape_xml(item["guid"])}</guid>\n'
        xml += '</item>\n'

    xml += '</channel>\n</rss>'
    return xml


def parse_cls_items(payload):
    """Convert CLS roll_data payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', {}).get('roll_data', []):
        item_id = item.get('id', '')
        content = item.get('content', '')
        title = clean_title(item.get('brief') or content, max_len=120)
        items.append({
            'title': title,
            'link': f'https://www.cls.cn/detail/{item_id}',
            'description': content,
            'pubDate': timestamp_to_rfc822(item.get('ctime', 0)),
            'guid': f'cls_{item_id}',
        })
    return items


def parse_jin10_items(payload):
    """Convert Jin10 flash API payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', []):
        item_id = item.get('id', '')
        data = item.get('data') or {}
        title = data.get('title') or strip_html(data.get('content', ''))[:100]
        content = strip_html(data.get('content') or title)
        link = data.get('source_link') or f'https://flash.jin10.com/detail/{item_id}'
        try:
            pubdate = parse_china_datetime_to_rfc822(item.get('time', ''))
        except Exception:
            pubdate = formatdate(timeval=None, localtime=False, usegmt=True)

        items.append({
            'title': title,
            'link': link,
            'description': content,
            'pubDate': pubdate,
            'guid': f'jin10_{item_id}',
        })
    return items


def parse_wallstreetcn_items(payload):
    """Convert Wallstreetcn live API payload into RSS item dictionaries."""
    items = []
    for item in payload.get('data', {}).get('items', []):
        item_id = item.get('id', '')
        description = item.get('content_text') or strip_html(item.get('content', ''))
        title = item.get('title') or description[:100]
        pub_ts = item.get('display_time') or item.get('created_at') or 0

        items.append({
            'title': title,
            'link': item.get('uri') or f'https://wallstreetcn.com/livenews/{item_id}',
            'description': description,
            'pubDate': timestamp_to_rfc822(int(pub_ts)),
            'guid': f'wallstreetcn_{item_id}',
        })
    return items


def generate_error_rss(title, link, description, error, feed_url=None):
    """Generate a valid RSS feed that explains an upstream failure."""
    error_text = str(error) or error.__class__.__name__
    items = [{
        'title': f'{title} temporarily unavailable',
        'link': link,
        'description': f'Upstream fetch failed: {error_text}',
        'pubDate': formatdate(timeval=None, localtime=False, usegmt=True),
        'guid': f'error_{title}'
    }]
    return generate_rss(title, link, description, items, feed_url=feed_url)


def generate_opml(base_url):
    """Generate an OPML subscription list for all built-in feeds."""
    base_url = (base_url or '').rstrip('/')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head>
<title>China Finance RSS Bridge feeds</title>
</head>
<body>
<outline text="China Finance RSS Bridge" title="China Finance RSS Bridge">
'''
    for path, info in ROUTES.items():
        xml += (f'<outline text="{escape_xml(info["name"])}" title="{escape_xml(info["name"])}" '
                f'type="rss" xmlUrl="{escape_xml(base_url + path)}"/>\n')

    xueqiu_path = '/xueqiu/user/1247347556'
    xueqiu_name = 'Xueqiu User Example (雪球)'
    xml += (f'<outline text="{escape_xml(xueqiu_name)}" title="{escape_xml(xueqiu_name)}" '
            f'type="rss" xmlUrl="{escape_xml(base_url + xueqiu_path)}"/>\n')
    xml += '</outline>\n</body>\n</opml>'
    return xml


# ── Source handlers ──────────────────────────────────────────────────────────

def handle_cls_telegraph(feed_url=None):
    """CLS Telegraph (财联社电报) - Real-time financial news flashes."""
    url = 'https://www.cls.cn/v1/roll/get_roll_list'
    params = {
        'refresh_type': 1,
        'rn': 50,
        'last_time': 0,
        'os': 'web',
        'sv': '8.7.9',
        'app': 'CailianpressWeb',
    }
    params['sign'] = cls_sign_params(params)
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/telegraph'}

    data = json.loads(fetch_json(f'{url}?{urlencode(params)}', headers))

    return generate_rss(
        '财联社电报',
        'https://www.cls.cn/telegraph',
        '财联社实时快讯',
        parse_cls_items(data),
        feed_url=feed_url
    )


def handle_eastmoney_kuaixun(feed_url=None):
    """Eastmoney 7x24 News (东方财富快讯)."""
    url = 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kuaixun.eastmoney.com/'}

    data = fetch_json(url, headers)
    match = re.search(r'var ajaxResult=(\{.*\})', data, re.DOTALL)
    if not match:
        return generate_rss(
            '东方财富快讯',
            'https://kuaixun.eastmoney.com/',
            '东方财富7x24快讯',
            [],
            feed_url=feed_url
        )

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

    return generate_rss(
        '东方财富快讯',
        'https://kuaixun.eastmoney.com/',
        '东方财富7x24快讯',
        items,
        feed_url=feed_url
    )


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

    return generate_rss(
        '同花顺快讯',
        'https://news.10jqka.com.cn/',
        '同花顺7x24快讯',
        items,
        feed_url=feed_url
    )


def handle_jin10_flash(feed_url=None):
    """Jin10 7x24 flash news (金十快讯)."""
    url = 'https://flash-api.jin10.com/get_flash_list?channel=-8200&limit=50'
    data = json.loads(fetch_json(url, get_jin10_public_headers()))
    return generate_rss(
        '金十快讯',
        'https://www.jin10.com/',
        '金十数据7x24快讯',
        parse_jin10_items(data),
        feed_url=feed_url
    )


def handle_wallstreetcn_live(feed_url=None):
    """Wallstreetcn 7x24 live news (华尔街见闻快讯)."""
    url = 'https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&client=pc&limit=50'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json,text/plain,*/*',
        'Referer': 'https://wallstreetcn.com/live',
    }

    data = json.loads(fetch_json(url, headers))
    return generate_rss(
        '华尔街见闻快讯',
        'https://wallstreetcn.com/live',
        '华尔街见闻7x24快讯',
        parse_wallstreetcn_items(data),
        feed_url=feed_url
    )





# Global CDP engine instance (initialized in main)
cdp_engine = None


# Expected CDP data keys per page — ensures external callers always get a
# consistent schema (missing keys → null) instead of silent omissions.
_FINANCE_EXPECTED_KEYS = frozenset({
    'market_sentiment', 'articles', 'advance_decline',
    'timeline', 'live_refresh', 'anchor', 'basic_info',
})

_QUOTATION_EXPECTED_KEYS = frozenset({
    'hot_plate', 'stock_ranking', 'stock_ipo',
    'bj_stock_info', 'index_home', 'timeline', 'basic_info',
})

_STOCK_EXPECTED_KEYS = frozenset({
    'basic_info', 'timeline', 'articles',
    'stock_plate', 'stock_company_info',
    'stock_announcement', 'stock_detail',
    'stock_quote',
    'stock_f10', 'stock_shareholder',
})

# x-quote.cls.cn API base for hotplate data
_HOTPLATE_BASE_URL = 'https://x-quote.cls.cn/web_quote/plate/plate_list'
_HOTPLATE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/hotplate'}

# Fund flow REST API (no CDP needed — direct REST call)
_FUNDFLOW_BASE_URL = 'https://x-quote.cls.cn/quote/stock/fundflow'
_FUNDFLOW_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Background prefetch cache for fund flow (30-stock pool)
_fundflow_cache = {}            # stock_code -> data dict
_fundflow_pool = {}             # stock_code -> last_access_time (for LRU evict)
_fundflow_cache_lock = threading.Lock()
_FUNDFLOW_POOL_REFRESH = 25     # seconds between refresh cycles
_FUNDFLOW_MAX_POOL = 500        # safety cap to prevent OOM from runaway queries
_MAX_BATCH_SIZE = 50             # max stock codes per batch request


def _fill_missing(result, data, expected_keys):
    """Fill expected keys not in data as null, preserving extra keys."""
    for key in expected_keys:
        result[key] = data.get(key)
    for k, v in data.items():
        if k not in expected_keys:
            result[k] = v


def handle_finance_market(feed_url=None):
    """CLS Finance Market Data (财联社看盘) via Chrome CDP.

    Returns JSON with market heat, index data, stock pools, and live feed.
    Data is continuously collected by a persistent CDP page (see cdp_engine.py).
    Once collected, _last_data persists across reconnections — external
    callers always get data once initial collection completes.
    """
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')
    if not page:
        return {'error': 'Finance page not initialized.'}
    data = page.get_data()
    ws_raw = data.pop('__ws__', None)
    result = {}
    _fill_missing(result, data, _FINANCE_EXPECTED_KEYS)
    if ws_raw:
        result['ws_count'] = len(ws_raw)
        result['ws_latest'] = ws_raw[-5:] if ws_raw else []
    return result


def handle_cls_quotation(feed_url=None):
    """CLS Quotation Market Data (财联社行情) via Chrome CDP.

    Returns JSON with index timelines, advance/decline distribution,
    hot sectors, stock rankings, NEEQ/BSE data, and IPO info.
    Data is continuously collected by a persistent CDP page (see cdp_engine.py).
    Once collected, _last_data persists across reconnections — external
    callers always get data once initial collection completes.
    """
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_quotation')
    if not page:
        return {'error': 'Quotation page not initialized.'}
    data = page.get_data()
    result = {}
    _fill_missing(result, data, _QUOTATION_EXPECTED_KEYS)
    return result


def handle_cls_stock(stock_code, timeout=30):
    """CLS Stock Detail Data (财联社个股详情) via persistent CDP page.

    Reuses a single hidden tab; navigates to the requested stock code,
    waits for fresh data, caches the result, and returns immediately.
    """
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_stock')
    if not page:
        return {'error': 'Stock page not initialized.'}
    page.navigate_stock(stock_code, timeout=timeout)
    data = page.get_data()
    result = {}
    _fill_missing(result, data, _STOCK_EXPECTED_KEYS)
    return result


def fetch_cls_fundflow(stock_code):
    """Fetch fund flow — CDP evaluate_fetch first, REST fallback.

    Uses fetch_json cache (15s TTL) for user-facing requests.
    The background prefetch loop uses _fundflow_direct_fetch instead.
    """
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')

    # Fallback: use fetch_json with cache
    url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _FUNDFLOW_HEADERS, ttl=15))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    return None


def _fundflow_direct_fetch(stock_code):
    """Fetch fund flow data via CDP browser context (anti-ban).

    Uses the persistent cls_fundflow page's JavaScript runtime to fire
    a fetch() call — request comes from the browser (same IP, cookies,
    headers as a real CLS user). Falls back to direct REST if CDP is
    not available or fails.
    """
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
            # Evaluate may return the raw data differently; check for error field
            if result and isinstance(result, dict) and result.get('error'):
                print(f'[fundflow] CDP fetch error for {stock_code}: {result["error"]}')

    # Fallback: direct REST call (no browser protection)
    req = Request(f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}',
                   headers=_FUNDFLOW_HEADERS)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if raw.get('code') == 200:
                return raw.get('data')
    except Exception:
        pass
    return None


def handle_cls_fundflow(codes):
    """Fund Flow Data (资金流向) — REST-based, batch supported, no CDP needed.

    Args:
        codes: list of stock code strings.
    Returns:
        dict of {stock_code: data_or_None, ...}.
    Auto-registers all codes into the background prefetch pool
    with LRU eviction when _FUNDFLOW_MAX_POOL is exceeded.
    """
    # Deduplicate while preserving order
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]

    if not codes:
        return {}

    now = time()
    with _fundflow_cache_lock:
        for code in codes:
            _fundflow_pool[code] = now
        # LRU evict: trim pool to max size, remove oldest entries
        if len(_fundflow_pool) > _FUNDFLOW_MAX_POOL:
            excess = sorted(_fundflow_pool, key=_fundflow_pool.get)[:len(_fundflow_pool) - _FUNDFLOW_MAX_POOL]
            for code in excess:
                del _fundflow_pool[code]
                _fundflow_cache.pop(code, None)

    result = {}
    missing = []
    with _fundflow_cache_lock:
        for code in codes:
            cached = _fundflow_cache.get(code)
            if cached is not None:
                result[code] = cached
            else:
                missing.append(code)

    for code in missing:
        data = fetch_cls_fundflow(code)
        if data:
            with _fundflow_cache_lock:
                _fundflow_cache[code] = data
            result[code] = data
        else:
            result[code] = None

    return result


def _fundflow_prefetch_loop():
    """Background thread: refresh fund flow for all auto-registered stocks.

    Runs every FUNDFLOW_POOL_REFRESH seconds. Bypasses fetch_json cache
    so data is always fresh. One failed stock does not block others.
    """
    while True:
        time.sleep(_FUNDFLOW_POOL_REFRESH)
        with _fundflow_cache_lock:
            codes = list(_fundflow_pool.keys())
        if not codes:
            continue
        for code in codes:
            data = _fundflow_direct_fetch(code)
            if data:
                with _fundflow_cache_lock:
                    _fundflow_cache[code] = data


def _china_trading_ttl():
    """Return (base_ttl, stagger_step) for China A-share trading status.

    Trading hours (Mon-Fri, UTC+8): 09:30-11:30, 13:00-15:00.
    During trading → short TTL (30s) to keep quant data fresh.
    Outside trading → normal TTL (300s).
    """
    now_utc = datetime.now(timezone.utc)
    now_cst = now_utc + timedelta(hours=8)
    if now_cst.weekday() >= 5:
        return (300, 90)                    # weekend, long TTL
    h, m = now_cst.hour, now_cst.minute
    in_morning = (h == 9 and m >= 30) or (10 <= h <= 10) or (h == 11 and m <= 30)
    in_afternoon = (13 <= h <= 14)
    if in_morning or in_afternoon:
        return (30, 15)                     # trading hours, short TTL
    return (300, 90)                        # night / pre-market, long TTL


def handle_cls_hotplate(feed_url=None):
    """CLS Hotplate Data (财联社板块) — uses same sign mechanism as telegraph.

    Returns:
      plate_industry / plate_concept / plate_area — plate list per type
      hot_plates — combined top 3 + last 3 hot sectors by fund flow (6 total)

    Cache strategy: each plate type gets a staggered TTL so the three entries
    do not expire simultaneously, preventing burst re-fetches.
    During trading hours base=30s, off-hours base=300s.
    """
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
            # Extract hot plates (6 = 3 top + 3 last) from first successful response
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


def xueqiu_fetch_via_cdp(api_path):
    """Fetch Xueqiu API via Chrome CDP to bypass WAF.

    Requires:
    - Chrome running with --remote-debugging-port
    - A Xueqiu tab open and logged in
    - pip install websocket-client
    """
    try:
        import websocket  # noqa: lazy import
    except ImportError:
        return None

    try:
        ws_url = find_tab('xueqiu')
        if not ws_url:
            return None
        return execute_js(ws_url,
                          f'fetch("{api_path}").then(r=>r.json()).then(d=>JSON.stringify(d))',
                          timeout=15)
    except Exception:
        return None


def handle_xueqiu_user(uid, feed_url=None):
    """Xueqiu user timeline (雪球用户动态).

    Uses Chrome CDP to bypass Alibaba Cloud WAF.
    """
    data = xueqiu_fetch_via_cdp(f'/v4/statuses/user_timeline.json?user_id={uid}&page=1&type=0')

    if not data:
        return generate_rss(
            '雪球用户动态', f'https://xueqiu.com/u/{uid}',
            'Error: Chrome CDP not available or Xueqiu tab not found. '
            'See README for setup instructions.', [], feed_url=feed_url
        )

    items = []
    for item in data.get('statuses', []):
        created_at = item.get('created_at', 0) // 1000
        items.append({
            'title': item.get('title', item.get('text', ''))[:100],
            'link': f"https://xueqiu.com/{item.get('id', '')}",
            'description': item.get('description', item.get('text', '')),
            'pubDate': timestamp_to_rfc822(created_at),
            'guid': f"xueqiu_{item.get('id', '')}"
        })

    username = data.get('statuses', [{}])[0].get('user', {}).get('screen_name', uid)
    return generate_rss(
        f'雪球-{username}',
        f'https://xueqiu.com/u/{uid}',
        f'{username}的雪球动态',
        items,
        feed_url=feed_url
    )


# ── HTTP Server ──────────────────────────────────────────────────────────────

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


def count_rss_items(xml):
    """Return the number of RSS items in a generated feed."""
    root = ET.fromstring(xml)
    return len(root.findall('./channel/item'))


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

    feeds.append({
        'name': 'Xueqiu User Example (雪球)',
        'path': '/xueqiu/user/1247347556',
        'url': base_url + '/xueqiu/user/1247347556',
        'status': 'requires_chrome_cdp',
    })

    feeds.append({
        'name': 'CLS Finance Market (财联社看盘)',
        'path': '/finance/market',
        'url': base_url + '/finance/market',
        'status': 'requires_chrome_cdp',
    })

    feeds.append({
        'name': 'CLS Quotation Market (财联社行情)',
        'path': '/quotation/market',
        'url': base_url + '/quotation/market',
        'status': 'requires_chrome_cdp',
    })

    feeds.append({
        'name': 'CLS Stock Detail (财联社个股详情)',
        'path': '/stock/data',
        'url': base_url + '/stock/data',
        'status': 'requires_chrome_cdp',
    })

    feeds.append({
        'name': 'CLS Stock Fund Flow (财联社个股资金流向)',
        'path': '/stock/fundflow',
        'url': base_url + '/stock/fundflow',
        'status': 'configured',
    })

    feeds.append({
        'name': 'CLS Hotplate (财联社板块)',
        'path': '/cls/hotplate',
        'url': base_url + '/cls/hotplate',
        'status': 'configured',
    })

    return {
        'status': status,
        'cache_ttl': CACHE_TTL,
        'request_timeout': REQUEST_TIMEOUT,
        'feeds': feeds,
    }


class RSSHandler(BaseHTTPRequestHandler):
    """HTTP request handler for RSS feeds."""

    timeout = 30  # seconds — prevents slow clients from tying up worker threads

    def log_date_time_string(self):
        """Return current Beijing time (UTC+8) for access logs."""
        from time import strftime, gmtime
        return strftime('%d/%b/%Y %H:%M:%S', gmtime(time() + 28800))

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
                            generate_opml(base_url), write_body=write_body)
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
            data = handle_finance_market()
            body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=True, write_body=write_body)
            return
        if path == '/quotation/market':
            data = handle_cls_quotation()
            body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=True, write_body=write_body)
            return
        if path == '/stock/data':
            params = parse_qs(parsed.query)
            if 'code' not in params:
                self._send_text(400, 'application/json; charset=utf-8',
                                json.dumps({'error': 'Missing ?code= parameter. Usage: /stock/data?code=sh600519'}),
                                cache=False, write_body=write_body)
                return
            stock_code = params['code'][0]
            data = handle_cls_stock(stock_code)
            body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=True, write_body=write_body)
            return
        if path == '/stock/fundflow':
            params = parse_qs(parsed.query)
            if 'code' not in params:
                self._send_text(400, 'application/json; charset=utf-8',
                                json.dumps({'error': 'Missing ?code= parameter. Usage: /stock/fundflow?code=sh600519 or /stock/fundflow?code=sh600519,sz000001'}),
                                cache=False, write_body=write_body)
                return
            codes_str = params['code'][0]
            stock_codes = [c.strip() for c in codes_str.split(',') if c.strip()]
            if not stock_codes:
                self._send_text(400, 'application/json; charset=utf-8',
                                json.dumps({'error': 'No valid stock codes provided.'}),
                                cache=False, write_body=write_body)
                return
            if len(stock_codes) > _MAX_BATCH_SIZE:
                stock_codes = stock_codes[:_MAX_BATCH_SIZE]
            data = handle_cls_fundflow(stock_codes)
            if len(stock_codes) == 1:
                body = json.dumps({'fund_flow': data.get(stock_codes[0])},
                                  ensure_ascii=False, indent=2)
            else:
                body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=True, write_body=write_body)
            return
        if path == '/cls/hotplate':
            data = handle_cls_hotplate()
            body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=True, write_body=write_body)
            return
        if path in ROUTES:
            self._serve_feed(path, base_url, write_body=write_body)
            return
        if path.startswith('/xueqiu/user/'):
            uid = path.split('/')[-1]
            feed_url = base_url + path
            xml = self._get_or_fetch_feed(
                path, lambda: handle_xueqiu_user(uid, feed_url=feed_url))
            self._send_text(200, 'application/rss+xml; charset=utf-8',
                            xml, write_body=write_body)
            return

        self.send_error(404, 'Not Found. Visit / for available feeds.')

    def _get_or_fetch_feed(self, path, fetch_func):
        """Thread-safe feed cache lookup with stampede protection and LRU eviction."""
        now = time()
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
                if cached and time() < cached['expires_at']:
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
                    'xml': xml, 'time': time(),
                    'expires_at': time() + CACHE_TTL * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))
                }
        return xml

    def _serve_feed(self, path, base_url, write_body=True):
        handler = ROUTES[path]['handler']
        feed_url = base_url + path

        try:
            xml = self._get_or_fetch_feed(path, lambda: handler(feed_url=feed_url))
        except Exception as exc:
            info = ROUTES[path]
            xml = generate_error_rss(info['title'], info['link'], info['description'], exc, feed_url=feed_url)

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
        """Serve a simple index page listing available feeds."""
        lines = ['<html><head><title>China Finance RSS Bridge</title></head>',
                 '<body><h1>🇨🇳 China Finance RSS Bridge</h1><ul>']
        for path, info in ROUTES.items():
            lines.append(f'<li><a href="{path}">{info["name"]}</a></li>')
        lines.append(f'<li><a href="/xueqiu/user/1247347556">Xueqiu User Example (雪球)</a></li>')
        lines.append('</ul><p><a href="/finance/market">Finance Market JSON</a> | '
                      '<a href="/quotation/market">Quotation Market JSON</a> | '
                      '<a href="/cls/hotplate">Hotplate JSON (板块)</a> | '
                      '<a href="/stock/data?code=sz300139">Stock Detail JSON (sz300139)</a> | '
                      '<a href="/stock/fundflow?code=sh600519">Stock Fund Flow JSON (sh600519)</a> | '
                      '<a href="/opml.xml">Import OPML</a> | '
                      '<a href="/healthz?check=1">Source check</a></p>')
        lines.append('<p>Add any URL above to your RSS reader.</p></body></html>')
        html = '\n'.join(lines)
        self._send_text(200, 'text/html; charset=utf-8', html,
                        cache=False, write_body=write_body)


class BoundedThreadPoolServer(ThreadingHTTPServer):
    """HTTPServer with a fixed-size thread pool instead of per-request threads.

    Prevents thread explosion on 2C2G hardware under burst traffic.
    Falls back to the parent's thread-per-request for truly concurrent CDP requests,
    but the pool limits how many in-flight requests can consume worker threads.
    """

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


def warm_jin10_headers():
    try:
        get_jin10_public_headers()
    except Exception:
        pass


def init_cdp():
    """Initialize CDP engine with persistent CLS finance page."""
    global cdp_engine
    if not ensure_chrome():
        print('  ✗ Chrome not available. CDP endpoints will return errors.')
        return
    cdp_engine = CDPEngine()
    if not cdp_engine.start():
        print('  ✗ Failed to connect to Chrome CDP.')
        return
    cdp_engine.add_page('cls_finance', 'https://www.cls.cn/finance')
    cdp_engine.add_page('cls_quotation', 'https://www.cls.cn/quotation')
    cdp_engine.add_page('cls_stock', 'https://www.cls.cn/stock?code=sz300139',
                        heartbeat=False)
    # Lightweight page for fund flow API calls — no heartbeat, no navigation
    cdp_engine.add_page('cls_fundflow', 'https://www.cls.cn/stock',
                        heartbeat=False)
    print(f'  ✓ CDP engine ready — finance, quotation, stock & fundflow pages')


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

    threading.Thread(target=warm_jin10_headers, daemon=True).start()
    threading.Thread(target=init_cdp, daemon=True).start()
    threading.Thread(target=_fundflow_prefetch_loop, daemon=True).start()

    print(f'China Finance RSS Bridge running on http://localhost:{PORT}')
    print(f'Cache TTL: {CACHE_TTL}s | Timeout: {REQUEST_TIMEOUT}s')
    print('Available feeds:')
    for path, info in ROUTES.items():
        print(f'  http://localhost:{PORT}{path}  — {info["name"]}')
    print(f'  http://localhost:{PORT}/xueqiu/user/{{uid}}  — Xueqiu User (雪球)')
    print(f'\nUtilities:')
    print(f'  http://localhost:{PORT}/finance/market  — Finance Market Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/quotation/market  — Quotation Market Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/cls/hotplate  — Hotplate Data (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/stock/data  — Stock Detail Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/stock/fundflow  — Stock Fund Flow (JSON, no CDP needed)')
    print(f'  http://localhost:{PORT}/opml.xml  — OPML subscription list')
    print(f'  http://localhost:{PORT}/healthz?check=1  — Source health check')
    print(f'\nNote: Xueqiu, Finance Market, Quotation and Stock Detail require Chrome with CDP enabled.\n      Hotplate and Stock Fund Flow do NOT require CDP — they use direct API calls with signing.')
    print(f'Visit http://localhost:{PORT}/ for the web index.\n')

    server = BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
