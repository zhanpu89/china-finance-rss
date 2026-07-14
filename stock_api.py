"""Stock data APIs: fundflow, timeline, F10, basic_info, stock detail.

All CDP-based endpoints use `config.cdp_engine` (set by server.py init).
"""

import json
import threading
from time import sleep, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import (
    REQUEST_TIMEOUT, VALID_STOCK_CODE,
    _MAX_CACHE_AGE, _MAX_BATCH_SIZE,
    _STOCK_EXPECTED_KEYS, _F10_EXPECTED_KEYS,
    _FUNDFLOW_BASE_URL, _FUNDFLOW_HEADERS,
    _TIMELINE_BASE_URL, _TIMELINE_HEADERS,
    _F10_BASE_URL, _F10_HEADERS,
    _ANNOUNCEMENT_BASE_URL, _ANNOUNCEMENT_HEADERS,
    _BASIC_INFO_BASE_URL, _BASIC_INFO_HEADERS,
    _STOCK_DETAIL_BASE_URL, _STOCK_DETAIL_HEADERS,
    _COMPANY_INFO_BASE_URL, _COMPANY_INFO_HEADERS,
    _FUNDFLOW_POOL_REFRESH, _FUNDFLOW_MAX_POOL,
    _TIMELINE_POOL_REFRESH, _TIMELINE_MAX_POOL,
    _F10_POOL_REFRESH, _F10_MAX_POOL,
    _BASIC_INFO_POOL_REFRESH, _BASIC_INFO_MAX_POOL,
    _ANNOUNCEMENT_POOL_REFRESH, _ANNOUNCEMENT_MAX_POOL,
    cdp_engine, _china_trading_ttl,
)
from cache import fetch_json, _fill_missing
from utils import cls_sign_params


def _announcement_url(stock_code):
    """Build signed announcement API URL — requires CLS sign."""
    params = {
        'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
        'secu_code': stock_code,
    }
    params['sign'] = cls_sign_params(params)
    return f'{_ANNOUNCEMENT_BASE_URL}?{urlencode(params)}'


# ── Fund Flow ──────────────────────────────────────────────────────────────

_fundflow_cache = {}
_fundflow_cache_ts = {}
_fundflow_pool = {}
_fundflow_cache_lock = threading.Lock()


def fetch_cls_fundflow(stock_code):
    """Fetch fund flow — REST first, CDP evaluate_fetch fallback."""
    url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _FUNDFLOW_HEADERS, ttl=15))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
    return None


def _fundflow_direct_fetch(stock_code):
    """Fetch fund flow via CDP browser context (anti-ban), REST fallback."""
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
            if result and isinstance(result, dict) and result.get('error'):
                print(f'[fundflow] CDP fetch error for {stock_code}: {result["error"]}')
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
    """Fund Flow Data (资金流向) — REST-based, batch supported."""
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    if not codes:
        return {}

    now = time()
    with _fundflow_cache_lock:
        for code in codes:
            _fundflow_pool[code] = now
        if len(_fundflow_pool) > _FUNDFLOW_MAX_POOL:
            excess = sorted(_fundflow_pool, key=_fundflow_pool.get)[:len(_fundflow_pool) - _FUNDFLOW_MAX_POOL]
            for code in excess:
                del _fundflow_pool[code]
                _fundflow_cache.pop(code, None)
                _fundflow_cache_ts.pop(code, None)

    result = {}
    missing = []
    with _fundflow_cache_lock:
        for code in codes:
            cached = _fundflow_cache.get(code)
            if cached is not None:
                ts = _fundflow_cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    for code in missing:
        data = fetch_cls_fundflow(code)
        if data:
            with _fundflow_cache_lock:
                _fundflow_cache[code] = data
                _fundflow_cache_ts[code] = time()
            result[code] = data
        else:
            result[code] = None

    return result


def _fundflow_prefetch_loop():
    """Background thread: refresh fund flow for all auto-registered stocks."""
    while True:
        try:
            ttl, _ = _china_trading_ttl()
            interval = max(_FUNDFLOW_POOL_REFRESH, ttl)
            sleep(interval)
            with _fundflow_cache_lock:
                codes = list(_fundflow_pool.keys())
            if not codes:
                continue
            for code in codes:
                data = _fundflow_direct_fetch(code)
                if data:
                    with _fundflow_cache_lock:
                        _fundflow_cache[code] = data
                        _fundflow_cache_ts[code] = time()
        except Exception as e:
            print(f'[fundflow] prefetch error: {e}')


