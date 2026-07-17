"""Stock data APIs: fundflow, timeline, F10, basic_info, stock detail.

All CDP-based endpoints use `config.cdp_engine` (set by server.py init).
"""

import json
import os
import threading
from time import sleep, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config
from config import (
    REQUEST_TIMEOUT, VALID_STOCK_CODE,
    _MAX_CACHE_AGE, _MAX_BATCH_SIZE,
    _F10_EXPECTED_KEYS,
    _FUNDFLOW_BASE_URL, _FUNDFLOW_HEADERS,
    _TIMELINE_BASE_URL, _TIMELINE_HEADERS,
    _F10_BASE_URL, _F10_HEADERS,
    _ANNOUNCEMENT_BASE_URL, _ANNOUNCEMENT_HEADERS,
    _BASIC_INFO_BASE_URL, _BASIC_INFO_HEADERS,
    _STOCK_DETAIL_BASE_URL, _STOCK_DETAIL_HEADERS,
    _FUNDFLOW_POOL_REFRESH, _FUNDFLOW_MAX_POOL,
    _TIMELINE_POOL_REFRESH, _TIMELINE_MAX_POOL,
    _F10_POOL_REFRESH, _F10_MAX_POOL,
    _BASIC_INFO_MAX_POOL,
    _ANNOUNCEMENT_POOL_REFRESH, _ANNOUNCEMENT_MAX_POOL,
    _china_trading_ttl,
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


def _evaluate_fetch_any(url, timeout=8):
    """Try evaluate_fetch on any available page. Returns parsed dict or None."""
    if not config.cdp_engine or not config.cdp_engine.ready:
        return None
    deadline = time() + timeout
    for name in _STOCK_NAV_PAGES[:3] + ('cls_finance', 'cls_quotation'):
        if time() >= deadline:
            break
        page = config.cdp_engine.get_page(name)
        if not page:
            continue
        try:
            result = page.evaluate_fetch(url, timeout=min(deadline - time(), 2))
            if result and isinstance(result, dict):
                return result
        except Exception:
            pass
    return None


def fetch_cls_fundflow(stock_code):
    """Fetch fund flow — REST first, CDP evaluate_fetch fallback."""
    url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _FUNDFLOW_HEADERS, ttl=15))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    result = _evaluate_fetch_any(url)
    if result and result.get('code') == 200:
        return result.get('data')
    return None


def _fundflow_direct_fetch(stock_code):
    """Fetch fund flow via CDP browser context (anti-ban), REST fallback."""
    result = _evaluate_fetch_any(f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}')
    if result and result.get('code') == 200:
        return result.get('data')
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
    result = _evaluate_fetch_any(url)
    if result and result.get('code') == 200:
        return result.get('data')
    return None


def _timeline_direct_fetch(stock_code):
    """Fetch timeline via CDP browser context (anti-ban), REST fallback."""
    result = _evaluate_fetch_any(f'{_TIMELINE_BASE_URL}?secu_code={stock_code}')
    if result and result.get('code') == 200:
        return result.get('data')
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
    """Navigate stock — skip pages that are busy beyond a short wait."""
    remaining = deadline - time()
    if remaining < 2:
        return False
    try:
        if not page._navigate_lock.acquire(timeout=0.5):
            return False
        page._navigate_lock.release()
    except AttributeError:
        return False
    return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)


def _company_info_matches(ci, stock_code):
    """Check if company_info data belongs to the requested stock."""
    if not isinstance(ci, dict):
        return False
    bi = ci.get('basic_info') or {}
    secu = bi.get('SecuCode', '')
    return secu.upper() == stock_code.upper()


def _iter_nav_pages():
    """Yield CDP stock navigation pages that are available."""
    if not config.cdp_engine or not config.cdp_engine.ready:
        return
    for name in _STOCK_NAV_PAGES:
        page = config.cdp_engine.get_page(name)
        if page:
            yield page


