#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""China Finance RSS Bridge

Lightweight RSS bridge server that converts Chinese financial news sources
into standard RSS 2.0 feeds.

Sources: CLS (财联社), Eastmoney (东方财富), THS (同花顺)

Usage:
    python -m china_finance_rss.server
    PORT=9000 python -m china_finance_rss.server

Dependencies:
    - websocket-client (optional, for CDP mode)
"""

import atexit
import gzip
import json
import re
import signal
import sys
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from email.utils import formatdate
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.parse import parse_qs, urlencode

from . import config
from . import metrics
from .cdp_engine import (ensure_chrome, CDPEngine, full_chrome_restart,
                         restart_window_snapshot, watchdog_restart_skip_reason,
                         page_data)
from .config import (
    PORT, REQUEST_TIMEOUT, PUBLIC_BASE_URL, MAX_WORKERS, MAX_INFLIGHT,
    LISTEN_BACKLOG, DOMAIN_MATRIX, cache_policy,
    _MAX_BATCH_SIZE,
    _FINANCE_EXPECTED_KEYS, _QUOTATION_EXPECTED_KEYS,
    _HOTPLATE_BASE_URL, _HOTPLATE_HEADERS,
    _PLATE_INFO_URL, _PLATE_STOCKS_URL, _PLATE_INDUSTRY_URL,
    _PLATE_HEADERS,
    CDP_RESTART_INTERVAL, stock_nav_page_names,
    cdp_engine,
)
from .cache import (fetch_json, feed_cache_get, feed_cache_put,
                    _feed_fetch_locks, _feed_fetch_locks_lock,
                    build_batch_response, _fill_missing, FetchError,
                    warm_transport)
from .utils import (
    generate_rss, generate_error_rss, generate_opml, count_rss_items,
    parse_cls_items, parse_jin10_items, parse_wallstreetcn_items,
    cls_sign_params, get_jin10_public_headers,
    timestamp_to_rfc822, parse_china_datetime_to_rfc822,
)
from .stock_api import (
    handle_cls_stock_batch, handle_cls_fundflow,
    handle_cls_timeline, handle_cls_f10, handle_cls_basic_infos,
    handle_cls_announcement,
    _fundflow_prefetch_loop, _timeline_prefetch_loop,
    _f10_prefetch_loop,
    _announcement_prefetch_loop,
)
from .market_api import (
    handle_margin,
    VALID_MARKETS,
)

log = logging.getLogger('server')


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
    data = json.loads(fetch_json(f'{url}?{urlencode(params)}', headers, ttl=cache_policy('news_url')['ttl']))
    return generate_rss('财联社电报', 'https://www.cls.cn/telegraph',
                        '财联社实时快讯', parse_cls_items(data), feed_url=feed_url)


def handle_eastmoney_kuaixun(feed_url=None):
    """Eastmoney 7x24 News (东方财富快讯)."""
    url = 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kuaixun.eastmoney.com/'}
    data = fetch_json(url, headers, ttl=cache_policy('news_url')['ttl'])
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
    data = json.loads(fetch_json(url, headers, ttl=cache_policy('news_url')['ttl']))
    items = []
    for item in data.get('data', {}).get('list', []):
        try:
            ctime = int(item.get('ctime', 0))
        except (ValueError, TypeError):
            ctime = int(time.time())
        digest = item.get('digest') or item.get('remark', '')
        items.append({
            'title': item.get('title', ''),
            'link': item.get('url', '') or f"https://news.10jqka.com.cn/{item.get('seq', '')}",
            'description': digest or item.get('title', ''),
            'pubDate': timestamp_to_rfc822(ctime),
            'guid': f"ths_{item.get('seq', '')}"
        })
    return generate_rss('同花顺快讯', 'https://news.10jqka.com.cn/',
                        '同花顺7x24快讯', items, feed_url=feed_url)


def handle_ths_longhu():
    """THS Longhu (同花顺龙虎榜) — full table with top5 buy/sell brokerages.

    Both upstreams go through cache.fetch_json via the shared ≤3-concurrency
    fan-out pool (BR-SRV-9/30): no direct urlopen, and elapsed time is max(url)
    not sum(url).  TTL *and* encoding come from `cache_policy('longhu')` — the
    per-domain encoding authority is actually consumed here (P2), so a matrix
    change can no longer silently drift from a hard-coded 'gbk' literal.
    """
    policy = cache_policy('longhu')
    ttl = policy['ttl']
    encoding = policy.get('encoding', 'utf-8')
    fetched = _fetch_concurrent([
        ('table', lambda: fetch_json(_LHBTABLE_URL, _LHBTABLE_HEADERS,
                                     ttl=ttl, encoding=encoding)),
        ('page', lambda: fetch_json(_LONGHU_PAGE_URL, _LONGHU_PAGE_HEADERS,
                                    ttl=ttl, encoding=encoding)),
    ])
    stock_html = fetched['table']
    if isinstance(stock_html, Exception):
        raise stock_html

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

    page_html = fetched['page']
    if isinstance(page_html, Exception):
        raise page_html

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
        kind = 'buy_top5' if '买入' in label else 'sell_top5'
        stock_idx = broker_idx // 2
        if stock_idx >= len(stocks):
            # P0: a table the `stocks` list does not cover is a data error that
            # must be visible — never silently dropped (it would shift every
            # later stock's seats).
            log.warning('[longhu] broker table #%d (%s) has no matching stock '
                        'row (stocks=%d): entries dropped',
                        broker_idx, kind, len(stocks))
        elif entries:
            stocks[stock_idx][kind] = entries
        # ★ P0: ALWAYS advance after a *matched label*, even when this table
        # parsed 0 entries (`len(bro_cells) < 4`, blank name, or `<th>` data
        # rows).  The buy/sell pairing is positional — two tables per stock, in
        # order — so skipping the increment here shifted every later stock's
        # seats by one and silently mis-attributed fund data (HTTP 200, no
        # error signal).
        broker_idx += 1
    expected = 2 * len(stocks)
    if broker_idx != expected:
        log.warning('[longhu] %d broker tables matched but %d stocks expect %d '
                    '— buy/sell pairing is misaligned',
                    broker_idx, len(stocks), expected)
    return {'data': stocks, 'total': len(stocks)}


def handle_jin10_flash(feed_url=None):
    """Jin10 7x24 flash news (金十快讯)."""
    url = 'https://flash-api.jin10.com/get_flash_list?channel=-8200&limit=50'
    data = json.loads(fetch_json(url, get_jin10_public_headers(), ttl=cache_policy('news_url')['ttl']))
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
    data = json.loads(fetch_json(url, headers, ttl=cache_policy('news_url')['ttl']))
    return generate_rss('华尔街见闻快讯', 'https://wallstreetcn.com/live',
                        '华尔街见闻7x24快讯', parse_wallstreetcn_items(data), feed_url=feed_url)


# ── CDP-based JSON handlers ────────────────────────────────────────────────

def handle_finance_market(feed_url=None):
    """CLS Finance Market Data (财联社看盘) via Chrome CDP (BR-SRV-27)."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')
    data = page_data(page)                      # A 类唯一防御取数入口
    if data is None:
        return {'error': 'Finance page not initialized.'}
    ws_raw = data.pop('__ws__', None)
    data.pop('timeline', None)
    result = {}
    _fill_missing(result, data, _FINANCE_EXPECTED_KEYS)
    if ws_raw:
        result['ws_count'] = len(ws_raw)
        result['ws_latest'] = ws_raw[-5:] if ws_raw else []
    return result


