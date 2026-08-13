"""Stock data APIs: fundflow, timeline, F10, basic_info, stock detail.

CDP-based endpoints (fundflow, timeline, F10) use `config.cdp_engine`
(set by server.py init); basic_info now sources sector from REST only.
"""

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    _china_trading_ttl, stock_nav_page_names,
)
from cache import fetch_json, _fill_missing
from utils import cls_sign_params

log = logging.getLogger('stock')

# CDP stock navigation pages (created by init_cdp in server.py). Snapshot at
# import would freeze env-tuned sizing; resolve lazily so a fresh env value is
# picked up without code changes.
def _stock_nav_pages():
    return list(stock_nav_page_names())

# Bounded parallelism for batch fetches (per-request fan-out is capped).
_BATCH_MAX_WORKERS = 8


def _run_batch(fetcher, codes, deadline=None, concurrent=True):
    """Fetch codes either concurrently or serially.

    concurrent=True: parallel (safe for REST / non-mutating CDP evaluate_fetch).
    concurrent=False: serial (required for CDP `navigate_stock` callers such as
    F10 which mutate the shared nav page pool — parallelizing makes
    `_navigate_f10` skip all busy pages -> null results).
    `fetcher` is a single-arg callable: fetcher(code) -> data | None.
    Returns {code: data_or_None}.
    """
    if not codes:
        return {}
    if not concurrent:
        return {code: _fetch_one(fetcher, code, deadline) for code in codes}
    results = {}
    with ThreadPoolExecutor(max_workers=min(_BATCH_MAX_WORKERS, len(codes))) as ex:
        futures = {ex.submit(_fetch_one, fetcher, code, deadline): code for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                results[code] = fut.result()
            except Exception:
                results[code] = None
    return {code: results.get(code) for code in codes}


def _fetch_one(fetcher, code, deadline):
    """Run fetch for a single code, honoring the batch deadline.

    The batch deadline is forwarded to fetchers that accept it (CDP
    navigation fetchers like fetch_cls_f10/basic_info use it as their real
    time budget). REST fetchers ignore the extra kwarg.
    """
    if deadline is not None and time() > deadline:
        return None
    try:
        return fetcher(code, deadline=deadline)
    except TypeError:
        return fetcher(code)


def _handle_cached_batch(codes, pool, pool_max, cache, cache_ts, lock,
                         fetcher, deadline=None, after=None, concurrent=True):
    """Shared batch handler for code-keyed REST/CDP endpoints.

    Steps: dedupe -> validate -> LRU pool touch -> freshness cache lookup ->
    fetch of misses (parallel for REST/CDP-evaluate, serial for CDP-navigate) ->
    cache/result merge. `after(data, code)` runs post-cache (e.g. sector).
    """
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    result = {}
    valid = []
    for code in codes:
        if VALID_STOCK_CODE.match(code):
            valid.append(code)
        else:
            result[code] = None
    if not valid:
        return result

    now = time()
    with lock:
        for code in valid:
            pool[code] = now
        if len(pool) > pool_max:
            excess = sorted(pool, key=pool.get)[:len(pool) - pool_max]
            for code in excess:
                del pool[code]
                cache.pop(code, None)
                cache_ts.pop(code, None)

    missing = []
    with lock:
        for code in valid:
            cached = cache.get(code)
            if cached is not None:
                ts = cache_ts.get(code, 0)
                if now - ts < _MAX_CACHE_AGE:
                    result[code] = cached
                else:
                    missing.append(code)
            else:
                missing.append(code)

    if missing:
        fetched = _run_batch(fetcher, missing, deadline, concurrent=concurrent)
        for code, data in fetched.items():
            if data is not None:
                with lock:
                    cache[code] = data
                    cache_ts[code] = time()
                if after is not None:
                    try:
                        after(data, code)
                    except Exception:
                        pass
            result[code] = data
    return result


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
    """Try evaluate_fetch on any available page. Returns parsed dict or None.

    Tries pages in order but stops at the first page that returns a usable
    dict; per-page budget is capped so a slow/busy page doesn't exhaust the
    whole window. Returns the hit from the first available page, never blocks
    across every page.
    """
    if not config.cdp_engine or not config.cdp_engine.ready:
        return None
    deadline = time() + timeout
    for name in _stock_nav_pages()[:3] + ['cls_finance', 'cls_quotation']:
        if time() >= deadline:
            break
        page = config.cdp_engine.get_page(name)
        if not page:
            continue
        budget = min(deadline - time(), 2)
        if budget < 0.5:
            break
        try:
            result = page.evaluate_fetch(url, timeout=budget)
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
    return _handle_cached_batch(
        codes, _fundflow_pool, _FUNDFLOW_MAX_POOL,
        _fundflow_cache, _fundflow_cache_ts, _fundflow_cache_lock,
        fetcher=fetch_cls_fundflow)


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
            log.error(f'[fundflow] prefetch error: {e}')


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
    return _handle_cached_batch(
        codes, _timeline_pool, _TIMELINE_MAX_POOL,
        _timeline_cache, _timeline_cache_ts, _timeline_cache_lock,
        fetcher=fetch_cls_timeline)


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
            log.error(f'[timeline] prefetch error: {e}')


# ── F10 (Financial Summary) ────────────────────────────────────────────────

_f10_cache = {}
_f10_cache_ts = {}
_f10_pool = {}
_f10_cache_lock = threading.Lock()


def _navigate_f10(page, stock_code, deadline):
    """Navigate stock — block on a busy page, do not skip.

    Previously the 0.5s probe-skip caused null results under concurrent
    load (3 pages shared across 12+ concurrent f10 requests).
    Blocking with fair queuing gives 100% success but at higher latency
    under heavy contention — which is acceptable for the low-frequency
    RSS reader workload.
    """
    remaining = deadline - time()
    if remaining < 2:
        return False
    try:
        return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)
    except Exception:
        return False


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
    for name in _stock_nav_pages():
        page = config.cdp_engine.get_page(name)
        if page:
            yield page


