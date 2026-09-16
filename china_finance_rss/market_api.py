"""Market-level data APIs: 融资融券 (margin).

Sourced from 同花顺 data center (public REST APIs, no auth needed).

TTL is derived from ``config.cache_policy('margin')`` only; fetching goes
through ``cache.fetch_json`` only. Failures are classified as
``cache.FetchError(kind)`` and surface as an enumerated ``_error`` code.
"""

import json
import logging
import time

from . import metrics
from .cache import FetchError, fetch_json
from .config import _MARGIN_HEADERS, _MARGIN_URL, cache_policy

log = logging.getLogger('market')

# Contract enum for `market` (market_api.md §2.1 / server.md §2.1 OpenAPI):
# '99'=合计(total) / '1'=沪市(SH) / '2'=深市(SZ) / '3'=京市(BJ).
# Single authority — server.py imports this for its boundary check, so the
# enum cannot drift between the routing layer and the URL builder.
VALID_MARKETS = ('99', '1', '2', '3')

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
    """
    if market not in VALID_MARKETS:                               # §2.1 enum gate
        raise FetchError('upstream_error', url=_MARGIN_URL)
    url = f'{_MARGIN_URL}/{market}/'
    ttl = cache_policy('margin')['ttl']                           # BR-MKT-1 (no bare ttl)
    if deadline is not None and time.time() >= deadline:          # BR-MKT-3: no network
        raise FetchError('upstream_timeout', url=url)

    metrics.incr('upstream_fetch_total', key='margin')            # BR-MKT-9
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
    return _transform_margin(raw.get('data') or {})


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