def handle_cls_quotation(feed_url=None):
    """CLS Quotation Market Data (财联社行情) via Chrome CDP (BR-SRV-27)."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_quotation')
    data = page_data(page)
    if data is None:
        return {'error': 'Quotation page not initialized.'}
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
    data = page_data(page)
    if data is None:
        return {'error': 'Quotation page not initialized.'}
    tl = data.get('timeline')
    if tl is None:                              # R18: never return bare null
        return {'error': 'timeline unavailable'}
    return tl


def handle_finance_timeline():
    """CLS Finance Market Timeline — from finance CDP page."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_finance')
    data = page_data(page)
    if data is None:
        return {'error': 'Finance page not initialized.'}
    tl = data.get('timeline')
    if tl is None:                              # R18: never return bare null
        return {'error': 'timeline unavailable'}
    return tl


# ── Hotplate ───────────────────────────────────────────────────────────────

def handle_cls_hotplate(feed_url=None):
    """CLS Hotplate Data (财联社板块) — uses same sign mechanism as telegraph.

    3 partitions fetched through the shared ≤3-concurrency pool (BR-SRV-30),
    each with its own derived stagger TTL (BR-SRV-11). Partition failures
    degrade independently; all-partition failure adds a top-level `error`
    (BR-SRV-31).
    """
    result = {}
    hot_plates = None
    base, stagger = _plate_ttls()
    offsets = {'industry': 0, 'concept': stagger, 'area': stagger * 2}
    specs = []
    for ptype in ('industry', 'concept', 'area'):
        params = {
            'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
            'type': ptype, 'way': 'change', 'page': 1, 'rever': 1,
        }
        params['sign'] = cls_sign_params(params)
        url = f'{_HOTPLATE_BASE_URL}?{urlencode(params)}'
        ttl = base + offsets[ptype]      # default-arg capture (no loop-var closure)
        specs.append((ptype, lambda url=url, ttl=ttl:
                      json.loads(fetch_json(url, _HOTPLATE_HEADERS, ttl=ttl))))
    fetched = _fetch_concurrent(specs)
    errors = []
    for ptype in ('industry', 'concept', 'area'):
        raw = fetched.get(ptype)
        if isinstance(raw, Exception):
            result[f'plate_{ptype}'] = {'error': str(raw)}
            errors.append(str(raw))
            continue
        data = raw.get('data') or raw
        result[f'plate_{ptype}'] = data
        if hot_plates is None:
            mfd = data.get('main_fund_diff') or {}
            top = mfd.get('top_main_fund_diff') or []
            last = mfd.get('last_main_fund_diff') or []
            if top or last:
                hot_plates = top + last
    if hot_plates:
        result['hot_plates'] = hot_plates
    if len(errors) == len(specs):
        result['error'] = '; '.join(errors)
    return result


def handle_cls_plate(code):
    """CLS Plate Data (财联社板块详情) — info + stocks + industry.

    Args:
        code: CLS plate code, e.g. 'cls80484'

    3 segments fetched through the shared ≤3-concurrency pool (BR-SRV-30);
    per-segment dependency semantics preserved verbatim.
    """
    result = {'code': code}
    base, stagger = _plate_ttls()          # info=0 / stocks=1 / industry=2

    def _signed_url(base_url, extra=None):
        params = {
            'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
            'secu_code': code,
        }
        if extra:
            params.update(extra)
        params['sign'] = cls_sign_params(params)
        return f'{base_url}?{urlencode(params)}'

    specs = [
        ('info', lambda: json.loads(fetch_json(
            _signed_url(_PLATE_INFO_URL), _PLATE_HEADERS, ttl=base))),
        ('stocks', lambda: json.loads(fetch_json(
            _signed_url(_PLATE_STOCKS_URL), _PLATE_HEADERS, ttl=base + stagger))),
        ('industry', lambda: json.loads(fetch_json(
            _signed_url(_PLATE_INDUSTRY_URL), _PLATE_HEADERS, ttl=base + stagger * 2))),
    ]
    fetched = _fetch_concurrent(specs)

    raw = fetched.get('info')              # 1) info: failure ⇒ error object
    if isinstance(raw, Exception):
        result['info'] = {'error': str(raw)}
    elif raw.get('code') == 200:
        result['info'] = raw.get('data', {})
    else:
        result['info'] = {'error': raw.get('msg', 'unknown')}

    raw = fetched.get('stocks')            # 2) stocks: failure/non-200 ⇒ []
    result['stocks'] = raw.get('data', {}).get('stocks', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []

    raw = fetched.get('industry')          # 3) industry: failure/non-200 ⇒ []
    result['industry'] = raw.get('data', []) \
        if (not isinstance(raw, Exception) and raw.get('code') == 200) else []
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


# ── Route tables / shapes ───────────────────────────────────────────────────

_SHAPES = frozenset({'batch', 'object', 'rss', 'text'})

# 14 JSON branches → shape. A new JSON endpoint MUST be registered here,
# otherwise _handle_request falls through to 404 (BR-SRV-2). /healthz reuses
# the `object` shape but is deliberately NOT in this table (else the guard
# below would fail at import).
_JSON_SHAPES = {
    '/finance/market': 'object', '/finance/timeline': 'object',
    '/quotation/market': 'object', '/market/timeline': 'object',
    '/stock/data': 'batch', '/stock/fundflow': 'batch', '/stock/timeline': 'batch',
    '/stock/f10': 'batch', '/stock/basic_info': 'batch', '/stock/announcement': 'batch',
    '/cls/hotplate': 'object', '/cls/plate': 'object',
    '/ths/longhu': 'text', '/market/margin': 'object',
}
assert len(_JSON_SHAPES) == 14      # structure guard (P1-6 anti-regression)

_STOCK_BATCH_HANDLERS = {
    '/stock/data': handle_cls_stock_batch,
    '/stock/fundflow': handle_cls_fundflow,
    '/stock/timeline': handle_cls_timeline,
    '/stock/f10': handle_cls_f10,
    '/stock/basic_info': handle_cls_basic_infos,
    '/stock/announcement': handle_cls_announcement,
}
assert set(_STOCK_BATCH_HANDLERS) == {p for p, s in _JSON_SHAPES.items()
                                      if s == 'batch'}

# 4 CDP panels → their handler (P2: the router dispatches from tables, and the
# guard shape is read from _JSON_SHAPES below — never a drifting literal).
_PANEL_HANDLERS = {
    '/finance/market': handle_finance_market,
    '/finance/timeline': handle_finance_timeline,
    '/quotation/market': handle_cls_quotation,
    '/market/timeline': handle_market_timeline,
}
# P2: _JSON_SHAPES must actually be consumed, not decorative.  This set is the
# routing's declared JSON coverage; the assertion makes a new _JSON_SHAPES entry
# without a branch (or a branch without a shape) fail at import time.
_JSON_DISPATCHED_PATHS = (frozenset(_PANEL_HANDLERS)
                          | set(_STOCK_BATCH_HANDLERS)
                          | {'/cls/hotplate', '/cls/plate',
                             '/ths/longhu', '/market/margin'})
assert _JSON_DISPATCHED_PATHS == frozenset(_JSON_SHAPES)

# path → cache-policy domain for Cache-Control max-age (BR-SRV-8). Unregistered
# paths (/healthz, /, /opml.xml) fall back to _DEFAULT_AGE_DOMAIN.
_CACHE_AGE_DOMAINS = {
    # live CDP panels are real-time quote surfaces — never the 300s default (P2)
    '/finance/market': 'quote', '/finance/timeline': 'quote',
    '/quotation/market': 'quote', '/market/timeline': 'quote',
    '/stock/data': 'quote', '/stock/basic_info': 'quote',
    '/stock/fundflow': 'fundflow', '/stock/timeline': 'timeline',
    '/stock/f10': 'f10', '/stock/announcement': 'announcement',
    '/cls/hotplate': 'plate', '/cls/plate': 'plate',
    '/ths/longhu': 'longhu', '/market/margin': 'margin',
    '/cls/telegraph': 'news_url', '/eastmoney/kuaixun': 'news_url',
    '/ths/kuaixun': 'news_url', '/jin10/flash': 'news_url',
    '/wallstreetcn/live': 'news_url',
}
_DEFAULT_AGE_DOMAIN = 'f10'          # L4, factor 1.0 ⇒ constant 300

# ── Request-derived base URL hardening (S2-3) ───────────────────────────────
# X-Forwarded-Host / Host are attacker-controllable, and the derived base URL is
# embedded in feed/opml bodies.  There is no env whitelist, so validate the
# format (hostname[:port] or [ipv6][:port]) — anything else falls back to
# localhost — and mark host-dependent responses `private` + `Vary` so a shared
# cache cannot serve one host's feed URLs to another (cache poisoning).
_HOST_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,253}[A-Za-z0-9])?'
                      r'(?::\d{1,5})?$')