# ── Timeline ───────────────────────────────────────────────────────────────

_timeline_cache = {}
_timeline_cache_ts = {}
_timeline_pool = {}
_timeline_cache_lock = threading.Lock()


def fetch_cls_timeline(stock_code):
    """Fetch stock timeline — REST first, CDP evaluate_fetch fallback."""
    url = f'{_TIMELINE_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _TIMELINE_HEADERS, ttl=15))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
    return None


def _timeline_direct_fetch(stock_code):
    """Fetch timeline via CDP browser context (anti-ban), REST fallback."""
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_fundflow')
        if page:
            url = f'{_TIMELINE_BASE_URL}?secu_code={stock_code}'
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
            if result and isinstance(result, dict) and result.get('error'):
                print(f'[timeline] CDP fetch error for {stock_code}: {result["error"]}')
    req = Request(f'{_TIMELINE_BASE_URL}?secu_code={stock_code}',
                   headers=_TIMELINE_HEADERS)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if raw.get('code') == 200:
                return raw.get('data')
    except Exception:
        pass
    return None


def handle_cls_timeline(codes):
    """Stock Timeline Data (分时图) — REST-based, batch supported."""
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    if not codes:
        return {}

    now = time()
    with _timeline_cache_lock:
        for code in codes:
            _timeline_pool[code] = now
        if len(_timeline_pool) > _TIMELINE_MAX_POOL:
            excess = sorted(_timeline_pool, key=_timeline_pool.get)[:len(_timeline_pool) - _TIMELINE_MAX_POOL]
            for code in excess:
                del _timeline_pool[code]
                _timeline_cache.pop(code, None)
                _timeline_cache_ts.pop(code, None)

    result = {}
    missing = []
    with _timeline_cache_lock:
        for code in codes:
            cached = _timeline_cache.get(code)
            if cached is not None:
                ts = _timeline_cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    for code in missing:
        data = fetch_cls_timeline(code)
        if data:
            with _timeline_cache_lock:
                _timeline_cache[code] = data
                _timeline_cache_ts[code] = time()
            result[code] = data
        else:
            result[code] = None

    return result


def _timeline_prefetch_loop():
    """Background thread: refresh timeline for all auto-registered stocks."""
    while True:
        try:
            ttl, _ = _china_trading_ttl()
            interval = max(_TIMELINE_POOL_REFRESH, ttl)
            sleep(interval)
            with _timeline_cache_lock:
                codes = list(_timeline_pool.keys())
            if not codes:
                continue
            for code in codes:
                data = _timeline_direct_fetch(code)
                if data:
                    with _timeline_cache_lock:
                        _timeline_cache[code] = data
                        _timeline_cache_ts[code] = time()
        except Exception as e:
            print(f'[timeline] prefetch error: {e}')


# ── F10 (Financial Summary) ────────────────────────────────────────────────

_f10_cache = {}
_f10_cache_ts = {}
_f10_pool = {}
_f10_cache_lock = threading.Lock()


def _navigate_f10(page, stock_code, deadline):
    """Helper: single-shot navigate_stock with F10 tab click.

    Unlike the old retry loop, this calls navigate_stock once with the
    full remaining time. navigate_stock internally uses a blocking lock
    (fair queuing) so concurrent requests wait their turn without wasting
    CPU on retries.
    """
    remaining = deadline - time()
    if remaining < 2:
        return False
    return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)


def fetch_cls_f10(stock_code, deadline=None):
    """Fetch F10 company info — CDP navigation with fast cache check.

    Returns company_info data dict: {basic_info, ipo_info, ...}
    matching the original CDP capture format.
    """
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_f10') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = deadline or time() + 10
            if not _navigate_f10(page, stock_code, deadline):
                return None
            data = page.get_data()
            r = {}
            _fill_missing(r, data, _F10_EXPECTED_KEYS)
            if r:
                return r.get('stock_company_info')
    return None


def _f10_direct_fetch(stock_code, deadline=None):
    """Fetch F10 company info — CDP navigation.

    Used by prefetch loop.
    """
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_f10') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = deadline or time() + 10
            if not _navigate_f10(page, stock_code, deadline):
                return None
            data = page.get_data()
            r = {}
            _fill_missing(r, data, _F10_EXPECTED_KEYS)
            if r:
                return r.get('stock_company_info')
    return None