def fetch_cls_f10(stock_code, deadline=None):
    """Fetch F10 company info — CDP navigation with fast cache check.

    Returns company_info data dict: {basic_info, ipo_info, ...}
    matching the original CDP capture format.
    """
    if config.cdp_engine and config.cdp_engine.ready:
        d = deadline or time() + 10
        for page in _iter_nav_pages():
            if time() >= d - 1:
                break
            if _navigate_f10(page, stock_code, d):
                data = page.get_data()
                r = {}
                _fill_missing(r, data, _F10_EXPECTED_KEYS)
                if r:
                    ci = r.get('stock_company_info')
                    if _company_info_matches(ci, stock_code):
                        return ci
    return None


def _f10_direct_fetch(stock_code, deadline=None):
    """Fetch F10 company info — CDP navigation.

    Used by prefetch loop.
    """
    if config.cdp_engine and config.cdp_engine.ready:
        d = deadline or time() + 10
        for page in _iter_nav_pages():
            if time() >= d - 1:
                break
            if _navigate_f10(page, stock_code, d):
                data = page.get_data()
                r = {}
                _fill_missing(r, data, _F10_EXPECTED_KEYS)
                if r:
                    ci = r.get('stock_company_info')
                    if _company_info_matches(ci, stock_code):
                        return ci
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

# Shared sector name cache (industry rarely changes, long TTL + file persistence)
_SECTOR_CACHE_FILE = 'data/sector_cache.json'
_sector_cache = {}
_sector_cache_lock = threading.Lock()


def _load_sector_cache():
    """Load persisted sector cache from disk."""
    try:
        with open(_SECTOR_CACHE_FILE) as f:
            data = json.load(f)
            count = 0
            with _sector_cache_lock:
                for k, v in data.items():
                    if isinstance(v, dict) and 'sector' in v:
                        _sector_cache[k] = v
                        count += 1
            if count:
                print(f'[sector] loaded {count} entries from {_SECTOR_CACHE_FILE}')
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f'[sector] load error: {e}')


def _save_sector_cache():
    """Persist sector cache to disk asynchronously."""
    try:
        with _sector_cache_lock:
            data = dict(_sector_cache)
        os.makedirs(os.path.dirname(_SECTOR_CACHE_FILE), exist_ok=True)
        with open(_SECTOR_CACHE_FILE, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f'[sector] save error: {e}')


_load_sector_cache()


def _populate_sector_from_f10(data, code):
    """Extract sector from F10 company_info data and populate shared cache."""
    if isinstance(data, dict):
        raw = data.get('result') or data.get('data') or data
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
                    threading.Thread(target=_save_sector_cache, daemon=True).start()


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
    if config.cdp_engine and config.cdp_engine.ready:
        for name in _STOCK_NAV_PAGES:
            page = config.cdp_engine.get_page(name)
            if page:
                try:
                    data = page.get_data()
                    ci = data.get('stock_company_info')
                    if _company_info_matches(ci, stock_code):
                        industry = (ci.get('basic_info') or {}).get('IndustryName') or ''
                        if industry:
                            sector = industry.split('-')[0]
                            break
                except Exception:
                    pass

    if sector:
        with _sector_cache_lock:
            _sector_cache[stock_code] = {'sector': sector, 'ts': time()}
        threading.Thread(target=_save_sector_cache, daemon=True).start()
    return sector


_STOCK_NAV_PAGES = ('cls_f10', 'cls_stock', 'cls_stock_2', 'cls_stock_3',
                     'cls_stock_4', 'cls_stock_5', 'cls_stock_6',
                     'cls_stock_7', 'cls_stock_8', 'cls_stock_9',
                     'cls_stock_10', 'cls_stock_11', 'cls_stock_12',
                     'cls_stock_13', 'cls_stock_14')


