"""Stock data APIs: fundflow, timeline, F10, basic_info, stock detail.

Every code-level fetcher shares one signature ``fetch_*(code, deadline=None,
ttl=None)`` so the request deadline (R13) and the cache TTL (INV-1a) propagate
end to end: handler -> budget -> ``_handle_cached_batch`` -> ``_process_chunk``
-> ``_run_batch`` -> ``_fetch_one`` -> fetcher -> ``fetch_json`` (the sole HTTP
funnel — URL/negative cache + single-flight).

Failures are classified as ``cache.FetchError(kind)`` and surfaced per code by
``cache.build_batch_response`` as ``_errors``; successful-but-empty stays
``None`` (no data, never counted). A shared code-level failure ledger
(ADR-014) gives failed codes a 120s cooldown that both the batch path and the
4 prefetch loops honour.
"""

import json
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep, time
from urllib.parse import urlencode

from . import config
from . import metrics
from .cache import FetchError, _fill_missing, build_batch_response, fetch_json
from .cdp_engine import page_data
from .config import (
    MAX_DEDUP_CODES, REQUEST_TIMEOUT, _MAX_BATCH_SIZE,
    _ANNOUNCEMENT_BASE_URL, _ANNOUNCEMENT_HEADERS, _BASIC_INFO_BASE_URL,
    _BASIC_INFO_HEADERS, _F10_EXPECTED_KEYS, _FUNDFLOW_BASE_URL,
    _FUNDFLOW_HEADERS, _STOCK_DETAIL_BASE_URL, _STOCK_DETAIL_HEADERS,
    _TIMELINE_BASE_URL, _TIMELINE_HEADERS, cache_policy, canonical_code,
    stock_nav_page_names,
)
from .utils import cls_sign_params

log = logging.getLogger('stock')

# CDP stock navigation pages (created by init_cdp in server.py). Snapshot at
# import would freeze env-tuned sizing; resolve lazily so a fresh env value is
# picked up without code changes.
def _stock_nav_pages():
    return list(stock_nav_page_names())


# ── Constants ──────────────────────────────────────────────────────────────

# Bounded parallelism for batch fetches. Public alias (no underscore) is the
# one stream.py reads to size the refresh coverage window (INV-1b / AR-1).
BATCH_MAX_WORKERS = 8
_BATCH_MAX_WORKERS = BATCH_MAX_WORKERS

# End-to-end batch budgets. REST is bounded by AC-E2 (<=15s); CDP navigation is
# serial and cannot finish 50 codes within 15s, so it keeps the 60s budget
# (REV-DES-21 accepts the residual risk for the non-hot /stock/f10 path).
_BATCH_BUDGET_REST = 15
_BATCH_BUDGET_CDP = 60
# Per-call CDP budget for one page evaluate/navigation (AC-S7 matrix).
_CDP_CALL_TIMEOUT = 8
# Per-code f10 prefetch budget (REV-DES-16).
_PREFETCH_CDP_CALL_TIMEOUT = 4
# Cap prefetch work per pass so a huge pool doesn't monopolize the CDP
# navigation pages or burn a whole interval in one loop iteration.
_PREFETCH_PASS_BUDGET = 60.0

# Shared failure ledger (ADR-014): (domain, code) -> 120s cooldown, shared by
# the batch path and all 4 prefetch loops.
FAIL_THRESHOLD = 3
FAIL_COOLDOWN = 120
_FAIL_DOMAINS = ('quote', 'fundflow', 'timeline', 'f10', 'announcement')
_FAIL_LEDGER_MAX = len(_FAIL_DOMAINS) * MAX_DEDUP_CODES        # 10000

# Local-budget marker (P1-1).  `_fetch_one`/`_run_batch` use it when *our own*
# deadline has already elapsed, i.e. no network attempt was made.  `_process_chunk`
# translates it to the pristine `upstream_timeout` error shape for the client but
# never writes it to the 120s cooldown ledger — matching cache.py's S1-1 rule
# ("local wait budget, not an upstream failure ⇒ never record").  Recording it
# made a single slow batch cool down the whole pool tail, a self-inflicted
# positive feedback loop.  It is deliberately not a `FetchError.KINDS` member.
_LOCAL_BUDGET = '__local_budget__'

# Round-robin cursor for prefetch loops so a large pool is refreshed
# fairly instead of always starting at index 0 (which would re-fetch the
# head every pass and leave the tail permanently stale).
_prefetch_cursor = {}
_prefetch_cursor_lock = threading.Lock()

# P2-13: per-page locks for _evaluate_fetch_any to prevent concurrent
# evaluate_fetch on the same CDP page (which can corrupt page state).
_page_fetch_locks = {}
_page_fetch_locks_lock = threading.Lock()


# ── Domain stores: (pool, terminal cache, write-ts, lock) ──────────────────
# Terminal caches are OrderedDict for true LRU access order (BR-SA-15).
# pool_max/cache_max/ttl come from cache_policy(domain); the containers here
# hold no policy.

_fundflow_pool = {}
_fundflow_cache = OrderedDict()
_fundflow_cache_ts = {}
_fundflow_cache_lock = threading.Lock()

_timeline_pool = {}
_timeline_cache = OrderedDict()
_timeline_cache_ts = {}
_timeline_cache_lock = threading.Lock()

_f10_pool = {}
_f10_cache = OrderedDict()
_f10_cache_ts = {}
_f10_cache_lock = threading.Lock()

_basic_info_pool = {}
_basic_info_cache = OrderedDict()
_basic_info_cache_ts = {}
_basic_info_cache_lock = threading.Lock()

_announcement_pool = {}
_announcement_cache = OrderedDict()
_announcement_cache_ts = {}
_announcement_cache_lock = threading.Lock()

