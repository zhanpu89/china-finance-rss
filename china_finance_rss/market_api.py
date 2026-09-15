"""Market-level data APIs: 融资融券 (margin).

Sourced from 同花顺 data center (public REST APIs, no auth needed).
"""

import json

from .config import (
    _MARGIN_URL, _MARGIN_HEADERS, _MARGIN_CACHE_TTL,
)
from .cache import fetch_json




# ── 融资融券 (Margin / Securities Lending) ─────────────────────────────────


def fetch_margin(market='99'):
    """Fetch margin data for a given market.

    Args:
        market: '99'=合计(total), '1'=沪市(SH), '2'=深市(SZ), '3'=京市(BJ)

    Returns dict: {latest: {rzye, rqye, ...}, recent: [{...}, ...]}
    On failure, returns degraded response with all-zeros and _error field.
    """
    url = f'{_MARGIN_URL}/{market}/'
    try:
        raw = json.loads(fetch_json(url, _MARGIN_HEADERS, ttl=_MARGIN_CACHE_TTL))
        if raw.get('status_code') != 0:
            raise ValueError(f"API error: {raw.get('status_msg', 'unknown')}")
        return _transform_margin(raw['data'])
    except Exception as e:
        return {
            'latest': {'rzye': 0, 'rqye': 0, 'rzmre': 0,
                       'rzjmr': 0, 'rqjmc': 0, 'lr': 0, 'zb': 0},
            'recent': [],
            '_error': str(e),
        }


def _transform_margin(data):
    """Convert 同花顺 raw margin data into unified format.

    Raw: {'date': [...], 'item': [{'rzye': ..., 'rqye': ..., ...}, ...]}
    """
    dates = data.get('date') or []
    items = data.get('item') or []
    if not dates or not items:
        return {'latest': None, 'recent': []}

    def to_100m(val):
        if val is None or val == '--':
            return 0.0
        return round(float(val) / 100_000_000, 4)

    def fmt(i):
        item = items[i]
        return {
            'date': dates[i],
            'rzye': to_100m(item.get('rzye', 0)),     # 融资余额(亿)
            'rqye': to_100m(item.get('rqye', 0)),     # 融券余额(亿)
            'rzmre': to_100m(item.get('rzmre', 0)),   # 融资买入额(亿)
            'rzjmr': to_100m(item.get('rzjmr', 0)),   # 融资净买入(亿)
            'rqjmc': to_100m(item.get('rqjmc', 0)),   # 融券净卖出(亿)
            'lr': to_100m(item.get('lr', 0)),         # 两融余额(亿)
            'zb': item.get('zb', 0),                  # 占比(小数)
        }

    n = min(len(dates), len(items))
    return {
        'latest': fmt(n - 1) if n > 0 else None,
        'recent': [fmt(i) for i in range(max(0, n - 30), n)],
    }


def handle_margin(market='99'):
    """Handler: margin data — fetch_json provides built-in caching."""
    return fetch_margin(market)
