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

import os
import json
import re
import signal
import sys
import threading
import urllib.request
import hashlib
from html import unescape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlencode, urlparse
from datetime import datetime, timedelta, timezone
from time import time
from email.utils import formatdate
from xml.etree import ElementTree as ET

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
MAX_CACHE_SIZE = 200


def fetch_json(url, headers=None):
    """Fetch URL with in-memory cache."""
    now = time()
    with _cache_lock:
        if url in cache and now - cache[url]['time'] < CACHE_TTL:
            return cache[url]['data']

    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = resp.read().decode('utf-8')

    with _cache_lock:
        if len(cache) >= MAX_CACHE_SIZE:
            cache.clear()
        cache[url] = {'data': data, 'time': now}
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
        items.append({
            'title': item.get('brief') or item.get('content', '')[:100],
            'link': f'https://www.cls.cn/detail/{item_id}',
            'description': item.get('content', ''),
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

        items.append({
            'title': item.get('title', ''),
            'link': item.get('url_w', '') or f"https://kuaixun.eastmoney.com/a/{item.get('newsid', '')}",
            'description': item.get('digest', ''),
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
        items.append({
            'title': item.get('title', ''),
            'link': item.get('url', '') or f"https://news.10jqka.com.cn/{item.get('seq', '')}",
            'description': item.get('digest', item.get('remark', '')),
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


def _start_chrome():
    """Launch headless Chrome if not already running. Returns True on success."""
    import subprocess
    port = urlparse(CDP_URL).port or 9222
    try:
        urllib.request.urlopen(f"http://localhost:{port}/json", timeout=2)
        return True
    except Exception:
        pass

    candidates = [
        'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
        'google-chrome-unstable',
    ]
    chrome = next((c for c in candidates if subprocess.run(
        ['which', c], capture_output=True).returncode == 0), None)
    if not chrome:
        return False

    subprocess.Popen([
        chrome, '--headless', f'--remote-debugging-port={port}',
        '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
        '--remote-allow-origins=*',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(15):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/json", timeout=2)
            return True
        except Exception:
            import time
            time.sleep(1)
    return False


def _cdp_find_tab(site_hint=''):
    """Find a CDP tab matching site_hint, or create a new one via CDP."""
    tabs = json.loads(urllib.request.urlopen(f"{CDP_URL}/json", timeout=5).read())
    tab = next((t for t in tabs if site_hint in t.get('url', '')), None)
    if not tab:
        tab = _cdp_create_tab(site_hint)
        if not tab:
            return None
    ws_url = tab['webSocketDebuggerUrl']
    cdp_host = urlparse(CDP_URL).hostname
    return ws_url.replace('127.0.0.1', cdp_host).replace('localhost', cdp_host)


def _cdp_create_tab(url):
    """Create a new CDP tab via Target.createTarget."""
    import websocket as ws_mod
    tabs = json.loads(urllib.request.urlopen(f"{CDP_URL}/json", timeout=5).read())
    if not tabs:
        return None
    first_url = tabs[0]['webSocketDebuggerUrl']
    cdp_host = urlparse(CDP_URL).hostname
    ws_url = first_url.replace('127.0.0.1', cdp_host).replace('localhost', cdp_host)
    ws = ws_mod.create_connection(ws_url, timeout=15)
    ws.send(json.dumps({
        'id': 1, 'method': 'Target.createTarget', 'params': {'url': url}
    }))
    result = json.loads(ws.recv())
    ws.close()
    tid = result.get('result', {}).get('targetId')
    if not tid:
        return None
    return {'webSocketDebuggerUrl': f'ws://{cdp_host}:{urlparse(CDP_URL).port or 9222}/devtools/page/{tid}'}


def _cdp_execute(ws_url, js, timeout=30):
    """Send JS to a CDP tab and return the result value."""
    import websocket as ws_mod
    ws = ws_mod.create_connection(ws_url, timeout=timeout)
    ws.send(json.dumps({
        'id': 1, 'method': 'Runtime.evaluate',
        'params': {'expression': js, 'awaitPromise': True, 'returnByValue': True}
    }))
    result = json.loads(ws.recv())
    ws.close()
    raw = result.get('result', {}).get('result', {}).get('value', '{}')
    return json.loads(raw)


# URL pattern → meaningful key name mapping for CLS finance API
CDP_API_KEY_MAP = {
    'emotion': 'market_sentiment',
    'articles': 'articles',
    'up_down': 'advance_decline',
    'tline': 'timeline',
    'refresh': 'live_refresh',
    'anchor': 'anchor',
    'basic': 'basic_info',
}


def _remap_cdp_keys(data):
    """Remap URL-based keys from CDP capture to meaningful short names."""
    if not isinstance(data, dict):
        return data
    mapped = {}
    for url, value in data.items():
        key = None
        for pattern, name in CDP_API_KEY_MAP.items():
            if pattern in url:
                key = name
                break
        mapped[key or url] = value
    return mapped


def handle_finance_market(feed_url=None):
    """CLS Finance Market Data (财联社看盘) via Chrome CDP.

    Returns JSON with market heat, index data, stock pools, and live feed.
    Requires Chrome CDP enabled (same as Xueqiu).
    """
    now = time()
    with _feed_cache_lock:
        entry = feed_cache.get('__finance_market__')
        if entry and now - entry['time'] < CACHE_TTL:
            return entry['data']

    data = finance_fetch_via_cdp()
    if data is None:
        return {'error': 'Chrome CDP not available or CLS finance tab not found. See README.'}

    with _feed_cache_lock:
        feed_cache['__finance_market__'] = {'data': data, 'time': time()}
    return data


def xueqiu_fetch_via_cdp(api_path):
    """Fetch Xueqiu API via Chrome CDP to bypass WAF.

    Requires:
    - Chrome running with --remote-debugging-port
    - A Xueqiu tab open and logged in
    - pip install websocket-client
    """
    try:
        import websocket as ws_mod  # noqa: lazy import
    except ImportError:
        return None

    try:
        ws_url = _cdp_find_tab('xueqiu')
        if not ws_url:
            return None
        return _cdp_execute(ws_url, f'fetch("{api_path}").then(r=>r.json()).then(d=>JSON.stringify(d))', timeout=15)
    except Exception:
        return None


def _cdp_connect_tab(url):
    """Create a CDP tab and establish WebSocket. Returns (ws_url, ws, send, recv) or None values."""
    try:
        import websocket as ws_mod
    except ImportError:
        return None, None, None, None

    tab = _cdp_create_tab(url)
    if not tab:
        return None, None, None, None
    ws_url = tab['webSocketDebuggerUrl']
    cdp_host = urlparse(CDP_URL).hostname
    ws_url = ws_url.replace('127.0.0.1', cdp_host).replace('localhost', cdp_host)
    ws = ws_mod.create_connection(ws_url, timeout=30)
    send = lambda m: ws.send(json.dumps(m))
    recv = lambda: json.loads(ws.recv())
    return ws_url, ws, send, recv


def _cdp_inject_xhr_interceptor(send, recv):
    """Inject XHR interceptor before any page script runs to capture CLS finance API responses."""
    send({'id': 1, 'method': 'Page.enable', 'params': {}})
    recv()

    send({'id': 2, 'method': 'Page.addScriptToEvaluateOnNewDocument', 'params': {
        'source': '''
            window.__cdp_api = {};
            var _open = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(m, u) {
                this._url = u;
                return _open.apply(this, arguments);
            };
            var _send = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.send = function() {
                this.addEventListener('load', function() {
                    var url = this._url || '';
                    if (url.indexOf('emotion') > -1 || url.indexOf('articles') > -1 ||
                        url.indexOf('up_down') > -1 || url.indexOf('tline') > -1 ||
                        url.indexOf('refresh') > -1 || url.indexOf('anchor') > -1 ||
                        url.indexOf('basic') > -1) {
                        try { window.__cdp_api[url] = JSON.parse(this.responseText); }
                        catch(e) { window.__cdp_api[url] = {_raw: this.responseText.substring(0,200)}; }
                    }
                });
                return _send.apply(this, arguments);
            };
        '''
    }})
    recv()


def _cdp_navigate_and_wait(ws, send, recv, url, timeout=15):
    """Navigate to a URL and wait for Page.loadEventFired."""
    import time
    send({'id': 3, 'method': 'Page.navigate', 'params': {'url': url}})
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(deadline - time.time())
        try:
            msg = recv()
        except Exception:
            break
        if msg.get('method') == 'Page.loadEventFired':
            return True
    return False


def finance_fetch_via_cdp():
    """Fetch CLS finance market data via Chrome CDP.

    Creates a tab, injects an XHR interceptor to capture API responses
    the page's own React code makes, navigates to the finance page,
    and returns the captured data.
    """
    try:
        import websocket as ws_mod  # noqa: lazy import
    except ImportError:
        return None

    try:
        import time
        ws_url, ws, send, recv = _cdp_connect_tab('about:blank')
        if not ws:
            return None

        _cdp_inject_xhr_interceptor(send, recv)
        loaded = _cdp_navigate_and_wait(ws, send, recv, 'https://www.cls.cn/finance')
        ws.close()

        if not loaded:
            time.sleep(1)

        # Poll for XHR data — return as soon as data arrives instead of fixed sleep
        deadline = time.time() + 10
        keys = []
        while time.time() < deadline:
            try:
                raw = _cdp_execute(ws_url, 'JSON.stringify(Object.keys(window.__cdp_api))', timeout=5) or []
                keys = raw if isinstance(raw, list) else []
                if len(keys) >= 1:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        data = _cdp_execute(ws_url, 'JSON.stringify(window.__cdp_api)', timeout=10) or {}
        return _remap_cdp_keys(data)
    except Exception as exc:
        print(f"finance CDP fetch failed: {exc}")
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

    return {
        'status': status,
        'cache_ttl': CACHE_TTL,
        'request_timeout': REQUEST_TIMEOUT,
        'feeds': feeds,
    }


class RSSHandler(BaseHTTPRequestHandler):
    """HTTP request handler for RSS feeds."""

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
            query = parse_qs(parsed.query)
            if query.get('refresh', ['0'])[0] in ('1', 'true', 'yes'):
                with _feed_cache_lock:
                    feed_cache.pop('__finance_market__', None)
            data = handle_finance_market()
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
        """Thread-safe feed cache lookup with automatic population."""
        now = time()
        with _feed_cache_lock:
            cached = feed_cache.get(path)
            if cached and now - cached['time'] < CACHE_TTL:
                return cached['xml']
        xml = fetch_func()
        with _feed_cache_lock:
            feed_cache[path] = {'xml': xml, 'time': time()}
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
                     '<a href="/opml.xml">Import OPML</a> | '
                     '<a href="/healthz?check=1">Source check</a></p>')
        lines.append('<p>Add any URL above to your RSS reader.</p></body></html>')
        html = '\n'.join(lines)
        self._send_text(200, 'text/html; charset=utf-8', html,
                        cache=False, write_body=write_body)


def warm_jin10_headers():
    try:
        get_jin10_public_headers()
    except Exception:
        pass


def ensure_chrome():
    """Start headless Chrome in background at server startup."""
    if _start_chrome():
        try:
            # Open a finance page tab so it's ready when first request comes
            _cdp_find_tab('https://www.cls.cn/finance')
        except Exception:
            pass
        print(f'  ✓ Headless Chrome running on {CDP_URL}')
    else:
        print(f'  ✗ Headless Chrome not available (install chromium or set CDP_URL)')


def main():
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    threading.Thread(target=warm_jin10_headers, daemon=True).start()
    threading.Thread(target=ensure_chrome, daemon=True).start()

    print(f'China Finance RSS Bridge running on http://localhost:{PORT}')
    print(f'Cache TTL: {CACHE_TTL}s | Timeout: {REQUEST_TIMEOUT}s | CDP: {CDP_URL}\n')
    print('Available feeds:')
    for path, info in ROUTES.items():
        print(f'  http://localhost:{PORT}{path}  — {info["name"]}')
    print(f'  http://localhost:{PORT}/xueqiu/user/{{uid}}  — Xueqiu User (雪球)')
    print(f'\nUtilities:')
    print(f'  http://localhost:{PORT}/finance/market  — Finance Market Data (JSON, needs Chrome CDP)')
    print(f'  http://localhost:{PORT}/opml.xml  — OPML subscription list')
    print(f'  http://localhost:{PORT}/healthz?check=1  — Source health check')
    print(f'\nNote: Xueqiu and Finance Market require Chrome with CDP enabled.')
    print(f'Visit http://localhost:{PORT}/ for the web index.\n')

    server = ThreadingHTTPServer(('0.0.0.0', PORT), RSSHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