# domain -> (pool, cache, cache_ts, lock). /stock/data is intentionally absent:
# it has no dedup pool and no terminal cache (URL cache only, §10#4).
_DOMAIN_STORES = {
    'quote':        (_basic_info_pool,   _basic_info_cache,   _basic_info_cache_ts,   _basic_info_cache_lock),
    'fundflow':     (_fundflow_pool,     _fundflow_cache,     _fundflow_cache_ts,     _fundflow_cache_lock),
    'timeline':     (_timeline_pool,     _timeline_cache,     _timeline_cache_ts,     _timeline_cache_lock),
    'f10':          (_f10_pool,          _f10_cache,          _f10_cache_ts,          _f10_cache_lock),
    'announcement': (_announcement_pool, _announcement_cache, _announcement_cache_ts, _announcement_cache_lock),
}

# Shared sector name cache (industry rarely changes; TTL/cap from
# cache_policy('sector')). RLock: _sweep_sector_cache() acquires the lock
# itself yet is also called by _sector_cache_put() which already holds it.
_sector_cache = {}
_sector_cache_lock = threading.RLock()


# ── Shared failure ledger (BR-SA-5..12) ────────────────────────────────────

_fail_ledger = {}
_fail_ledger_lock = threading.Lock()

# S1-3: housekeeping cadence for the failure path. The ledger can hold up to
# _FAIL_LEDGER_MAX entries, so doing the O(n) aged-scan *and* an O(n)
# `code_cooldown_list` rebuild on every failure write made an n-failure storm
# O(n²) — all serialized on _fail_ledger_lock (degradation that amplifies itself
# exactly when the system is already failing). The gauge is republished only
# when the *active cooldown set* actually changes (a cooldown opens/closes) or
# the sample interval elapses; the bulk aged-scan runs at most once per
# interval (per-key ageing in `_fail_ledger_get` + the hard cap keep the bound).
_COOLDOWN_PUBLISH_INTERVAL = 5.0
_FAIL_LEDGER_PRUNE_INTERVAL = 5.0
_cooldown_published_at = 0.0
_fail_ledger_pruned_at = 0.0


def _cooldown_snapshot_locked(now):
    """Cooldown entries still active at `now`. Caller must hold the lock."""
    return [[d, c, e[1]] for (d, c), e in _fail_ledger.items() if e[1] > now]


def _fail_ledger_prune_locked(now):
    """BR-SA-8/9: age out stale entries + hard-cap eviction (caller holds lock).

    The O(n) aged-scan is rate-limited to `_FAIL_LEDGER_PRUNE_INTERVAL` (S1-3)
    so a failure storm never pays a full-ledger scan per write.  The hard cap
    evicts in O(1) amortised: ``dict`` preserves insertion order, so dropping
    from the front discards the oldest-registered keys.  The previous
    ``sorted()`` over the whole ledger ran on *every* write once at cap (a
    10001-key sort serialized on the ledger lock) — a sustained failure storm
    refreshed ``e[3]`` for every entry, so the aged-scan never freed a slot and
    the S1-3 O(n²) degradation survived (P1-4).  First-insertion order is an
    acceptable victim choice here: reaching the cap already means more distinct
    (domain, code) failures than the whole dedup pool can hold.
    """
    global _fail_ledger_pruned_at
    pruned = 0
    if now - _fail_ledger_pruned_at >= _FAIL_LEDGER_PRUNE_INTERVAL:
        aged = [k for k, e in _fail_ledger.items() if now - e[3] > FAIL_COOLDOWN]
        for k in aged:
            del _fail_ledger[k]
        pruned = len(aged)
        _fail_ledger_pruned_at = now
    while len(_fail_ledger) > _FAIL_LEDGER_MAX:                       # BR-SA-9
        _fail_ledger.pop(next(iter(_fail_ledger)))                    # O(1) victim
    return pruned


def _fail_ledger_get(domain, code, now=None):
    """BR-SA-8: return a copy of the entry, or None (aging out stale ones)."""
    now = time() if now is None else now
    with _fail_ledger_lock:
        entry = _fail_ledger.get((domain, code))
        if entry is None:
            return None
        if now - entry[3] > FAIL_COOLDOWN:                            # not "consecutive"
            del _fail_ledger[(domain, code)]
            return None
        return list(entry)


def _fail_ledger_record_failure(domain, code, kind, now=None):
    """BR-SA-6/7: count a real fetch failure; 3 in a row -> 120s cooldown."""
    global _cooldown_published_at
    now = time() if now is None else now
    snapshot = publish = None
    with _fail_ledger_lock:
        prev = _fail_ledger.get((domain, code))
        fresh = prev is not None and (now - prev[3]) <= FAIL_COOLDOWN
        cnt = (prev[0] + 1) if fresh else 1
        cooldown = (now + FAIL_COOLDOWN) if cnt >= FAIL_THRESHOLD else 0.0
        _fail_ledger[(domain, code)] = [cnt, cooldown, kind, now]
        _fail_ledger_prune_locked(now)
        # The O(n) `code_cooldown_list` rebuild is published at most once per
        # interval, including when a cooldown opens (P1-4).  Letting the
        # inactive→active transition bypass the interval made a cold-start
        # upstream outage rebuild the whole ledger from *inside* the lock on
        # every write.  A ≤5s publication lag is immaterial for a 120s cooldown;
        # any later write (failure or clear) refreshes the gauge.
        if now - _cooldown_published_at >= _COOLDOWN_PUBLISH_INTERVAL:
            snapshot = _cooldown_snapshot_locked(now)
            _cooldown_published_at = now
            publish = True
    if publish:
        metrics.set_gauge('code_cooldown_list', snapshot)             # BR-SA-12


def _fail_ledger_clear(domain, code):
    """BR-SA-6: success clears the whole entry (republishes on the same cadence)."""
    global _cooldown_published_at
    now = time()
    snapshot = publish = None
    with _fail_ledger_lock:
        entry = _fail_ledger.pop((domain, code), None)
        if entry is None:
            return
        if now - _cooldown_published_at >= _COOLDOWN_PUBLISH_INTERVAL:
            snapshot = _cooldown_snapshot_locked(now)
            _cooldown_published_at = now
            publish = True
    if publish:
        metrics.set_gauge('code_cooldown_list', snapshot)


