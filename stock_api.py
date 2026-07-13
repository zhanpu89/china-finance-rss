"""Stock data APIs: fundflow, timeline, F10, basic_info, stock detail.

All CDP-based endpoints use `config.cdp_engine` (set by server.py init).
"""

import json
import threading
from time import sleep, time
from urllib.request import Request, urlopen

from config import (
    REQUEST_TIMEOUT, VALID_STOCK_CODE,
    _MAX_CACHE_AGE, _MAX_BATCH_SIZE,
    _STOCK_EXPECTED_KEYS, _F10_EXPECTED_KEYS,
    _FUNDFLOW_BASE_URL, _FUNDFLOW_HEADERS,
    _TIMELINE_BASE_URL, _TIMELINE_HEADERS,
    _F10_BASE_URL, _F10_HEADERS,
    _FUNDFLOW_POOL_REFRESH, _FUNDFLOW_MAX_POOL,
    _TIMELINE_POOL_REFRESH, _TIMELINE_MAX_POOL,
    _F10_POOL_REFRESH, _F10_MAX_POOL,
    _BASIC_INFO_POOL_REFRESH, _BASIC_INFO_MAX_POOL,
    cdp_engine, _china_trading_ttl,
)
from cache import fetch_json, _fill_missing


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
    """Helper: retry navigate_stock with F10 tab click until deadline."""
    ok = False
    while time() < deadline:
        timeout = min(8, deadline - time() - 0.5)
        if timeout < 1:
            break
        if page.navigate_stock(stock_code, tabs=('f10',), timeout=timeout):
            ok = True
            break
        sleep(0.5)
    return ok


def fetch_cls_f10(stock_code, deadline=None):
    """Fetch company info — CDP page navigation (clicks F10 tab)."""
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_f10') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = deadline or time() + 10
            if not _navigate_f10(page, stock_code, deadline):
                return None
            data = page.get_data()
            result = {}
            _fill_missing(result, data, _F10_EXPECTED_KEYS)
            if result:
                return result.get('stock_company_info')
    return None


def _f10_direct_fetch(stock_code, deadline=None):
    """Fetch company info via CDP page navigation (anti-ban)."""
    global cdp_engine
    if cdp_engine and cdp_engine.ready:
        page = cdp_engine.get_page('cls_stock_f10') or cdp_engine.get_page('cls_stock')
        if page:
            deadline = deadline or time() + 10
            if not _navigate_f10(page, stock_code, deadline):
                return None
            data = page.get_data()
            result = {}
            _fill_missing(result, data, _F10_EXPECTED_KEYS)
            if result:
                return result.get('stock_company_info')
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

    batch_deadline = time() + 25
    missing_count = len(missing)
    for i, code in enumerate(missing):
        remaining = batch_deadline - time()
        if remaining <= 0:
            result[code] = None
            continue
        per_stock = remaining / (missing_count - i)
        per_stock = max(5, min(8, per_stock))
        data = fetch_cls_f10(code, deadline=time() + per_stock)
        if data:
            with _f10_cache_lock:
                _f10_cache[code] = data
                _f10_cache_ts[code] = time()
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
        except Exception as e:
            print(f'[f10] prefetch error: {e}')


# ── Basic Info ─────────────────────────────────────────────────────────────

_basic_info_cache = {}
_basic_info_cache_ts = {}
_basic_info_pool = {}
_basic_info_cache_lock = threading.Lock()


def _navigate_basic_info(page, stock_code, deadline):
    """Helper: retry navigate_stock for basic info until deadline."""
    ok = False
    while time() < deadline:
        timeout = min(8, deadline - time() - 0.5)
        if timeout < 1:
            break
        if page.navigate_stock(stock_code, tabs=('f10',), timeout=timeout):
            ok = True
            break
        sleep(0.5)
    return ok


def fetch_cls_basic_info(stock_code, deadline=None):
    """Fetch basic info via CDP page navigation with F10 tab click.

    Returns basic_info merged with sector_name (申万一级行业).
    """
    global cdp_engine
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

    batch_deadline = time() + 25
    missing_count = len(missing)
    for i, code in enumerate(missing):
        remaining = batch_deadline - time()
        if remaining <= 0:
            result[code] = None
            continue
        per_stock = remaining / (missing_count - i)
        per_stock = max(5, min(8, per_stock))
        data = fetch_cls_basic_info(code, deadline=time() + per_stock)
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


# ── Stock Detail ───────────────────────────────────────────────────────────

def handle_cls_stock(stock_code, timeout=30):
    """CLS Stock Detail Data (财联社个股详情) via persistent CDP page."""
    global cdp_engine
    if not cdp_engine or not cdp_engine.ready:
        return {'error': 'Chrome CDP not available. See README.'}
    page = cdp_engine.get_page('cls_stock_data')
    if not page:
        page = cdp_engine.get_page('cls_stock')
    if not page:
        return {'error': 'Stock page not initialized.'}
    deadline = time() + min(timeout, 10)
    ok = False
    while time() < deadline:
        if page.navigate_stock(stock_code, timeout=min(timeout, 8), tabs=()):
            ok = True
            break
        sleep(0.5)
    if not ok:
        return {'error': f'Failed to navigate to stock {stock_code}'}
    data = page.get_data()
    data.pop('stock_quote', None)
    data.pop('basic_info', None)
    data.pop('timeline', None)
    data.pop('stock_f10', None)
    data.pop('stock_company_info', None)
    result = {}
    _fill_missing(result, data, _STOCK_EXPECTED_KEYS)
    return result