def _navigate_for_sector(stock_code, deadline):
    """Try navigate_stock on available CDP pages until one succeeds.

    Uses multiple pages with separate _navigate_lock to increase
    concurrent navigation capacity. Returns (data_dict, sector_str).
    """
    for pname in _STOCK_NAV_PAGES:
        page = config.cdp_engine.get_page(pname)
        if not page:
            continue
        remaining = 15
        if deadline:
            remaining = min(remaining, int(deadline - time()))
        if remaining < 3:
            continue
        try:
            if not page._navigate_lock.acquire(timeout=0.5):
                continue
            page._navigate_lock.release()
        except AttributeError:
            continue
        if page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining):
            poll_deadline = time() + 3
            while time() < poll_deadline:
                data = page.get_data()
                ci = data.get('stock_company_info') or {}
                if _company_info_matches(ci, stock_code):
                    raw_sector = (ci.get('basic_info') or {}).get('IndustryName', '')
                    if raw_sector:
                        return data, raw_sector.split('-')[0]
                page.refresh()
                sleep(0.5)
            data = page.get_data()
            ci = data.get('stock_company_info') or {}
            if _company_info_matches(ci, stock_code):
                raw_sector = (ci.get('basic_info') or {}).get('IndustryName', '')
                if raw_sector:
                    return data, raw_sector.split('-')[0]
    return None, None


def fetch_cls_basic_info(stock_code, deadline=None):
    """Fetch basic info with sector_name (申万一级行业).

    Two-phase:
      1) REST basic_info API for pricing data (<100ms)
      2) CDP navigate_stock for sector (via F10 tab, distributed across pages)
    Returns dict with secu_code, price data, and sector_name.
    """
    result = None

    # Phase 1: REST API — fast pricing & identity data
    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
    try:
        raw = json.loads(fetch_json(url, _BASIC_INFO_HEADERS, ttl=_MAX_CACHE_AGE))
        if raw.get('code') == 200:
            result = raw
    except Exception:
        pass

    # Phase 2: Sector name — cache first, then CDP navigation
    sector = _extract_sector_name(stock_code)
    if not sector and config.cdp_engine and config.cdp_engine.ready:
        nav_data, sector = _navigate_for_sector(stock_code, deadline)
        if sector:
            _populate_sector_simple(stock_code, sector)

    # Merge sector_name into result
    if sector and result is not None:
        if not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector
        return result

    if result is not None:
        return result

    # Fallback: full CDP response (only if REST failed but navigation succeeded)
    if sector:
        result = nav_data.get('basic_info')
        if not isinstance(result, dict):
            result = {'code': 200, 'msg': 'success', 'data': {}}
            pd = (nav_data.get('basic_info') or {}).get('data')
            if isinstance(pd, dict):
                result['data'] = pd
        elif not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector
        return result

    return None


def _populate_sector_simple(stock_code, sector):
    """Set sector into shared cache and persist to disk."""
    if sector:
        with _sector_cache_lock:
            _sector_cache[stock_code] = {'sector': sector, 'ts': time()}
        threading.Thread(target=_save_sector_cache, daemon=True).start()


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
    result = _evaluate_fetch_any(url)
    if result and result.get('code') == 200:
        return result.get('data')
    return None


def _announcement_direct_fetch(stock_code):
    """Fetch announcements via CDP browser context (anti-ban), REST fallback."""
    result = _evaluate_fetch_any(_announcement_url(stock_code))
    if result and result.get('code') == 200:
        return result.get('data')
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

def handle_cls_stock(stock_code):
    """CLS Stock Detail Data — REST API direct."""
    try:
        url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={stock_code}'
        raw = json.loads(fetch_json(url, _STOCK_DETAIL_HEADERS, ttl=_MAX_CACHE_AGE))
        if raw.get('code') == 200:
            return raw.get('data')
    except Exception:
        pass
    return None


def handle_cls_stock_batch(codes):
    """Batch version of handle_cls_stock — returns {code: data, ...}."""
    result = {}
    for code in codes:
        if not VALID_STOCK_CODE.match(code):
            result[code] = None
        else:
            result[code] = handle_cls_stock(code)
    return result