def code_cooldown_list(now=None):
    """Enumerable cooldown list: [[domain, code, cooldown_until], ...]."""
    now = time() if now is None else now
    with _fail_ledger_lock:
        return _cooldown_snapshot_locked(now)


# ── Deadline / failure classification helpers (BR-SA-19) ───────────────────

def _fetch_rest_json(url, headers, ttl, deadline=None):
    """The single REST fetch funnel: budget pass-through + failure classification.

    The remaining R13 budget is threaded into ``fetch_json`` so its
    ``urlopen`` timeout is clamped to the caller's deadline instead of the
    fixed ``REQUEST_TIMEOUT`` (S1-5 — otherwise a call that passes the gate can
    still run a full 10s and blow the 15s batch budget).

    There is deliberately no deadline gate *here* (P1-5): ``fetch_json`` checks
    its positive cache before enforcing the deadline, so a URL-cache hit is
    still served once the batch budget is exhausted.  Gating first would make a
    slow batch return ``null`` for data that was already in cache.

    ``fetch_json`` already counts its own network failures (BR-CACHE-6), so a
    ``FetchError`` from it is re-raised untouched (BR-SA-29). Only the failures
    this layer detects (JSON decode / non-dict payload) are counted here.
    """
    try:
        raw = json.loads(fetch_json(url, headers, ttl=ttl, deadline=deadline))
    except FetchError:
        raise                                                         # cache counted it
    except Exception as exc:                                          # JSON decode
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url, cause=exc) from exc
    if not isinstance(raw, dict):                                     # upstream not dict
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url)
    return raw


# ── Terminal cache (LRU + TTL + cache_max; BR-SA-2/13..16) ─────────────────

def _cache_store(cache, cache_ts, lock, code, data, cache_max, domain, now=None):
    """Write with true-LRU eviction; TTL base is the write instant only."""
    now = time() if now is None else now
    with lock:
        cache[code] = data
        cache_ts[code] = now                                          # TTL base
        cache.move_to_end(code)                                       # BR-SA-15
        if len(cache) > cache_max:
            victim, _ = cache.popitem(last=False)                     # true LRU
            cache_ts.pop(victim, None)
        size = len(cache)
    metrics.set_gauge('cache_entries', size, key=domain)              # BR-SA-26


def cached_batch(domain, codes, now=None):
    """Read-only view of the terminal cache (used by stream slicing).

    No network: returns {code: data} for entries whose TTL has not expired and
    LRU-touches each hit. Unknown domain -> {} + warning (never raises).

    Codes are canonicalised for the lookup (P1-6) while the result stays keyed
    by the *requested* spelling, so a caller that still passes ``600519.SH``
    reads the same entry as one passing ``sh600519`` and receives the key it
    asked for.
    """
    store = _DOMAIN_STORES.get(domain)
    if store is None:
        log.warning('[cached_batch] unknown domain %r', domain)
        return {}
    _pool, cache, cache_ts, lock = store
    if cache is None:
        return {}
    now = time() if now is None else now
    ttl = cache_policy(domain)['ttl']
    out = {}
    with lock:
        for code in codes:
            canon = canonical_code(code)
            if canon is None:
                continue
            data = cache.get(canon)
            if data is not None and now - cache_ts.get(canon, 0) < ttl:
                cache.move_to_end(canon)
                out[code] = data
    return out


# ── Batch pipeline: _fetch_one / _run_batch / _process_chunk / _handle_cached_batch ──

def _call_fetcher(fetcher, code, deadline, ttl):
    """Call ``fetcher(code, deadline=..., ttl=...)``, degrading only on a
    **call-frame** TypeError (argument binding — a signature-mismatched test
    double that rejects the keyword form).

    A TypeError raised *inside* the fetcher body is a real failure and is
    re-raised untouched: retrying it would execute the fetch twice (P2-④).
    Each fallback keeps ``deadline``/``ttl`` for every parameter the callable
    accepts, so the budget is never silently dropped (S1-5).
    """
    for kwargs in ({'deadline': deadline, 'ttl': ttl},
                   {'deadline': deadline},
                   {'ttl': ttl},
                   {}):
        try:
            return fetcher(code, **kwargs)
        except TypeError as exc:
            tb = exc.__traceback__
            if tb is None or tb.tb_next is not None:
                raise                                  # raised in the body
    # Every keyword form was rejected at call time (arity/parameter mismatch).
    raise TypeError(f'{fetcher!r} does not accept (code, deadline, ttl)')


def _fetch_one(fetcher, code, deadline=None, ttl=None):
    """The single deadline/failure-classification funnel. Never raises.

    An already elapsed deadline is ``_LOCAL_BUDGET`` — our own budget, not an
    upstream failure — so the caller can surface the timeout shape without
    writing it to the cooldown ledger (P1-1).
    """
    if deadline is not None and time() > deadline:                    # BR-SA-20
        return None, _LOCAL_BUDGET
    try:
        return _call_fetcher(fetcher, code, deadline, ttl), None
    except FetchError as exc:
        return None, exc.kind
    except Exception:
        return None, 'upstream_error'


