"""Market-level data APIs: 融资融券 (margin).

Sourced from 同花顺 data center (public REST APIs, no auth needed).

TTL is derived from ``config.cache_policy('margin')`` only. ``cache.fetch_json``
remains the sole HTTP egress, but a TTL-fresh terminal-cache hit serves the
stored payload without calling it. Failures are classified as
``cache.FetchError(kind)`` and surface as an enumerated ``_error`` code.
"""

import json
import logging
import threading
import time
from collections import OrderedDict

from . import metrics
from .cache import FetchError, fetch_json
from .config import _MARGIN_HEADERS, _MARGIN_URL, cache_policy

log = logging.getLogger('market')

# Contract enum for `market` (market_api.md §2.1 / server.md §2.1 OpenAPI):
# '99'=合计(total) / '1'=沪市(SH) / '2'=深市(SZ) / '3'=京市(BJ).
# Single authority — server.py imports this for its boundary check, so the
# enum cannot drift between the routing layer and the URL builder.
VALID_MARKETS = ('99', '1', '2', '3')

# Terminal cache (LRU + TTL + cache_max; PRF-LAT-02).  The shared URL cache
# stores decoded *text* (cache.py) — every request that hits it still pays
# ``json.loads`` + ``_transform_margin`` on the hot path (measured P50 ≈8-9ms).
# Keyed by ``market`` (the full validated enum), so the cache can never hold
# more than len(VALID_MARKETS) entries in practice while ``cache_max`` still
# bounds it structurally.
_margin_cache = OrderedDict()          # market -> transformed payload
_margin_cache_ts = {}                  # market -> write instant (TTL base)
_margin_cache_lock = threading.Lock()

_DEGRADED_LATEST = {'rzye': 0.0, 'rqye': 0.0, 'rzmre': 0.0,
                    'rzjmr': 0.0, 'rqjmc': 0.0, 'lr': 0.0, 'zb': 0.0}


# ── 融资融券 (Margin / Securities Lending) ─────────────────────────────────

def _degraded(kind):
    """Single degraded-body builder (BR-MKT-7: kind is enum-closed)."""
    if kind not in FetchError.KINDS:
        kind = 'upstream_error'
    return {'latest': dict(_DEGRADED_LATEST), 'recent': [], '_error': kind}


def fetch_margin(market='99', deadline=None):
    """Fetch margin data for a given market.

    Args:
        market: '99'=合计(total), '1'=沪市(SH), '2'=深市(SZ), '3'=京市(BJ)
        deadline: absolute epoch-seconds deadline; None -> no entry gate.  The
                  remaining budget is threaded into ``fetch_json`` so its
                  ``urlopen`` timeout shrinks with it (S1-5) instead of always
                  allowing the fixed ``REQUEST_TIMEOUT``.

    Returns dict: {latest: {...}, recent: [...]} on success, or
    {'latest': None, 'recent': []} when the upstream has no data.
    Raises FetchError (the only failure type) — handle_margin degrades it.

    A `market` outside :data:`VALID_MARKETS` is rejected **before the URL is
    built** (`FetchError('upstream_error')`, no network): the value is
    interpolated into a path segment, so unvalidated input could otherwise
    inject same-host paths/queries and mint one cache key per bogus value.

    PRF-LAT-02: a TTL-fresh entry in the process-local ``_margin_cache``
    short-circuits both the URL fetch *and* the ``upstream_fetch_total`` count
    (the gauge tracks fetch-path invocations, i.e. terminal-cache misses).
    Nothing is cached on a failure or a "no data" payload — only a usable
    ``latest`` row is stored, so a degraded body can never be served.
    """
    if market not in VALID_MARKETS:                               # §2.1 enum gate
        raise FetchError('upstream_error', url=_MARGIN_URL)
    url = f'{_MARGIN_URL}/{market}/'
    policy = cache_policy('margin')                               # BR-MKT-1 (no bare ttl)
    ttl = policy['ttl']
    if deadline is not None and time.time() >= deadline:          # BR-MKT-3: no network
        raise FetchError('upstream_timeout', url=url)

    # Terminal cache lookup (TTL hit -> move_to_end, no parse / no count).
    now = time.time()
    with _margin_cache_lock:
        cached = _margin_cache.get(market)
        hit = cached is not None and now - _margin_cache_ts.get(market, 0) < ttl
        if hit:
            _margin_cache.move_to_end(market)                     # true LRU
        entries = len(_margin_cache)                              # 锁内取长度
    if hit:
        # Publish out-of-lock (metrics is a leaf lock): keeps the gauge honest
        # even when a hit is the only thing that touched the cache.
        metrics.set_gauge('cache_entries', entries, key='margin')
        return cached

    metrics.incr('upstream_fetch_total', key='margin')            # BR-MKT-9 (miss only)
    try:
        raw = json.loads(                                                 # BR-MKT-2
            fetch_json(url, _MARGIN_HEADERS, ttl=ttl, deadline=deadline))
    except FetchError:
        raise                                                     # BR-MKT-8: cache counted
    except Exception as exc:                                      # JSON decode etc.
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url, cause=exc) from exc

    if not isinstance(raw, dict):                                 # BR-MKT-5: no data
        return {'latest': None, 'recent': []}
    if raw.get('status_code') != 0:                               # BR-MKT-4: semantic fail
        metrics.incr('upstream_fail_total', key='upstream_error')
        raise FetchError('upstream_error', url=url)
    payload = _transform_margin(raw.get('data') or {})
    if payload['latest'] is not None:                             # usable data only
        cache_max = policy['cache_max']
        with _margin_cache_lock:
            _margin_cache[market] = payload
            _margin_cache_ts[market] = now                        # TTL base
            _margin_cache.move_to_end(market)                     # BR-MKT-15
            while len(_margin_cache) > cache_max:
                victim, _ = _margin_cache.popitem(last=False)     # true LRU
                _margin_cache_ts.pop(victim, None)
            entries = len(_margin_cache)                          # 锁内取长度
        # Publish out-of-lock, matching stock_api._cache_store (BR-SA-26) so
        # every terminal cache in the repo reports cache_entries{domain}.
        metrics.set_gauge('cache_entries', entries, key='margin')
    return payload