def handle_cls_f10(codes):
    """Stock F10 Financial Summary — CDP navigation-based, batch supported."""
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    if not codes:
        return {}

    result = {}
    valid = []
    for code in codes:
        if VALID_STOCK_CODE.match(code):
            valid.append(code)
        else:
            result[code] = None
    codes = valid

    now = time()
    with _f10_cache_lock:
        for code in codes:
            _f10_pool[code] = now
        if len(_f10_pool) > _F10_MAX_POOL:
            excess = sorted(_f10_pool, key=_f10_pool.get)[:len(_f10_pool) - _F10_MAX_POOL]
            for code in excess:
                del _f10_pool[code]
                _f10_cache.pop(code, None)
                _f10_cache_ts.pop(code, None)

    missing = []
    with _f10_cache_lock:
        for code in codes:
            cached = _f10_cache.get(code)
            if cached is not None:
                ts = _f10_cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    batch_deadline = time() + 60
    for code in missing:
        if time() > batch_deadline:
            result[code] = None
            continue
        data = fetch_cls_f10(code, deadline=batch_deadline)
        if data:
            with _f10_cache_lock:
                _f10_cache[code] = data
                _f10_cache_ts[code] = time()
            _populate_sector_from_f10(data, code)
            result[code] = data
        else:
            result[code] = None

    return result


def _f10_prefetch_loop():
    """Background thread: refresh F10 for all auto-registered stocks."""
    while True:
        try:
            ttl, _ = _china_trading_ttl()
            interval = max(_F10_POOL_REFRESH, ttl)
            sleep(interval)
            with _f10_cache_lock:
                codes = list(_f10_pool.keys())
            if not codes:
                continue
            for code in codes:
                data = _f10_direct_fetch(code, deadline=time() + 4)
                if data:
                    with _f10_cache_lock:
                        _f10_cache[code] = data
                        _f10_cache_ts[code] = time()
                    _populate_sector_from_f10(data, code)
        except Exception as e:
            print(f'[f10] prefetch error: {e}')


# ── Basic Info ─────────────────────────────────────────────────────────────

_basic_info_cache = {}
_basic_info_cache_ts = {}
_basic_info_pool = {}
_basic_info_cache_lock = threading.Lock()

# Shared sector name cache (industry rarely changes, so long TTL is safe)
_sector_cache = {}
_sector_cache_lock = threading.Lock()


def _populate_sector_from_f10(data, code):
    """Extract sector from F10 company_info data and populate shared cache."""
    if isinstance(data, dict):
        raw = data.get('result') or data
        bi = raw.get('basic_info') or {}
        # company_info API uses SecuCode (camelCase)
        if isinstance(bi, dict):
            stored_code = bi.get('SecuCode') or bi.get('secu_code') or ''
            if stored_code.upper() == code.upper():
                industry = bi.get('IndustryName') or ''
                if industry:
                    sector = industry.split('-')[0]
                    with _sector_cache_lock:
                        _sector_cache[code] = {'sector': sector, 'ts': time()}


def _extract_sector_name(stock_code):
    """Get sector name for a stock code from shared cache or CDP pages.

    Non-blocking: only reads already-cached data, never triggers navigation.
    Returns sector string (e.g. '食品饮料') or None.
    """
    # 1) Shared Python cache (fastest, cross-page)
    with _sector_cache_lock:
        cached = _sector_cache.get(stock_code)
        if cached and time() - cached['ts'] < 3600:
            return cached['sector']

    # 2) CDP page cache — check any page that may have company_info
    sector = None
    if cdp_engine and cdp_engine.ready:
        for name in ('cls_stock_f10', 'cls_stock_basic_info', 'cls_stock'):
            page = cdp_engine.get_page(name)
            if page:
                try:
                    data = page.get_data()
                    ci = data.get('stock_company_info')
                    if isinstance(ci, dict):
                        bi = ci.get('basic_info') or {}
                        # company_info API uses SecuCode (camelCase)
                        stored_code = bi.get('SecuCode') or bi.get('secu_code') or ''
                        if stored_code.upper() != stock_code.upper():
                            continue
                        industry = bi.get('IndustryName') or ''
                        if industry:
                            sector = industry.split('-')[0]
                            break
                except Exception:
                    pass

    if sector:
        with _sector_cache_lock:
            _sector_cache[stock_code] = {'sector': sector, 'ts': time()}
    return sector


def _navigate_basic_info(page, stock_code, deadline):
    """Helper: single-shot navigate_stock for basic info.

    Single attempt with full remaining time — fair queuing in
    navigate_stock avoids retry waste under concurrent load.
    """
    remaining = deadline - time()
    if remaining < 2:
        return False
    return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)