def _run_batch(fetcher, codes, deadline=None, ttl=None, concurrent=True):
    """Fetch codes, returning ``(results, errors)``.

    BR-SA-20: an exhausted budget creates no threads — every code is reported
    as ``_LOCAL_BUDGET`` (bounded degradation, never an unbounded wait; the
    marker keeps it out of the failure ledger — P1-1).
    """
    results, errors = {}, {}
    if not codes:
        return results, errors
    if deadline is not None and time() >= deadline:
        for code in codes:
            results[code] = None
            errors[code] = _LOCAL_BUDGET
        return results, errors
    if not concurrent:
        for code in codes:                                            # CDP must be serial
            data, kind = _fetch_one(fetcher, code, deadline, ttl)
            results[code] = data
            if kind:
                errors[code] = kind
        return results, errors
    with ThreadPoolExecutor(max_workers=min(BATCH_MAX_WORKERS, len(codes))) as ex:
        futures = {ex.submit(_fetch_one, fetcher, code, deadline, ttl): code
                   for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                data, kind = fut.result()
            except Exception:                                         # _fetch_one is total
                data, kind = None, 'upstream_error'
            results[code] = data
            if kind:
                errors[code] = kind
    return results, errors


def _process_chunk(codes, domain, policy, fetcher, pool=None, cache=None,
                   cache_ts=None, lock=None, deadline=None, after=None,
                   concurrent=True):
    """Process one chunk (caller passes <= _MAX_BATCH_SIZE codes).

    canonicalise -> dedupe -> validate -> pool touch -> cache lookup ->
    cooldown gate -> fetch -> cache/ledger merge.  Returns ``(results,
    errors)`` keyed by the *requested* spellings.
    """
    ttl = policy['ttl']
    pool_max = policy['pool_max']
    cache_max = policy['cache_max']
    # ① canonicalise + dedupe + validate (P1-6).  `canonical_code` folds
    # 'SH600519' / '600519.SH' into 'sh600519' so one stock can never mint two
    # pools / cache keys / upstream URLs.  Results are mapped back onto every
    # requested spelling before returning, because build_batch_response keys
    # off the requested codes (never its own re-spelling of them).
    results, errors = {}, {}
    alias = {}                        # requested spelling -> canonical
    canons = []                       # canonical codes, request order, deduped
    seen = set()
    for code in codes:
        canon = canonical_code(code)
        if canon is None:
            results[code] = None                                      # invalid -> null
            continue
        alias[code] = canon
        if canon not in seen:
            seen.add(canon)
            canons.append(canon)
    if not canons:
        return results, errors
    now = time()
    # ② pool membership touch + cap eviction (never touches the data cache)
    if pool is not None:
        with lock:
            for canon in canons:
                pool[canon] = now
            if len(pool) > pool_max:
                for victim in sorted(pool, key=pool.get)[:len(pool) - pool_max]:
                    del pool[victim]                                      # BR-SA-14
    # ③ terminal cache lookup (TTL hit / move_to_end)
    by_canon = {}
    missing = []
    if cache is not None:
        with lock:
            for canon in canons:
                data = cache.get(canon)
                if data is not None and now - cache_ts.get(canon, 0) < ttl:
                    cache.move_to_end(canon)
                    by_canon[canon] = data
                else:
                    missing.append(canon)                              # expired -> refetch
    else:
        missing = list(canons)
    # ④ code cooldown gate (hit -> no network)
    err_canon = {}
    eligible = []
    for canon in missing:
        entry = _fail_ledger_get(domain, canon, now)
        if entry is not None and entry[1] > now:
            by_canon[canon] = None
            err_canon[canon] = entry[2] or 'upstream_error'
            continue
        eligible.append(canon)
    # ⑤ fetch (deadline propagates; returns (results, errors))
    if eligible:
        fetched, fetch_errors = _run_batch(fetcher, eligible, deadline=deadline,
                                           ttl=ttl, concurrent=concurrent)
        # ⑥ merge + ledger + cache write
        for canon in eligible:
            data = fetched.get(canon)
            kind = fetch_errors.get(canon)
            if kind == _LOCAL_BUDGET:
                # P1-1: our own deadline ran out before any network attempt.
                # Surface the timeout shape, but never write it to the 120s
                # cooldown ledger (cache.md S1-1 parity) — otherwise a slow
                # batch cools down the pool tail and the cooldown is
                # self-inflicted.
                by_canon[canon] = None
                err_canon[canon] = 'upstream_timeout'
                continue
            if kind:
                _fail_ledger_record_failure(domain, canon, kind)       # BR-SA-6
                by_canon[canon] = None
                err_canon[canon] = kind
                continue
            if data is not None:
                _fail_ledger_clear(domain, canon)                      # success clears
                if cache is not None:
                    _cache_store(cache, cache_ts, lock, canon, data, cache_max, domain)
                if after is not None:
                    try:
                        after(data, canon)
                    except Exception:
                        log.warning('[after] callback failed for %s', canon)
                by_canon[canon] = data
            else:
                by_canon[canon] = None                                 # no data: no count
    # ⑦ map canonical results back onto every requested spelling
    for original, canon in alias.items():
        results[original] = by_canon.get(canon)
        if canon in err_canon:
            errors[original] = err_canon[canon]
    return results, errors


def _ceil_div(a, b):
    """BR-SA-23: integer ceil division (math is not on the import allowlist)."""
    return -(-a // b)


def _handle_cached_batch(codes, domain, policy, fetcher, pool=None, cache=None,
                         cache_ts=None, lock=None, budget=None,
                         per_call_timeout=REQUEST_TIMEOUT, after=None,
                         concurrent=True):
    """Shard codes into <= _MAX_BATCH_SIZE chunks and process them all.

    Never truncates: every code is processed across chunks (stream.py hands the
    whole dedup pool here). Returns ``(results, errors)``.
    """
    if not codes:
        return {}, {}
    results, errors = {}, {}
    workers = BATCH_MAX_WORKERS if concurrent else 1
    for i in range(0, len(codes), _MAX_BATCH_SIZE):
        chunk = codes[i:i + _MAX_BATCH_SIZE]
        if budget is not None:                                        # BR-SA-22
            chunk_budget = _ceil_div(len(chunk), workers) * per_call_timeout
            chunk_deadline = min(budget, time() + chunk_budget)
        else:
            chunk_deadline = None
        r, e = _process_chunk(chunk, domain, policy, fetcher, pool=pool,
                              cache=cache, cache_ts=cache_ts, lock=lock,
                              deadline=chunk_deadline, after=after,
                              concurrent=concurrent)
        results.update(r)
        errors.update(e)
    return results, errors


# ── Announcement URL (CLS sign) ────────────────────────────────────────────

def _announcement_url(stock_code):
    """Build signed announcement API URL — requires CLS sign."""
    params = {
        'app': 'CailianpressWeb', 'os': 'web', 'sv': '8.7.9',
        'secu_code': stock_code,
    }
    params['sign'] = cls_sign_params(params)
    return f'{_ANNOUNCEMENT_BASE_URL}?{urlencode(params)}'


# ── CDP helpers ────────────────────────────────────────────────────────────

def _get_page_fetch_lock(name):
    """Return (or create) a threading.Lock for the given CDP page name."""
    with _page_fetch_locks_lock:
        if name not in _page_fetch_locks:
            _page_fetch_locks[name] = threading.Lock()
        return _page_fetch_locks[name]


def _evaluate_fetch_any(url, deadline=None):
    """Try evaluate_fetch on any available page. Returns parsed dict or None.

    Tries pages in order but stops at the first page that returns a usable
    dict; per-page budget is capped so a slow/busy page doesn't exhaust the
    whole window. `deadline` shrinks the overall window.
    """
    if not config.cdp_engine or not config.cdp_engine.ready:
        return None
    end = time() + _CDP_CALL_TIMEOUT if deadline is None \
        else min(time() + _CDP_CALL_TIMEOUT, deadline)
    for name in _stock_nav_pages()[:3] + ['cls_finance', 'cls_quotation']:
        if time() >= end:
            break
        page = config.cdp_engine.get_page(name)
        if not page:
            continue
        budget = min(end - time(), 2)
        if budget < 0.5:
            break
        # P2-13: serialize evaluate_fetch per page to prevent concurrent
        # JS evaluation on the same shared CDP page.
        lock = _get_page_fetch_lock(name)
        with lock:
            try:
                result = page.evaluate_fetch(url, timeout=budget)
                if result and isinstance(result, dict):
                    return result
            except Exception:
                pass
    return None


def _iter_nav_pages():
    """Yield CDP stock navigation pages that are available."""
    if not config.cdp_engine or not config.cdp_engine.ready:
        return
    for name in _stock_nav_pages():
        page = config.cdp_engine.get_page(name)
        if page:
            yield page


def _acquire_nav_lock(page, remaining):
    """Bounded navigation-lock queue (P1-2).

    A navigation can hold its page's lock for up to ~60s (load wait + poll) and
    only ``stock_nav_page_names()`` pages carry every ``/stock/f10``.  An
    unbounded ``acquire()`` parked the request thread *and its admission slot*,
    so CDP slowness used to 503 the whole site (including ``/healthz``).  Wait
    at most the remaining request budget; on timeout degrade (skip the page →
    ``cdp_unavailable`` at the funnel) instead of blocking.
    """
    if remaining <= 0:
        return False
    try:
        return page._navigate_lock.acquire(timeout=remaining)
    except Exception:
        return False


def _navigate_f10(page, stock_code, deadline):
    """Navigate stock — block on a busy page, bounded by the request deadline.

    The lock wait itself is budgeted (P1-2): a page busy past our deadline is a
    degradation, never an unbounded park that starves the admission pool.
    """
    remaining = deadline - time()
    if remaining < 2:
        return False
    if not _acquire_nav_lock(page, remaining):
        return False
    try:
        return page.navigate_stock(stock_code, tabs=('f10',), timeout=remaining)
    except Exception:
        return False
    finally:
        page._navigate_lock.release()


def _company_info_matches(ci, stock_code):
    """Check if company_info data belongs to the requested stock.

    Compares canonical forms (P1-6) so the two accepted ingress spellings
    (``600519.SH`` and ``sh600519``) match the same fixed upstream ``SecuCode``
    instead of one of them never matching.
    """
    if not isinstance(ci, dict):
        return False
    bi = ci.get('basic_info')
    if not isinstance(bi, dict):
        return False
    target = canonical_code(stock_code)
    return target is not None and canonical_code(bi.get('SecuCode', '')) == target


# ── Sector cache (TTL/cap from cache_policy('sector'); BR-SA-4) ────────────

def _sweep_sector_cache(now=None):
    """Drop expired entries from _sector_cache (acquires the sector lock)."""
    if now is None:
        now = time()
    ttl = cache_policy('sector')['ttl']
    with _sector_cache_lock:
        expired = [k for k, v in _sector_cache.items()
                   if isinstance(v, dict) and now - v.get('ts', 0) > ttl]
        for k in expired:
            del _sector_cache[k]
    if expired:
        log.info(f'[sector] expired {len(expired)} entries from sector cache')


def _sector_cache_put(code, sector, now=None):
    """Insert into the bounded sector cache (sweep + cap eviction)."""
    if now is None:
        now = time()
    cap = cache_policy('sector')['cache_max']
    with _sector_cache_lock:
        _sweep_sector_cache(now)
        if len(_sector_cache) >= cap:
            oldest = min(_sector_cache, key=lambda k: _sector_cache[k].get('ts', 0))
            del _sector_cache[oldest]
        _sector_cache[code] = {'sector': sector, 'ts': now}
        size = len(_sector_cache)
    metrics.set_gauge('cache_entries', size, key='sector')


def _populate_sector_from_f10(data, code):
    """Extract sector from F10 company_info data and populate shared cache."""
    if isinstance(data, dict):
        raw = data.get('result') or data.get('data') or data
        bi = raw.get('basic_info') or {}
        # company_info API uses SecuCode (camelCase)
        if isinstance(bi, dict):
            stored_code = bi.get('SecuCode') or bi.get('secu_code') or ''
            target = canonical_code(code)
            if target is not None and canonical_code(stored_code) == target:
                industry = bi.get('IndustryName') or ''
                if industry:
                    sector = industry.split('-')[0]
                    _sector_cache_put(code, sector)


# ── Detail-derived sector-name cache (fetch_cls_basic_info phase 2) ────────
# `fetch_cls_basic_info` attaches `sector_name` from the stock-detail endpoint
# (`primary_industry.plate_name`).  The stream tick refreshes quote per code,
# so that second REST call was half of the quote domain's upstream cost
# (BUG-P6C-01 root cause 2) even though industry names change on the order of
# days.  Caching them under the existing `sector` policy (7 d TTL / 2000 cap)
# keeps the returned value byte-identical while dropping the steady-state quote
# cost to 1 call/code.  Deliberately a separate store from `_sector_cache`:
# that one holds the F10 `IndustryName` prefix (`_populate_sector_from_f10`), a
# *different* upstream field whose string semantics must not leak into
# `sector_name`.  No dedicated gauge — metric names/labels are frozen
# (`metrics.md` §3.2), `cache_entries{sector}` stays owned by `_sector_cache`.
_basic_sector_cache = {}                     # code -> {'sector': str, 'ts': float}
_basic_sector_lock = threading.Lock()        # leaf lock: never held across IO


def _sweep_basic_sector_locked(now):
    """Drop expired entries; caller must hold `_basic_sector_lock`."""
    ttl = cache_policy('sector')['ttl']
    expired = [k for k, v in _basic_sector_cache.items()
               if now - v.get('ts', 0) > ttl]
    for k in expired:
        del _basic_sector_cache[k]


def _basic_sector_get(code, now=None):
    """Cached `sector_name` for `code`, or None when absent/expired."""
    now = time() if now is None else now
    with _basic_sector_lock:
        v = _basic_sector_cache.get(code)
        if v is None:
            return None
        if now - v.get('ts', 0) > cache_policy('sector')['ttl']:
            del _basic_sector_cache[code]
            return None
        return v.get('sector')


def _basic_sector_put(code, sector, now=None):
    """Store `sector` with the sector-policy TTL + cap (sweep then evict)."""
    if not sector:
        return                                   # empty ⇒ never cached (retry)
    now = time() if now is None else now
    cap = cache_policy('sector')['cache_max']
    with _basic_sector_lock:
        _sweep_basic_sector_locked(now)
        if code not in _basic_sector_cache and len(_basic_sector_cache) >= cap:
            oldest = min(_basic_sector_cache,
                         key=lambda k: _basic_sector_cache[k].get('ts', 0))
            del _basic_sector_cache[oldest]
        _basic_sector_cache[code] = {'sector': sector, 'ts': now}


# ── Code-level fetchers (REST first, CDP fallback) ─────────────────────────

def fetch_cls_fundflow(stock_code, deadline=None, ttl=None):
    """Fetch fund flow — REST first, CDP evaluate_fetch fallback."""
    domain = 'fundflow'
    url = f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)                  # BR-SA-28
    err = None
    try:
        raw = _fetch_rest_json(url, _FUNDFLOW_HEADERS, ttl, deadline)
        if raw.get('code') == 200:
            return raw.get('data')                                    # may be None
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')     # self-built
    except FetchError as exc:
        err = exc                                                     # cache counted it
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)                  # CDP fallback call
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_timeline(stock_code, deadline=None, ttl=None):
    """Fetch stock timeline — REST first, CDP evaluate_fetch fallback."""
    domain = 'timeline'
    url = f'{_TIMELINE_BASE_URL}?secu_code={stock_code}'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)
    err = None
    try:
        raw = _fetch_rest_json(url, _TIMELINE_HEADERS, ttl, deadline)
        if raw.get('code') == 200:
            return raw.get('data')
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_announcement(stock_code, deadline=None, ttl=None):
    """Fetch stock announcements — REST first (CLS sign), CDP fallback."""
    domain = 'announcement'
    url = _announcement_url(stock_code)
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl        # no bare ttl=15
    metrics.incr('upstream_fetch_total', key=domain)
    err = None
    try:
        raw = _fetch_rest_json(url, _ANNOUNCEMENT_HEADERS, ttl, deadline)
        if raw.get('code') == 200:
            return raw.get('data')
        err = FetchError('upstream_error', url=url)
        metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    if deadline is not None and time() >= deadline:
        raise err
    metrics.incr('upstream_fetch_total', key=domain)
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raise err