def fetch_cls_f10(stock_code, deadline=None):
    """Fetch F10 company info — CDP navigation with fast cache check.

    Returns company_info data dict: {basic_info, ipo_info, ...}
    matching the original CDP capture format.

    Holds the page navigation lock across navigate_stock() AND get_data()
    so a concurrent request cannot navigate the shared page to a different
    code between the navigation and the read (that race returned nulls
    under concurrent load). _navigate_lock is an RLock, so the re-entrant
    acquire inside navigate_stock() is safe.
    """
    if config.cdp_engine and config.cdp_engine.ready:
        d = deadline or time() + 10
        for page in _iter_nav_pages():
            if time() >= d - 1:
                break
            with page._navigate_lock:
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
    batch_deadline = time() + 60
    return _handle_cached_batch(
        codes, _f10_pool, _F10_MAX_POOL,
        _f10_cache, _f10_cache_ts, _f10_cache_lock,
        fetcher=fetch_cls_f10, deadline=batch_deadline,
        after=_populate_sector_from_f10, concurrent=False)


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
                data = fetch_cls_f10(code, deadline=time() + 4)
                if data:
                    with _f10_cache_lock:
                        _f10_cache[code] = data
                        _f10_cache_ts[code] = time()
                    _populate_sector_from_f10(data, code)
        except Exception as e:
            log.error(f'[f10] prefetch error: {e}')


# ── Basic Info ─────────────────────────────────────────────────────────────

_basic_info_cache = {}
_basic_info_cache_ts = {}
_basic_info_pool = {}
_basic_info_cache_lock = threading.Lock()

# Shared sector name cache (industry rarely changes, long TTL + file persistence)
_SECTOR_CACHE_FILE = 'data/sector_cache.json'
_sector_cache = {}
_sector_cache_lock = threading.Lock()
# Bounded: sector changes are rare but an unbounded dict + disk file grows
# forever on a long-running 2c2g box. Cap size and expire old entries.
_SECTOR_CACHE_MAX = 2000
_SECTOR_CACHE_TTL = 7 * 24 * 3600  # 7 days


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
                log.info(f'[sector] loaded {count} entries from {_SECTOR_CACHE_FILE}')
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning(f'[sector] load error: {e}')