def fetch_cls_basic_info(stock_code, deadline=None):
    """Fetch basic info — REST first, shared cache for sector.

    Priority:
      1) REST API for basic pricing data (<100ms)
      2) Shared sector cache + CDP page cache (non-blocking, <1ms)
      3) CDP full navigation (3-5s) if REST fails

    Returns dict: {code, msg, data, [sector_name]} matching original CDP format.
    """
    global cdp_engine
    result = None

    # 1) REST API — basic pricing & identity data
    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _BASIC_INFO_HEADERS, ttl=_MAX_CACHE_AGE))
        if raw.get('code') == 200:
            result = raw
    except Exception:
        pass

    # 2) Sector name — from shared cache or CDP pages (non-blocking)
    sector = _extract_sector_name(stock_code)
    if sector:
        if result is None:
            result = {'code': 200, 'msg': 'success', 'data': {}}
        elif not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector

    if result is not None:
        return result

    # 3) CDP navigation fallback (full page load, 3-5s)
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_basic_info') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = deadline or time() + 10
            if not _navigate_basic_info(page, stock_code, deadline):
                return None
            data = page.get_data()
            result = data.get('basic_info')
            ci = data.get('stock_company_info')
            if isinstance(ci, dict):
                ci_bi = ci.get('basic_info', {})
                sector = ci_bi.get('IndustryName')
                if sector:
                    if result is None:
                        result = {}
                    result['sector_name'] = sector.split('-')[0]
                    _populate_sector_from_f10(ci, stock_code)
            return result
    return None


def handle_cls_basic_infos(codes):
    """Stock Basic Info — CDP navigation-based, batch supported."""
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    if not codes:
        return {}

    result = {}
    valid = []
    for code in codes:
        if VALID_STOCK_CODE.match(code):
            valid.append(code)
        else:
            result[code] = None
    codes = valid

    now = time()
    with _basic_info_cache_lock:
        for code in codes:
            _basic_info_pool[code] = now
        if len(_basic_info_pool) > _BASIC_INFO_MAX_POOL:
            excess = sorted(_basic_info_pool, key=_basic_info_pool.get)[:len(_basic_info_pool) - _BASIC_INFO_MAX_POOL]
            for code in excess:
                del _basic_info_pool[code]
                _basic_info_cache.pop(code, None)
                _basic_info_cache_ts.pop(code, None)

    missing = []
    with _basic_info_cache_lock:
        for code in codes:
            cached = _basic_info_cache.get(code)
            if cached is not None:
                ts = _basic_info_cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    batch_deadline = time() + 60
    for code in missing:
        if time() > batch_deadline:
            result[code] = None
            continue
        data = fetch_cls_basic_info(code, deadline=batch_deadline)
        if data:
            with _basic_info_cache_lock:
                _basic_info_cache[code] = data
                _basic_info_cache_ts[code] = time()
            result[code] = data
        else:
            result[code] = None

    return result


def _basic_info_prefetch_loop():
    """Background thread: refresh basic info for all auto-registered stocks."""
    while True:
        try:
            ttl, _ = _china_trading_ttl()
            interval = max(_BASIC_INFO_POOL_REFRESH, ttl)
            sleep(interval)
            with _basic_info_cache_lock:
                codes = list(_basic_info_pool.keys())
            if not codes:
                continue
            for code in codes:
                data = fetch_cls_basic_info(code, deadline=time() + 4)
                if data:
                    with _basic_info_cache_lock:
                        _basic_info_cache[code] = data
                        _basic_info_cache_ts[code] = time()
        except Exception as e:
            print(f'[basic_info] prefetch error: {e}')


# ── Announcement (公告) ─────────────────────────────────────────────────────

_announcement_cache = {}
_announcement_cache_ts = {}
_announcement_pool = {}
_announcement_cache_lock = threading.Lock()


def fetch_cls_announcement(stock_code):
    """Fetch stock announcements — REST first (with CLS sign), CDP evaluate_fetch fallback."""
    url = _announcement_url(stock_code)
    try:
        raw = json.loads(fetch_json(url, _ANNOUNCEMENT_HEADERS, ttl=15))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_announcement')
        if page:
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
    return None


def _announcement_direct_fetch(stock_code):
    """Fetch announcements via CDP browser context (anti-ban), REST fallback."""
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_announcement')
        if page:
            url = _announcement_url(stock_code)
            result = page.evaluate_fetch(url, timeout=15)
            if result and isinstance(result, dict) and result.get('code') == 200:
                return result.get('data')
            if result and isinstance(result, dict) and result.get('error'):
                print(f'[announcement] CDP fetch error for {stock_code}: {result["error"]}')
    req = Request(_announcement_url(stock_code),
                   headers=_ANNOUNCEMENT_HEADERS)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if raw.get('code') == 200:
                return raw.get('data')
    except Exception:
        pass
    return None