def fetch_cls_stock_detail(stock_code, deadline=None, ttl=None):
    """Fetch CLS stock detail — REST only."""
    domain = 'quote'
    url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={stock_code}'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)
    raw = _fetch_rest_json(url, _STOCK_DETAIL_HEADERS, ttl, deadline)
    if raw.get('code') == 200:
        return raw.get('data')
    metrics.incr('upstream_fail_total', key='upstream_error')          # semantic failure
    raise FetchError('upstream_error', url=url)


def fetch_cls_basic_info(stock_code, deadline=None, ttl=None):
    """Fetch basic info with sector_name.

    Two-phase:
      1) REST basic_info API for pricing data (fatal)
      2) REST stock detail API for sector (non-fatal, best effort; served from
         the 7-day `sector`-policy cache once the code's industry is known)
    Returns dict with secu_code + price data (+ sector_name).
    """
    domain = 'quote'
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    result, err = None, None
    # Phase 1: quote/identity (fatal)
    url = f'{_BASIC_INFO_BASE_URL}?secu_code={stock_code}'
    metrics.incr('upstream_fetch_total', key=domain)
    try:
        raw = _fetch_rest_json(url, _BASIC_INFO_HEADERS, ttl, deadline)
        if raw.get('code') == 200:
            result = raw
        else:
            err = FetchError('upstream_error', url=url)
            metrics.incr('upstream_fail_total', key='upstream_error')
    except FetchError as exc:
        err = exc
    # Phase 2: sector name (non-fatal).  Cache first: the value is identical to
    # the detail-derived one, so a hit removes the per-tick second upstream
    # call (BUG-P6C-01).  A failed phase 1 skips it entirely — the sector would
    # be discarded anyway.
    sector = _basic_sector_get(stock_code) if result is not None else None
    if sector is None and result is not None \
            and (deadline is None or time() < deadline):
        detail_url = f'{_STOCK_DETAIL_BASE_URL}?secu_code={stock_code}'
        metrics.incr('upstream_fetch_total', key=domain)
        try:
            detail_raw = _fetch_rest_json(detail_url, _STOCK_DETAIL_HEADERS, ttl, deadline)
            if detail_raw.get('code') == 200:
                sector = (detail_raw.get('data', {}).get('primary_industry') or {}) \
                    .get('plate_name', '')
                _basic_sector_put(stock_code, sector)
        except Exception:                                             # non-fatal
            pass
    if sector and result is not None:
        if not isinstance(result.get('data'), dict):
            result['data'] = {}
        result['sector_name'] = sector
    if result is not None:
        return result
    if err is not None:
        raise err
    return None