_HOST_IPV6_RE = re.compile(r'^\[[0-9A-Fa-f:.]{2,45}\](?::\d{1,5})?$')
_BASE_URL_VARY = 'Host, X-Forwarded-Host, X-Forwarded-Proto'


def _accepts_gzip(header):
    """True when ``Accept-Encoding`` explicitly accepts gzip (RFC 9110 §12.5.3).

    Parses the comma-separated coding list with optional ``;q=`` weights:
    coding tokens are case-insensitive, ``*`` accepts anything not explicitly
    refused, and ``q=0`` means "not acceptable".  A naive substring test used
    to gzip responses for clients that had explicitly refused gzip
    (``gzip;q=0``) while missing uppercase (``GZIP``).
    """
    best = None
    for part in header.split(','):
        tokens = part.split(';')
        coding = tokens[0].strip().lower()
        if not coding:
            continue
        q = 1.0
        for param in tokens[1:]:
            key, _, val = param.partition('=')
            if key.strip().lower() == 'q':
                try:
                    q = float(val.strip())
                except ValueError:
                    q = 0.0
        if coding == 'gzip':
            best = q                      # explicit coding wins over '*'
        elif coding == '*' and best is None:
            best = q
    return best is not None and best > 0


def _valid_host_header(host):
    """True when ``host`` is a well-formed ``hostname[:port]`` / ``[v6][:port]``.

    Rejects empty / over-long / host-list / injection values (``@``, ``/``,
    whitespace, CR/LF) so a forged Host cannot redefine published feed links."""
    if not host or len(host) > 260:
        return False
    return bool(_HOST_RE.match(host) or _HOST_IPV6_RE.match(host))


def _normalize_proto(value):
    """``X-Forwarded-Proto`` → 'http'/'https' (anything else ⇒ 'http')."""
    proto = (value or '').split(',')[0].strip().lower()
    return proto if proto in ('http', 'https') else 'http'


# longhu upstreams (module-level constants extracted from the old inline
# Request(...) literals; see server.md §10#1).
_LHBTABLE_URL = 'https://data.10jqka.com.cn/ifmarket/lhbtable'
_LHBTABLE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://data.10jqka.com.cn/market/longhu/',
    'X-Requested-With': 'XMLHttpRequest',
}
_LONGHU_PAGE_URL = 'https://data.10jqka.com.cn/market/longhu/'
_LONGHU_PAGE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


# ── Unified exception boundary ──────────────────────────────────────────────

def _guard(fn, *, shape, requested=None, dropped=0, rss_info=None, feed_url=None):
    """Execute fn(); any Exception → structured degraded body by shape.

    BR-SRV-3: never bubbles to do_GET/do_HEAD. `KeyboardInterrupt`/`SystemExit`
    are BaseException and pass through (BR-SRV-4).
    """
    if shape not in _SHAPES:
        raise ValueError(f'unknown guard shape: {shape!r}')
    try:
        return fn()
    except Exception as exc:
        log.exception('[guard:%s] handler raised: %s', shape, exc)
        if shape == 'batch':
            codes = list(dict.fromkeys(requested or []))
            errors = {c: 'upstream_error' for c in codes}
            return build_batch_response(codes, {}, errors, dropped=dropped)
        if shape == 'rss':
            info = rss_info or {}
            return generate_error_rss(info.get('title', 'feed'),
                                      info.get('link', ''),
                                      info.get('description', ''),
                                      exc, feed_url=feed_url)
        return {'error': str(exc)}


# ── Stock-batch ingress: canonical code identity (P1-6) ─────────────────────

def _parse_stock_codes(codes_str):
    """``(codes, requested)`` for one ``?code=a,b,c`` value — ingress fold (P1-6).

    ``codes`` is what the handler is called with: one canonical code per
    distinct stock, in request order (``600519.SH`` / ``SH600519`` /
    ``sh600519`` all fold to ``sh600519`` through the single authority
    ``config.canonical_code``).  Folding *before* the ``_MAX_BATCH_SIZE``
    accounting means a re-spelled duplicate cannot burn a second slot, and
    downstream there is exactly one pool / cache / ledger key per stock however
    the client spelled it.

    ``requested`` is positionally aligned with ``codes`` and carries the
    spelling the client actually sent.  That is the key the response must use:
    ``cache.build_batch_response`` — and therefore ``_guard``'s batch degrade
    body — keys off its ``requested`` list, so the response contract (one row
    per requested code, spelled the way it was requested) is unchanged.

    A code the authority rejects has no canonical form, so its own spelling is
    its identity: the handler reports it per code as ``null`` (SA-T13).  A bad
    code *value* therefore stays a per-code ``null``, never a 400 — 400 is for
    a missing / empty ``?code=`` (server.md §2.1).
    """
    codes, requested, seen = [], [], set()
    for raw in codes_str.split(','):
        raw = raw.strip()
        if not raw:
            continue
        canon = config.canonical_code(raw)
        key = canon if canon is not None else raw        # invalid ⇒ own spelling
        if key in seen:                                  # re-spelled duplicate
            continue
        seen.add(key)
        codes.append(key)
        requested.append(raw)
    return codes, requested