def handle_cls_announcement(codes):
    """Stock Announcement Data (公告) — REST-based, batch supported."""
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    if not codes:
        return {}

    now = time()
    with _announcement_cache_lock:
        for code in codes:
            _announcement_pool[code] = now
        if len(_announcement_pool) > _ANNOUNCEMENT_MAX_POOL:
            excess = sorted(_announcement_pool, key=_announcement_pool.get)[:len(_announcement_pool) - _ANNOUNCEMENT_MAX_POOL]
            for code in excess:
                del _announcement_pool[code]
                _announcement_cache.pop(code, None)
                _announcement_cache_ts.pop(code, None)

    result = {}
    missing = []
    with _announcement_cache_lock:
        for code in codes:
            cached = _announcement_cache.get(code)
            if cached is not None:
                ts = _announcement_cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    for code in missing:
        data = fetch_cls_announcement(code)
        if data:
            with _announcement_cache_lock:
                _announcement_cache[code] = data
                _announcement_cache_ts[code] = time()
            result[code] = data
        else:
            result[code] = None

    return result


def _announcement_prefetch_loop():
    """Background thread: refresh announcements for all auto-registered stocks."""
    while True:
        try:
            ttl, _ = _china_trading_ttl()
            interval = max(_ANNOUNCEMENT_POOL_REFRESH, ttl)
            sleep(interval)
            with _announcement_cache_lock:
                codes = list(_announcement_pool.keys())
            if not codes:
                continue
            for code in codes:
                data = _announcement_direct_fetch(code)
                if data:
                    with _announcement_cache_lock:
                        _announcement_cache[code] = data
                        _announcement_cache_ts[code] = time()
        except Exception as e:
            print(f'[announcement] prefetch error: {e}')


# ── Stock Detail ───────────────────────────────────────────────────────────

def handle_cls_stock(stock_code, timeout=30):
    """CLS Stock Detail Data — REST first, CDP fallback per component.

    Components:
      - stock_detail: REST API directly (<100ms)
      - stock_plate:   evaluate_fetch from browser (<500ms)
      - stock_announcement: REST API directly (already signed)
      - articles:      CDP page navigation (only if needed)
    """
    result = {}
    global cdp_engine

    # 1) stock_detail — REST direct
    try:
        url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={stock_code}'
        raw = json.loads(fetch_json(url, _STOCK_DETAIL_HEADERS, ttl=_MAX_CACHE_AGE))
        if raw.get('code') == 200:
            result['stock_detail'] = raw.get('data')
    except Exception:
        pass

    # 2) stock_announcement — REST direct (already signed in fetch_cls_announcement)
    ann = fetch_cls_announcement([stock_code])
    if ann and stock_code in ann:
        result['stock_announcement'] = ann[stock_code]

    # 3) stock_plate — evaluate_fetch from browser (no navigation, just a fetch)
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_data') or cdp_engine.get_page('cls_stock')
        if page:
            try:
                result_plate = page.evaluate_fetch(
                    f'https://x-quote.cls.cn/stock/assoc_plate?secu_code={stock_code}',
                    timeout=6)
                if result_plate and isinstance(result_plate, dict):
                    if 'data' in result_plate:
                        result['stock_plate'] = result_plate['data']
                    elif 'code' not in result_plate or result_plate.get('code') in (200, None, ''):
                        result['stock_plate'] = result_plate
            except Exception:
                pass

    # 4) articles — CDP page navigation (index page, no other source)
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_data') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = time() + min(timeout, 8)
            ok = False
            while time() < deadline:
                if page.navigate_stock(stock_code, timeout=min(timeout, 6), tabs=()):
                    ok = True
                    break
                sleep(0.5)
            if ok:
                data = page.get_data()
                for k in ('articles', 'stock_plate', 'stock_detail', 'stock_announcement'):
                    if k not in result and data.get(k) is not None:
                        result[k] = data[k]

    return result


def handle_cls_stock_batch(codes):
    """Batch version of handle_cls_stock — returns {code: data, ...}."""
    result = {}
    for code in codes:
        if not VALID_STOCK_CODE.match(code):
            result[code] = None
        else:
            result[code] = handle_cls_stock(code)
    return result