def _raise_cdp_unavailable():
    """The single `cdp_unavailable` exit (counts once, then raises).

    REV-DES-12 / P1-6: every failure exit in `fetch_cls_f10` funnels through
    here — engine down, no pages, spent budget, never navigated, data-less, or
    data for another stock — so `upstream_fail_total{cdp_unavailable}` is never
    under-counted and a mismatch can never become a silent, uncounted ``None``.
    """
    metrics.incr('upstream_fail_total', key='cdp_unavailable')        # BR-SA-29
    raise FetchError('cdp_unavailable')


def fetch_cls_f10(stock_code, deadline=None, ttl=None):
    """Fetch F10 company info — CDP navigation; A' shape on failure.

    Returns company_info data dict {basic_info, ipo_info, ...}. Any page that
    did not yield matching data (never navigated, data-less, or showing another
    stock) is a ``cdp_unavailable`` fetch failure — a silent ``None`` would mean
    "no data, not counted" and made the batch re-pay a full navigation on every
    tick without any error signal (P1-6).

    Holds the page navigation lock across navigate_stock() AND the data read so
    a concurrent request cannot navigate the shared page to a different code in
    between (that race returned nulls under concurrent load); the wait for that
    lock is bounded by the request deadline (P1-2).
    `ttl` is accepted for signature uniformity but unused (no URL cache).
    """
    if not (config.cdp_engine and config.cdp_engine.ready):
        _raise_cdp_unavailable()                                      # exit 1: engine down
    pages = list(_iter_nav_pages())
    if not pages:
        _raise_cdp_unavailable()                                      # exit 2: no nav pages
    d = deadline if deadline is not None else time() + _CDP_CALL_TIMEOUT
    if time() >= d:
        _raise_cdp_unavailable()                                      # exit 3: budget spent
    navigated = False
    got_data = False
    for page in pages:
        remaining = d - time()
        if remaining < 1:
            break
        if not _acquire_nav_lock(page, remaining):
            continue                                                  # P1-2: busy past budget
        try:
            if _navigate_f10(page, stock_code, d):
                navigated = True
                data = page_data(page)                                # R18 single entry
                if data is None:
                    continue                                          # page data cleared
                got_data = True
                r = {}
                _fill_missing(r, data, _F10_EXPECTED_KEYS)
                ci = r.get('stock_company_info')
                if _company_info_matches(ci, stock_code):
                    return ci
        finally:
            page._navigate_lock.release()
    # Exits 4/5: never navigated / data-less, or the pages showed a different
    # stock.  Both are cdp_unavailable, counted and surfaced (P1-6) — never a
    # silent, uncounted None.
    _raise_cdp_unavailable()