def _rekey_batch_response(data, codes, requested):
    """Re-key a handler-assembled batch body onto the requested spellings (P1-6).

    ``_handle_stock_batch`` calls the handler with canonical codes, so the body
    and its ``_errors`` sub-mapping come back keyed canonically.  The response
    contract is the client's spelling, so data keys are folded back here
    (``codes[i]`` → ``requested[i]``).

    This is a pure rename, not assembly: the key set is exactly the handler's
    (``build_batch_response`` remains the sole assembler of ``_``-prefixed
    reserved keys — server.md §2.4), and a request that needed no re-spelling
    (the common ``sh600519`` case) returns ``data`` untouched, so its body stays
    byte-identical.
    """
    if not isinstance(data, dict):
        return data
    rename = dict(zip(codes, requested))
    if not any(canon != raw for canon, raw in rename.items()):
        return data
    out = {}
    for key, value in data.items():
        if key == '_errors' and isinstance(value, dict):
            out[key] = {rename.get(c, c): kind for c, kind in value.items()}
        elif key.startswith('_'):
            out[key] = value
        else:
            out[rename.get(key, key)] = value
    return out


# ── External upstream fan-out (≤ _FANOUT_MAX_WORKERS concurrent) ────────────

_FANOUT_MAX_WORKERS = 3
# AC-E2 (P1-2): one fan-out cycle must drain within a single REQUEST_TIMEOUT.
# The pool is shared by hotplate/plate/longhu and may already be busy with
# another request's tasks, so the wait is bounded by a deadline instead of by
# each fn's own socket timeout (unbounded `fut.result()` let the queue stretch
# a single request to ~190s while slot #4..N waited).
_FANOUT_WAIT_BUDGET = REQUEST_TIMEOUT
_fanout_executor = None
_fanout_lock = threading.Lock()


def _get_fanout_executor():
    """Lazily create the shared ≤3-concurrency fan-out pool (BR-SRV-30)."""
    global _fanout_executor
    with _fanout_lock:
        if _fanout_executor is None:
            _fanout_executor = ThreadPoolExecutor(
                max_workers=_FANOUT_MAX_WORKERS, thread_name_prefix='fanout')
        return _fanout_executor


def _fetch_concurrent(specs):
    """specs = [(key, fn)]; expand concurrently (≤3); return {key: result|Exception}.

    Never raises. Result order follows specs (deterministic). A single spec
    runs inline to avoid pool overhead.

    BR-SRV-30 / AC-E2: all specs share one `_FANOUT_WAIT_BUDGET` deadline, so a
    request never blocks longer than one REQUEST_TIMEOUT even when the shared
    pool is saturated. An expired spec is cancelled (a task still sitting in the
    work queue never runs; one already running is left to its own
    REQUEST_TIMEOUT bound) and degrades to FetchError('upstream_timeout').
    Nothing is counted here: a real upstream failure is counted by
    cache.fetch_json when it actually happens (no double count).
    """
    if not specs:
        return {}
    if len(specs) == 1:
        k, fn = specs[0]
        try:
            return {k: fn()}
        except Exception as exc:
            return {k: exc}
    ex = _get_fanout_executor()
    futs = {ex.submit(fn): k for k, fn in specs}
    done, _ = wait(futs, timeout=_FANOUT_WAIT_BUDGET)   # ★ bounded drain (P1-2)
    out = {}
    for fut, k in futs.items():
        if fut in done:
            try:
                out[k] = fut.result()
            except Exception as exc:
                out[k] = exc
            continue
        fut.cancel()                        # queued ⇒ never runs; running ⇒
        out[k] = FetchError('upstream_timeout')   # left to its own 10s bound
    return out