def _to_float(val):
    """Best-effort float for one upstream numeric cell.

    Missing sentinels (``None`` / ``'--'`` / blank) and unparseable junk all
    degrade to ``0.0`` *per field* (P2-8): previously ``float(val)`` raised out
    of the transform and ``handle_margin`` degraded the whole response to zeros,
    so one dirty row erased every valid row.
    """
    if val is None or val == '--' or val == '':
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _transform_margin(data):
    """Convert 同花顺 raw margin data into unified format.

    Raw: {'date': [...], 'item': [{'rzye': ..., 'rqye': ..., ...}, ...]}
    Signature and numeric semantics unchanged; non-dict input degrades and every
    numeric field is normalised independently (P2-7/P2-8): the ``'--'`` sentinel
    never reaches a numeric field, and one dirty cell cannot void the response.
    """
    if not isinstance(data, dict):
        return {'latest': None, 'recent': []}
    dates = data.get('date') or []
    items = data.get('item') or []
    if not dates or not items:
        return {'latest': None, 'recent': []}

    def to_100m(val):
        return round(_to_float(val) / 100_000_000, 4)

    def fmt(i):
        item = items[i] if isinstance(items[i], dict) else {}
        return {
            'date': dates[i],
            'rzye': to_100m(item.get('rzye', 0)),     # 融资余额(亿)
            'rqye': to_100m(item.get('rqye', 0)),     # 融券余额(亿)
            'rzmre': to_100m(item.get('rzmre', 0)),   # 融资买入额(亿)
            'rzjmr': to_100m(item.get('rzjmr', 0)),   # 融资净买入(亿)
            'rqjmc': to_100m(item.get('rqjmc', 0)),   # 融券净卖出(亿)
            'lr': to_100m(item.get('lr', 0)),         # 两融余额(亿)
            'zb': _to_float(item.get('zb', 0)),       # 占比(小数) — floats like the rest
        }

    n = min(len(dates), len(items))
    return {
        'latest': fmt(n - 1) if n > 0 else None,
        'recent': [fmt(i) for i in range(max(0, n - 30), n)],
    }


def handle_margin(market='99'):
    """Handler: margin data — total function, never raises (BR-MKT-6)."""
    try:
        return fetch_margin(market)
    except FetchError as exc:
        return _degraded(exc.kind)
    except Exception as exc:                                      # defensive fallback
        log.warning('[margin] unexpected error: %s', exc)
        metrics.incr('upstream_fail_total', key='upstream_error')
        return _degraded('upstream_error')