def _direct_fetch(url, headers, domain, deadline=None, ttl=None):
    """CDP evaluate_fetch first (anti-ban), REST fallback through `fetch_json`.

    Prefetch-only: never returns None on failure — raises FetchError.

    The REST leg goes through the shared ``fetch_json`` funnel (URL positive
    cache + negative cache + single-flight) instead of a bare ``urlopen``, so a
    prefetch is no longer a second HTTP entry that bypasses the aggregate
    (P2-①).  One logical fetch increments ``upstream_fetch_total`` exactly once.
    """
    ttl = cache_policy(domain)['ttl'] if ttl is None else ttl
    metrics.incr('upstream_fetch_total', key=domain)                  # BR-SA-28
    result = _evaluate_fetch_any(url, deadline=deadline)
    if result and result.get('code') == 200:
        return result.get('data')
    raw = _fetch_rest_json(url, headers, ttl, deadline)
    if raw.get('code') == 200:
        return raw.get('data')
    metrics.incr('upstream_fail_total', key='upstream_error')         # semantic failure
    raise FetchError('upstream_error', url=url)


def _fundflow_direct_fetch(stock_code, deadline=None):
    """Fetch fund flow via CDP browser context (anti-ban), REST fallback."""
    return _direct_fetch(f'{_FUNDFLOW_BASE_URL}?secu_code={stock_code}',
                         _FUNDFLOW_HEADERS, 'fundflow', deadline)


def _timeline_direct_fetch(stock_code, deadline=None):
    """Fetch timeline via CDP browser context (anti-ban), REST fallback."""
    return _direct_fetch(f'{_TIMELINE_BASE_URL}?secu_code={stock_code}',
                         _TIMELINE_HEADERS, 'timeline', deadline)


def _announcement_direct_fetch(stock_code, deadline=None):
    """Fetch announcements via CDP browser context (anti-ban), REST fallback."""
    return _direct_fetch(_announcement_url(stock_code),
                         _ANNOUNCEMENT_HEADERS, 'announcement', deadline)


# ── Public batch handlers (server / stream contract) ───────────────────────