def _plate_ttls():
    """Return (base_ttl, stagger); stagger = max(3, base//4) (BR-SRV-10)."""
    base = cache_policy('plate')['ttl']
    return base, max(3, base // 4)


# ── Health payload (bounded admission + budgets + snapshot) ─────────────────

_MAX_HEALTH_INFLIGHT = config.MAX_HEALTH_INFLIGHT
_health_sem = threading.BoundedSemaphore(_MAX_HEALTH_INFLIGHT)
_health_executor = None
_health_executor_lock = threading.Lock()
_health_inflight = 0
_health_inflight_lock = threading.Lock()
_health_last_snapshot = None
_health_last_lock = threading.Lock()

_HEALTH_TOTAL_BUDGET = 10.0
_HEALTH_SOURCE_BUDGET = 3.0
_HEALTH_POLL = 0.25


def _base_feed_entries(base_url):
    """15 healthz feed entries (5 RSS + 10 JSON/CDP); status per §2.9.1."""
    feeds = []
    for path, info in ROUTES.items():
        feeds.append({
            'name': info['name'],
            'path': path,
            'url': base_url + path,
            'status': 'configured',
        })
    feeds.extend([
        {'name': 'CLS Finance Market (财联社看盘)', 'path': '/finance/market',
         'url': base_url + '/finance/market', 'status': 'requires_chrome_cdp'},
        {'name': 'CLS Quotation Market (财联社行情)', 'path': '/quotation/market',
         'url': base_url + '/quotation/market', 'status': 'requires_chrome_cdp'},
        {'name': 'CLS Stock Detail (财联社个股详情)', 'path': '/stock/data',
         'url': base_url + '/stock/data', 'status': 'configured'},
        {'name': 'CLS Stock Fund Flow (财联社个股资金流向)', 'path': '/stock/fundflow',
         'url': base_url + '/stock/fundflow', 'status': 'configured'},
        {'name': 'CLS Hotplate (财联社板块)', 'path': '/cls/hotplate',
         'url': base_url + '/cls/hotplate', 'status': 'configured'},
        {'name': 'CLS Plate Detail (财联社板块详情)', 'path': '/cls/plate?code=cls80484',
         'url': base_url + '/cls/plate?code=cls80484', 'status': 'configured'},
        {'name': 'CLS Stock Timeline (个股分时图)', 'path': '/stock/timeline',
         'url': base_url + '/stock/timeline', 'status': 'configured'},
        {'name': 'CLS Stock F10 (个股F10财务概要)', 'path': '/stock/f10',
         'url': base_url + '/stock/f10', 'status': 'requires_chrome_cdp'},
        {'name': 'CLS Stock Basic Info (个股基本信息)', 'path': '/stock/basic_info',
         'url': base_url + '/stock/basic_info', 'status': 'configured'},
        {'name': 'Market Margin (融资融券)', 'path': '/market/margin',
         'url': base_url + '/market/margin', 'status': 'configured'},
    ])
    return feeds


def _policy_snapshot():
    """{domain: cache_policy(domain)} — domain enum from config.DOMAIN_MATRIX."""
    return {d: cache_policy(d) for d in sorted(DOMAIN_MATRIX)}


def _set_health_inflight(delta):
    global _health_inflight
    with _health_inflight_lock:
        _health_inflight = max(0, _health_inflight + delta)
        metrics.set_gauge('healthz_inflight', _health_inflight)


def _release_health_slot():
    """Release one healthz admission slot (BR-SRV-19; once per batch)."""
    _set_health_inflight(-1)
    _health_sem.release()


class _HealthBatch:
    """Per-?check=1 in-flight ledger (P1-1).

    The admission slot must cover the batch's real in-flight futures, so the
    slot is released only when ALL of this batch's futures have finished —
    not when the polling loop returns."""

    __slots__ = ('_remaining', '_lock', '_done')

    def __init__(self, n):
        self._remaining = n
        self._lock = threading.Lock()
        self._done = False

    def task_done(self, _fut=None):
        """Future completion callback; idempotent — releases the slot once."""
        release = False
        with self._lock:
            self._remaining -= 1
            if self._remaining <= 0 and not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()

    def settle(self):
        """Release the slot NOW, outstanding futures notwithstanding (P1-5).

        Idempotent with :meth:`task_done` via the same `_done` latch: whichever
        path releases first wins, so the error guard in `build_health_payload`
        and a late future callback can never double-release the
        `BoundedSemaphore` (an over-release raises `ValueError`)."""
        release = False
        with self._lock:
            if not self._done:
                self._done = True
                release = True
        if release:
            _release_health_slot()


def _get_health_executor():
    global _health_executor
    with _health_executor_lock:
        if _health_executor is None:
            _health_executor = ThreadPoolExecutor(
                max_workers=_MAX_HEALTH_INFLIGHT, thread_name_prefix='healthz')
        return _health_executor


def _check_one_feed(feed_path, base_url, info):
    """Total function: any exception → error entry (never raises)."""
    try:
        xml = info['handler'](feed_url=base_url + feed_path)
        return {'status': 'ok', 'items': count_rss_items(xml), 'error': None}
    except Exception as exc:
        return {'status': 'error', 'items': None, 'error': str(exc)}


def _run_health_checks(base_url, batch=None):
    """BR-SRV-20: 5 sources concurrent; per-source 3s and total 10s budgets.

    The admission slot is settled by `batch` as each future truly finishes
    (P1-1).  P1-5: a caller may pass the ledger it created, so an exception here
    can be settled by `build_health_payload` instead of leaking the slot.
    Total for `Exception`; `BaseException` propagates to the caller's guard.
    """
    out = {}
    try:
        executor = _get_health_executor()
    except Exception as exc:
        for path in ROUTES:
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
        _release_health_slot()
        return out

    if batch is None:
        batch = _HealthBatch(len(ROUTES))    # ledger before any submit
    started = time.monotonic()
    pending = {}                             # fut -> (path, submitted_at)
    for path, info in ROUTES.items():
        try:
            fut = executor.submit(_check_one_feed, path, base_url, info)
        except Exception as exc:
            out[path] = {'status': 'error', 'items': None, 'error': str(exc)}
            batch.task_done()
            continue
        fut.add_done_callback(batch.task_done)
        pending[fut] = (path, time.monotonic())

    while pending:
        now = time.monotonic()
        for fut in [f for f, (_p, t) in pending.items()
                    if now - t >= _HEALTH_SOURCE_BUDGET]:
            out[pending.pop(fut)[0]] = {'status': 'timeout', 'items': None,
                                        'error': 'timeout'}
        if not pending:
            break
        elapsed = now - started
        if elapsed >= _HEALTH_TOTAL_BUDGET:
            break
        next_due = min(t for _p, t in pending.values()) + _HEALTH_SOURCE_BUDGET
        timeout = min(_HEALTH_POLL, max(0.0, next_due - now),
                      max(0.0, _HEALTH_TOTAL_BUDGET - elapsed))
        done, _ = wait(set(pending), timeout=timeout, return_when=FIRST_COMPLETED)
        for fut in done:
            path = pending.pop(fut)[0]
            try:
                out[path] = fut.result()
            except Exception as exc:        # ★ P1-5: never bubble mid-wait
                out[path] = {'status': 'error', 'items': None,
                             'error': str(exc)}
    for fut, (path, _t) in pending.items():
        out[path] = {'status': 'timeout', 'items': None, 'error': 'timeout'}
    return out


def _remember_health_snapshot(payload):
    global _health_last_snapshot
    with _health_last_lock:
        _health_last_snapshot = json.loads(json.dumps(payload, ensure_ascii=False))


def build_health_payload(base_url, check_sources=False):
    """Build a JSON-serializable health payload (signature unchanged)."""
    feeds = _base_feed_entries(base_url)
    status = 'ok'

    if check_sources:
        if not _health_sem.acquire(blocking=False):     # BR-SRV-18: bounded admission
            metrics.incr('healthz_stale_total')
            with _health_last_lock:
                snap = _health_last_snapshot
            if snap is None:                            # first check already rejected
                snap = {'status': 'degraded',
                        'cache_ttl': cache_policy('feed')['ttl'],
                        'request_timeout': REQUEST_TIMEOUT,
                        'feeds': feeds, 'metrics': metrics.snapshot(),
                        'policy': _policy_snapshot(),
                        'cdp': restart_window_snapshot()}
            return {**snap, 'stale': True}              # no fetch, no snapshot refresh
        _set_health_inflight(+1)
        # ★ P1-5: create the ledger the caller owns BEFORE the risky call, so an
        # exception (executor creation, a `BaseException` out of `fut.result()`,
        # …) settles the admission slot exactly once instead of leaking it
        # forever — 5 leaks pinned every later `?check=1` to a stale body.
        batch = _HealthBatch(len(ROUTES))
        try:
            results = _run_health_checks(base_url, batch)
        except BaseException:
            batch.settle()
            raise
        for entry in feeds:
            res = results.get(entry['path'])
            if res is None:
                continue
            entry['status'] = res['status']
            if res['items'] is not None:
                entry['items'] = res['items']
            if res['error'] is not None:
                entry['error'] = res['error']
            if res['status'] != 'ok':
                status = 'degraded'

    payload = {'status': status,
               'cache_ttl': cache_policy('feed')['ttl'],
               'request_timeout': REQUEST_TIMEOUT,
               'feeds': feeds,
               'metrics': metrics.snapshot(),
               'policy': _policy_snapshot(),
               'cdp': restart_window_snapshot()}
    _remember_health_snapshot(payload)
    return payload


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
        log.info(f"{format % args}")

    def do_HEAD(self):
        try:
            self._handle_request(write_body=False)
        except OSError:          # P2: TimeoutError ⊂ OSError (stream parity)
            pass

    def do_GET(self):
        try:
            self._handle_request(write_body=True)
        except OSError:
            pass

    def _handle_request(self, write_body=True):
        parsed = urlparse(self.path)
        path = parsed.path
        base_url = self._base_url()

        if path == '/':                                     # static, no IO
            self._serve_index(write_body=write_body)
            return
        if path == '/opml.xml':                             # static, no IO
            # S2-3: the OPML embeds the (possibly request-derived) base URL ⇒
            # non-public + Vary whenever it is not from PUBLIC_BASE_URL.
            self._send_text(200, 'text/x-opml; charset=utf-8',
                            generate_opml(base_url, ROUTES),
                            varies_on_host=not PUBLIC_BASE_URL,
                            write_body=write_body)
            return
        if path == '/healthz':                              # BR-SRV-21: object guard
            query = parse_qs(parsed.query)
            check_sources = query.get('check', ['0'])[0] in ('1', 'true', 'yes')
            payload = _guard(
                lambda: build_health_payload(base_url, check_sources=check_sources),
                shape='object')
            # S2-5 / N1: this 503 belongs to the *health* endpoint's own
            # semantics (the guard's failure body is {'error': ...} with no
            # 'status'; treating that as 200 made a broken health check read as
            # healthy).  Data endpoints do NOT share it — see `_send_json_shape`.
            if 'error' in payload or 'status' not in payload:
                status_code = 503
            else:
                status_code = 503 if payload.get('status') == 'degraded' else 200
            if status_code == 503:
                metrics.incr('http_503_total')              # P2: real 503 total
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            self._send_text(status_code, 'application/json; charset=utf-8',
                            body, cache=False, write_body=write_body)
            return

        # ── 4 panels (object) — handler + shape from the dispatch tables ────
        if path in _PANEL_HANDLERS:
            self._send_json_shape(path, _PANEL_HANDLERS[path],
                                  write_body=write_body)
            return

        # ── 6 batch (batch) — shape derived from the route table ────────────
        if path in _STOCK_BATCH_HANDLERS:
            self._handle_stock_batch(parsed, _STOCK_BATCH_HANDLERS[path],
                                     write_body=write_body, path=path)
            return

        # ── remaining 4 JSON branches ───────────────────────────────────────
        if path == '/cls/hotplate':
            self._send_json_shape(path, handle_cls_hotplate,
                                  write_body=write_body)
            return
        if path == '/cls/plate':
            code = parse_qs(parsed.query).get('code', [''])[0]
            if not code:                                    # 400 before guard
                self._send_error(
                    'Missing ?code= parameter. Usage: /cls/plate?code=cls80484',
                    write_body=write_body)
                return
            self._send_json_shape(path, lambda: handle_cls_plate(code),
                                  write_body=write_body)
            return
        if path == '/ths/longhu':                           # text: JSON body, no cache
            data = _guard(handle_ths_longhu, shape=_JSON_SHAPES[path])
            body = json.dumps(data, ensure_ascii=False, indent=2)
            self._send_text(200, 'application/json; charset=utf-8',
                            body, cache=False, write_body=write_body)
            return
        if path == '/market/margin':
            market = parse_qs(parsed.query).get('market', ['99'])[0]
            if market not in VALID_MARKETS:                 # 400 before guard:
                self._send_error(                           # no URL, no cache key
                    'Invalid ?market= parameter. Allowed: '
                    + ','.join(VALID_MARKETS),
                    write_body=write_body)
                return
            self._send_json_shape(path, lambda: handle_margin(market),
                                  write_body=write_body)
            return

        # ── 5 RSS (rss) ─────────────────────────────────────────────────────
        if path in ROUTES:
            self._serve_feed(path, base_url, write_body=write_body)
            return

        self.send_error(404, 'Not Found. Visit / for available feeds.')

    def _handle_stock_batch(self, parsed, handler, write_body=True, path=None):
        params = parse_qs(parsed.query)
        if 'code' not in params:
            self._send_error('Missing ?code= parameter. Usage: /stock/...?code=sh600519 or ...?code=sh600519,sz000001',
                             write_body=write_body)
            return
        # ★ P1-6: fold every code through the single authority on the way in
        # (`config.canonical_code`), so `600519.SH` / `SH600519` / `sh600519`
        # are one stock for the batch budget, for the handler, and for every
        # pool/cache/ledger key downstream.  `requested` carries the client's
        # spelling, which is what the response is keyed by.
        stock_codes, requested = _parse_stock_codes(params['code'][0])
        if not stock_codes:
            self._send_error('No valid stock codes provided.', write_body=write_body)
            return
        dropped = 0
        if len(stock_codes) > _MAX_BATCH_SIZE:              # BR-SRV-14
            dropped = len(stock_codes) - _MAX_BATCH_SIZE
            log.warning(f'Batch truncated: {dropped} codes dropped, '
                        f'samples={stock_codes[_MAX_BATCH_SIZE:_MAX_BATCH_SIZE + 3]}')
            stock_codes = stock_codes[:_MAX_BATCH_SIZE]
            requested = requested[:_MAX_BATCH_SIZE]     # keep the two aligned
        # BR-SRV-15: inject `dropped` only — assembly point is the handler.
        # P2: the guard shape comes from the _JSON_SHAPES table, not a literal.
        data = _guard(lambda: handler(stock_codes, dropped=dropped),
                      shape=_JSON_SHAPES.get(path, 'batch'),
                      requested=requested, dropped=dropped)
        # ★ P1-6: the handler answered in canonical codes; the response contract
        # is the requested spelling (a no-op when nothing was re-spelled).
        data = _rekey_batch_response(data, stock_codes, requested)
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self._send_text(200, 'application/json; charset=utf-8',
                        body, cache=True, write_body=write_body)

    def _send_error(self, msg, write_body=True):
        body = json.dumps({'error': msg}, ensure_ascii=False, indent=2)
        self._send_text(400, 'application/json; charset=utf-8',
                        body, cache=False, write_body=write_body)

    def _send_json(self, data, write_body=True, cache=True):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self._send_text(200, 'application/json; charset=utf-8',
                        body, cache=cache, write_body=write_body)

    def _send_json_shape(self, path, fn, write_body=True, cache=True):
        """Send a JSON endpoint whose guard shape comes from `_JSON_SHAPES`.

        P2: keeps the shape registry authoritative — the router never invents a
        literal shape string that could drift from the table.

        N1 (编排层裁决): 业务降级体 — 上游/CDP 整体不可用时 ``_guard`` 给出的
        ``{'error': ...}`` / ``_error`` 体 — **恒以 HTTP 200 + 结构化 error 体
        返回**，与旧版本及既有业务系统消费的契约一致（状态码不由 payload 内容
        决定）。真实的 503 仅保留两条路径：连接准入拒绝
        (``BoundedThreadPoolServer._reject_503``) 与 ``/healthz`` degraded。
        """
        payload = _guard(fn, shape=_JSON_SHAPES[path])
        self._send_json(payload, write_body=write_body, cache=cache)

    def _get_or_fetch_feed(self, path, fetch_func):
        """BR-SRV-6: stampede protection + double-checked cache lookup.

        LRU / TTL / sweeping are owned by cache.py; this only sequences
        miss → per-path lock → second get → fetch → put.
        """
        xml = feed_cache_get(path)                      # ① hit path: no policy read
        if xml is not None:
            return xml
        with _feed_fetch_locks_lock:                    # ② build lock, release at once
            lock = _feed_fetch_locks.setdefault(path, threading.Lock())
        with lock:                                      # ③
            xml = feed_cache_get(path)                  # ★ double-check
            if xml is not None:
                return xml
            ttl = cache_policy('feed')['ttl']           # ★ P2-1: only after 2nd miss
            xml = fetch_func()                          # fetch only on a real miss
            feed_cache_put(path, xml, ttl)              # failure ⇒ raises, no cache write
        return xml

    def _serve_feed(self, path, base_url, write_body=True):
        info = ROUTES[path]
        feed_url = base_url + path
        xml = _guard(lambda: self._get_or_fetch_feed(
            path, lambda: info['handler'](feed_url=feed_url)),
            shape='rss', rss_info=info, feed_url=feed_url)
        # S2-3: the feed body embeds feed_url (derived from the request Host when
        # PUBLIC_BASE_URL is unset) ⇒ never `public` without Vary in that case.
        self._send_text(200, 'application/rss+xml; charset=utf-8',
                        xml, varies_on_host=not PUBLIC_BASE_URL,
                        write_body=write_body)

    def _base_url(self):
        """Public base URL for published links: config first, else validated Host.

        S2-3: with PUBLIC_BASE_URL set it always wins.  Otherwise the value is
        taken from X-Forwarded-Host/Host — attacker-controllable — so it is
        format-validated (invalid ⇒ localhost) and the caller marks the response
        host-dependent (private + Vary).
        """
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL
        proto = _normalize_proto(self.headers.get('X-Forwarded-Proto'))
        raw = (self.headers.get('X-Forwarded-Host')
               or self.headers.get('Host') or '')
        host = raw.split(',')[0].strip()
        if not _valid_host_header(host):
            host = f'localhost:{PORT}'
        return f'{proto}://{host}'.rstrip('/')

    def _cache_age(self):
        """BR-SRV-8: path → domain → policy (no bare TTL literals).

        P2: parse with `urlparse` (the router's own rule) so an absolute-form
        request line (`GET http://host/stock/data?x=1`) resolves its path
        instead of falling through to the 300 s default domain and stamping
        real-time quotes `max-age=300`."""
        path = urlparse(self.path).path
        domain = _CACHE_AGE_DOMAINS.get(path, _DEFAULT_AGE_DOMAIN)
        return cache_policy(domain)['ttl']

    def _send_text(self, status_code, content_type, body, cache=True,
                   varies_on_host=False, write_body=True):
        # Perf: gzip large bodies when the client advertises it (compression
        # shrinks 334KB JSON quotes ~10x → network time dominates).  Raw body
        # for clients without Accept-Encoding — wire contract unchanged.
        body_bytes = body.encode('utf-8')
        gzipped = False
        if (len(body_bytes) >= config.GZIP_MIN_BYTES
                and _accepts_gzip(self.headers.get('Accept-Encoding', ''))):
            body_bytes = gzip.compress(body_bytes, config.GZIP_COMPRESSLEVEL)
            gzipped = True
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body_bytes)))
        vary_parts = []
        if gzipped:
            self.send_header('Content-Encoding', 'gzip')
        if cache:
            # S2-3: a request-derived base URL makes the body host-dependent, so
            # it must not be marked `public` (nor cached without `Vary`).
            scope = 'private' if varies_on_host else 'public'
            self.send_header('Cache-Control',
                             f'{scope}, max-age={self._cache_age()}')
            if varies_on_host:
                vary_parts.append(_BASE_URL_VARY)
        # The representation depends on Accept-Encoding whenever it could have
        # been gzipped — even for uncacheable responses, a shared cache must not
        # reuse the gzip body for a client that cannot decode it.
        if gzipped or cache:
            vary_parts.append('Accept-Encoding')
        if vary_parts:
            self.send_header('Vary', ', '.join(vary_parts))
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
            ('/cls/plate', 'Plate Detail (板块详情)', '/cls/plate?code=cls80484', False),
            ('/ths/longhu', 'THS Longhu (龙虎榜)', '/ths/longhu', False),
            ('/stock/data', 'Stock Detail (个股详情)', '/stock/data?code=sz300139', False),
            ('/stock/fundflow', 'Stock Fund Flow (资金流向)', '/stock/fundflow?code=sh600519', False),
            ('/stock/timeline', 'Stock Timeline (个股分时图)', '/stock/timeline?code=sh600519', False),
            ('/stock/f10', 'Stock F10 (个股财务概要)', '/stock/f10?code=sh600519', True),
            ('/stock/basic_info', 'Stock Basic Info (个股基本信息)', '/stock/basic_info?code=sh600519', False),
            ('/stock/announcement', 'Stock Announcement (个股公告)', '/stock/announcement?code=sh600519', False),
            ('/market/margin', 'Market Margin (融资融券)', '/market/margin?market=99', False),
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
    """HTTPServer with a fixed-size thread pool instead of per-request threads.

    Implements load shedding: when every worker is busy, new connections are
    answered with HTTP 503 instead of queuing unboundedly (which would let
    memory grow under sustained overload).
    """

    allow_reuse_address = True
    daemon_threads = True
    # BUG-P6C-03: socketserver defaults to backlog 5 — under burst connects the
    # accept queue overflows and clients retransmit ~1s later (SYN RTO).  Read
    # by server_activate() for BOTH the main port (≤MAX_INFLIGHT) and the
    # stream port (make_stream_server, ≤MAX_STREAM_CONNS=100), so one value
    # configures both; see config.LISTEN_BACKLOG.
    request_queue_size = LISTEN_BACKLOG

    def __init__(self, *args, max_workers=MAX_WORKERS, max_inflight=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        # Main port: MAX_INFLIGHT (40). Stream port passes
        # max_inflight=MAX_STREAM_CONNS+10 explicitly (P1-4) so the 100-conn
        # cap is not masked by the main-port default.
        self._max_inflight = MAX_INFLIGHT if max_inflight is None else max_inflight

    def _reject_503(self, request):
        try:
            body = b'{"error":"server busy"}'
            request.sendall(
                b'HTTP/1.1 503 Service Unavailable\r\n'
                b'Content-Type: application/json\r\n'
                b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
                b'Connection: close\r\n\r\n' + body)
        except Exception:
            pass
        finally:
            try:
                metrics.incr('http_503_total')      # BR-SRV-25: single count point
            except Exception:
                pass
            try:
                request.close()
            except Exception:
                pass

    def process_request(self, request, client_address):
        with self._inflight_lock:
            if self._inflight >= self._max_inflight:
                overloaded = True
            else:
                self._inflight += 1
                overloaded = False
        if overloaded:
            self._reject_503(request)
            return
        try:
            fut = self.executor.submit(self.process_request_thread, request, client_address)
        except Exception:
            with self._inflight_lock:
                self._inflight -= 1
            self._reject_503(request)
            return
        fut.add_done_callback(self._release_inflight)

    def _release_inflight(self, fut):
        with self._inflight_lock:
            if self._inflight > 0:
                self._inflight -= 1

    def server_close(self):
        self.executor.shutdown(wait=False)
        super().server_close()


# ── CDP init ────────────────────────────────────────────────────────────────

def init_cdp():
    """Initialize CDP engine with persistent CLS pages."""
    global cdp_engine
    try:
        log.info('[CDP] init_cdp started')
        if not ensure_chrome():
            log.error('  ✗ Chrome not available. CDP endpoints will return errors.')
            return
        cdp_engine = CDPEngine()
        # Chrome may still be starting — retry connect up to 15s
        for attempt in range(15):
            if cdp_engine.start():
                log.info(f'[CDP] connected on attempt {attempt+1}')
                break
            time.sleep(1)
        else:
            log.error('  ✗ Failed to connect to Chrome CDP after 15s.')
            return
        cdp_engine.add_page('cls_finance', 'https://www.cls.cn/finance')
        cdp_engine.add_page('cls_quotation', 'https://www.cls.cn/quotation')
        nav_names = stock_nav_page_names()
        for name in nav_names:
            cdp_engine.add_page(name, 'https://www.cls.cn/stock?code=sz300139', heartbeat=False)
        log.info(f'  ✓ CDP engine ready — finance, quotation, {len(nav_names)} stock pages')
        from . import config
        config.cdp_engine = cdp_engine
    except Exception as e:
        import traceback
        log.error(f'  ✗ init_cdp error: {e}')
        traceback.print_exc()


# ── CDP memory watchdog ─────────────────────────────────────────────────────

def _cdp_memory_watchdog():
    """Periodically restart Chrome to reclaim V8/renderer memory.

    `_maybe_reconnect` (in cdp_engine) only restarts Chrome after ~30 stock
    navigations. Under low traffic navigation volume rarely reaches that, so
    renderers grow over days and never release memory. This thread forces a
    `full_chrome_restart()` on a wall-clock interval regardless of traffic.

    The skip decision (trading-hours avoidance + throttle + restart window +
    not-ready) is centralized in cdp_engine.watchdog_restart_skip_reason()
    (BR-SRV-26 / ADR-012).
    """
    while True:
        time.sleep(CDP_RESTART_INTERVAL)
        try:
            reason = watchdog_restart_skip_reason()
            if reason is not None:
                log.info('  [CDP] watchdog: restart skipped (%s)', reason)
                continue                        # defer one cycle, no accumulation
            log.info('  [CDP] watchdog: restarting Chrome to reclaim renderer memory')
            full_chrome_restart()
        except Exception as e:
            log.error(f'  [CDP] watchdog error: {e}')


def main():
    from .utils import setup_logging
    setup_logging()

    def _signal_handler(signum, frame):
        log.info(f'[exit] received signal {signum} ({signal.Signals(signum).name})')
        sys.exit(0)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    @atexit.register
    def _shutdown():
        if cdp_engine:
            cdp_engine.shutdown()

    from .utils import warm_jin10_headers
    threading.Thread(target=warm_jin10_headers, daemon=True).start()
    # Pre-warm the upstream transport (DNS + one pooled connection per SSE
    # hot-path host) so the first real refresh of a cold process is not fully
    # cold.  Daemon thread: it never delays startup or /healthz, and
    # `warm_transport` is total/best-effort, so a dead upstream is silent.
    threading.Thread(target=warm_transport, daemon=True).start()
    threading.Thread(target=init_cdp, daemon=True).start()
    threading.Thread(target=_cdp_memory_watchdog, daemon=True).start()
    threading.Thread(target=_fundflow_prefetch_loop, daemon=True).start()
    threading.Thread(target=_timeline_prefetch_loop, daemon=True).start()
    threading.Thread(target=_f10_prefetch_loop, daemon=True).start()
    threading.Thread(target=_announcement_prefetch_loop, daemon=True).start()
    from .stream import push_loop, run_stream_server
    threading.Thread(target=push_loop, daemon=True).start()
    threading.Thread(target=run_stream_server, daemon=True).start()

    log.info(f'China Finance RSS Bridge running on http://localhost:{PORT}')
    log.info(f'Cache TTL: {cache_policy("feed")["ttl"]}s | Timeout: {REQUEST_TIMEOUT}s')
    log.info('Available feeds:')
    for path, info in ROUTES.items():
        log.info(f'  http://localhost:{PORT}{path}  — {info["name"]}')
    log.info(f'\nUtilities:')
    log.info(f'  http://localhost:{PORT}/finance/market  — Finance Market Data (JSON, needs Chrome CDP)')
    log.info(f'  http://localhost:{PORT}/finance/timeline  — Finance Timeline (JSON, needs Chrome CDP)')
    log.info(f'  http://localhost:{PORT}/quotation/market  — Quotation Market Data (JSON, needs Chrome CDP)')
    log.info(f'  http://localhost:{PORT}/market/timeline  — Market Index Timeline (JSON, needs Chrome CDP)')
    log.info(f'  http://localhost:{PORT}/cls/hotplate  — Hotplate Data (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/cls/plate?code=cls80484  — Plate Detail (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/stock/data  — Stock Detail Data (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/stock/fundflow  — Stock Fund Flow (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/stock/timeline  — Stock Timeline (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/stock/f10  — Stock F10 Financial Summary (JSON, needs Chrome CDP)')
    log.info(f'  http://localhost:{PORT}/stock/basic_info  — Stock Basic Info (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/stock/announcement  — Stock Announcement (JSON, no CDP needed)')
    log.info(f'  http://localhost:{PORT}/market/margin  — Market Margin (融资融券, JSON, no CDP needed)')
    from .config import STREAM_PORT
    log.info(f'\nStream push (SSE, port {STREAM_PORT}):')
    log.info(f'  POST   http://localhost:{STREAM_PORT}/stream/subscriptions  — create subscription group')
    log.info(f'  PATCH  http://localhost:{STREAM_PORT}/stream/subscriptions/<sid> — add/remove codes')
    log.info(f'  GET    http://localhost:{STREAM_PORT}/stream/quote/<sid>    — SSE stream (event: quote)')
    log.info(f'  http://localhost:{PORT}/opml.xml  — OPML subscription list')
    log.info(f'  http://localhost:{PORT}/healthz?check=1  — Source health check')
    log.info(f'Visit http://localhost:{PORT}/ for the web index.\n')

    server = BoundedThreadPoolServer(('0.0.0.0', PORT), RSSHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