def _save_sector_cache():
    """Persist sector cache to disk (called from the single writer thread)."""
    try:
        with _sector_cache_lock:
            data = dict(_sector_cache)
        os.makedirs(os.path.dirname(_SECTOR_CACHE_FILE), exist_ok=True)
        tmp = _SECTOR_CACHE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _SECTOR_CACHE_FILE)
    except Exception as e:
        log.warning(f'[sector] save error: {e}')


_sector_dirty = False
_sector_save_lock = threading.Lock()
_SECTOR_WRITE_DEBOUNCE = 2  # seconds between disk flushes


def _sector_cache_writer():
    """Single background writer: flush dirty sector cache with debounce.

    Replaces the old thread-per-update spawn, avoiding disk write storms and
    concurrent writes to /data/sector_cache.json.
    """
    global _sector_dirty
    while True:
        sleep(_SECTOR_WRITE_DEBOUNCE)
        with _sector_save_lock:
            if not _sector_dirty:
                continue
            _sector_dirty = False
            _save_sector_cache()

# Single background writer for sector cache (debounced disk flush)
_load_sector_cache()
threading.Thread(target=_sector_cache_writer, daemon=True).start()


def _sweep_sector_cache(now=None):
    """Drop expired entries from _sector_cache. Caller must hold the lock."""
    if now is None:
        now = time()
    expired = [k for k, v in _sector_cache.items()
               if isinstance(v, dict) and now - v.get('ts', 0) > _SECTOR_CACHE_TTL]
    for k in expired:
        del _sector_cache[k]
    if expired:
        log.info(f'[sector] expired {len(expired)} entries from sector cache')


def _sector_cache_put(code, sector, now=None):
    """Insert into the bounded sector cache (sweep + cap eviction)."""
    global _sector_dirty
    if now is None:
        now = time()
    with _sector_cache_lock:
        _sweep_sector_cache(now)
        if len(_sector_cache) >= _SECTOR_CACHE_MAX:
            oldest = min(_sector_cache, key=lambda k: _sector_cache[k].get('ts', 0))
            del _sector_cache[oldest]
        _sector_cache[code] = {'sector': sector, 'ts': now}
    with _sector_save_lock:
        _sector_dirty = True


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
                    _sector_cache_put(code, sector)





def fetch_cls_basic_info(stock_code, deadline=None):
    """Fetch basic info with sector_name.

    Two-phase:
      1) REST basic_info API for pricing data (<100ms)
      2) REST stock detail API for sector (primary_industry.plate_name)
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

    # Phase 2: Sector name from stock detail API (primary_industry.plate_name)
    sector = None
    try:
        detail_url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={stock_code}'
        detail_raw = json.loads(fetch_json(detail_url, _STOCK_DETAIL_HEADERS, ttl=_MAX_CACHE_AGE))
        if detail_raw.get('code') == 200:
            sector = (detail_raw.get('data', {}).get('primary_industry') or {}).get('plate_name', '')
            if not sector:
                sector = None
    except Exception:
        pass

    # Merge sector_name into result
    if sector and result is not None:
        if not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector
        return result

    if result is not None:
        return result

    return None


def handle_cls_basic_infos(codes):
    """Stock Basic Info — batch supported."""
    batch_deadline = time() + 60
    return _handle_cached_batch(
        codes, _basic_info_pool, _BASIC_INFO_MAX_POOL,
        _basic_info_cache, _basic_info_cache_ts, _basic_info_cache_lock,
        fetcher=fetch_cls_basic_info, deadline=batch_deadline)


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
    return _handle_cached_batch(
        codes, _announcement_pool, _ANNOUNCEMENT_MAX_POOL,
        _announcement_cache, _announcement_cache_ts, _announcement_cache_lock,
        fetcher=fetch_cls_announcement)


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
            log.error(f'[announcement] prefetch error: {e}')


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
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]
    result = {}
    valid = []
    for code in codes:
        if VALID_STOCK_CODE.match(code):
            valid.append(code)
        else:
            result[code] = None
    if valid:
        fetched = _run_batch(handle_cls_stock, valid)  # REST, parallel is safe
        result.update(fetched)
    return result