def handle_cls_fundflow(codes, deadline=None, dropped=0):
    """Fund Flow Data (资金流向) — batch supported."""
    policy = cache_policy('fundflow')                                 # once per request
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['fundflow']
    results, errors = _handle_cached_batch(
        codes, 'fundflow', policy, fetch_cls_fundflow,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_timeline(codes, deadline=None, dropped=0):
    """Stock Timeline Data (分时图) — batch supported."""
    policy = cache_policy('timeline')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['timeline']
    results, errors = _handle_cached_batch(
        codes, 'timeline', policy, fetch_cls_timeline,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_f10(codes, deadline=None, dropped=0):
    """Stock F10 Financial Summary — CDP navigation, serial batch."""
    policy = cache_policy('f10')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_CDP
    pool, cache, cache_ts, lock = _DOMAIN_STORES['f10']
    results, errors = _handle_cached_batch(
        codes, 'f10', policy, fetch_cls_f10,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget,
        per_call_timeout=_CDP_CALL_TIMEOUT,
        after=_populate_sector_from_f10, concurrent=False)            # CDP must be serial
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_basic_infos(codes, deadline=None, dropped=0):
    """Stock Basic Info — batch supported."""
    policy = cache_policy('quote')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['quote']
    results, errors = _handle_cached_batch(
        codes, 'quote', policy, fetch_cls_basic_info,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_announcement(codes, deadline=None, dropped=0):
    """Stock Announcement Data (公告) — batch supported."""
    policy = cache_policy('announcement')
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    pool, cache, cache_ts, lock = _DOMAIN_STORES['announcement']
    results, errors = _handle_cached_batch(
        codes, 'announcement', policy, fetch_cls_announcement,
        pool=pool, cache=cache, cache_ts=cache_ts, lock=lock, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_stock_batch(codes, deadline=None, dropped=0):
    """Batch version of the stock detail endpoint (returns assembled dict).

    No dedup pool and no terminal cache — the URL cache inside fetch_json is
    the only cache layer (§10#4).
    """
    policy = cache_policy('quote')                                    # ttl source only
    budget = deadline if deadline is not None else time() + _BATCH_BUDGET_REST
    results, errors = _handle_cached_batch(
        codes, 'quote', policy, fetch_cls_stock_detail,
        pool=None, cache=None, cache_ts=None, lock=None, budget=budget)
    return build_batch_response(codes, results, errors, dropped=dropped)


def handle_cls_stock(stock_code):
    """CLS Stock Detail Data — retained thin wrapper (server import compat)."""
    try:
        return fetch_cls_stock_detail(stock_code)
    except Exception:
        return None


# ── Prefetch loops (4 public names; shared ledger + shared implementation) ──

def _prefetch_loop(name, domain, fetch_one, pool, cache, cache_ts, cache_lock,
                   after=None, per_call_budget=REQUEST_TIMEOUT):
    """Background loop: refresh one domain's pool fairly, sharing the ledger.

    Round-robin across the pool with a per-pass time budget so a large pool
    is refreshed fairly and the loop never stalls a whole interval.
    """
    while True:
        try:
            sleep(cache_policy(domain)['pool_refresh'])               # interval = policy
            codes = _prefetch_rotate(pool, cache_lock, name)
            if not codes:
                continue
            policy = cache_policy(domain)
            pass_deadline = time() + _PREFETCH_PASS_BUDGET
            visited = 0
            for code in codes:
                if time() >= pass_deadline:
                    break
                # S1-2: *visited* (consumed from the rotated head) — not
                # "processed" (data written) or "skipped" (cooldown) — advances
                # the round-robin cursor. Counting only the latter froze the
                # cursor whenever codes were fetched but returned no data
                # (`None` is success-but-empty, never counted), so the head was
                # re-fetched every pass and the pool tail was never reached.
                visited += 1
                now = time()
                entry = _fail_ledger_get(domain, code, now)           # shared ledger
                if entry is not None and entry[1] > now:
                    continue
                kind = None
                # REV-DES-16: one call still consumes a bounded budget.
                call_deadline = min(pass_deadline, now + per_call_budget)
                try:
                    data = fetch_one(code, deadline=call_deadline)
                except FetchError as exc:
                    data, kind = None, exc.kind
                except Exception:
                    data, kind = None, 'upstream_error'
                if data:
                    _cache_store(cache, cache_ts, cache_lock, code, data,
                                 policy['cache_max'], domain)
                    _fail_ledger_clear(domain, code)
                    if after is not None:
                        try:
                            after(data, code)
                        except Exception:
                            log.warning('[prefetch:%s] after failed for %s', name, code)
                elif kind:
                    _fail_ledger_record_failure(domain, code, kind)   # no data: no count
            _prefetch_advance(name, visited, len(codes))
        except Exception as e:
            log.error(f'[{name}] prefetch error: {e}')


def _fundflow_prefetch_loop():
    _prefetch_loop('fundflow', 'fundflow', _fundflow_direct_fetch,
                   _fundflow_pool, _fundflow_cache, _fundflow_cache_ts,
                   _fundflow_cache_lock)


def _timeline_prefetch_loop():
    _prefetch_loop('timeline', 'timeline', _timeline_direct_fetch,
                   _timeline_pool, _timeline_cache, _timeline_cache_ts,
                   _timeline_cache_lock)


def _f10_prefetch_loop():
    _prefetch_loop('f10', 'f10', fetch_cls_f10,
                   _f10_pool, _f10_cache, _f10_cache_ts, _f10_cache_lock,
                   after=_populate_sector_from_f10,
                   per_call_budget=_PREFETCH_CDP_CALL_TIMEOUT)        # single code <=4s


def _announcement_prefetch_loop():
    _prefetch_loop('announcement', 'announcement', _announcement_direct_fetch,
                   _announcement_pool, _announcement_cache, _announcement_cache_ts,
                   _announcement_cache_lock)


# ── Rotation primitives ────────────────────────────────────────────────────

def _prefetch_rotate(pool, lock, key):
    """Return pool codes rotated to start at the last pass's stop point."""
    with lock:
        keys = list(pool.keys())
    if not keys:
        return []
    with _prefetch_cursor_lock:
        start = _prefetch_cursor.get(key, 0) % len(keys)
    return keys[start:] + keys[:start]


def _prefetch_advance(key, visited, total):
    """Advance the round-robin cursor by the codes consumed this pass (S1-2)."""
    with _prefetch_cursor_lock:
        _prefetch_cursor[key] = (_prefetch_cursor.get(key, 0) + visited) % max(total, 1)


def _prefetch_slice(pool, lock, key, size):
    """Return (this pass's slice, next cursor value); does NOT move the cursor.

    Splitting "take slice" from "advance cursor" lets stream.py record
    `stream_refresh_lag_ticks` between the two.
    """
    ordered = _prefetch_rotate(pool, lock, key)
    if not ordered:
        return [], 0
    size = max(1, min(int(size), len(ordered)))
    with _prefetch_cursor_lock:
        start = _prefetch_cursor.get(key, 0) % len(ordered)
    return ordered[:size], (start + size) % len(ordered)
