"""Market-level data APIs: 融资融券 (margin), 北向资金 (northbound).

Both sourced from 同花顺 data center (public REST APIs, no auth needed).
"""

import json

from config import (
    _MARGIN_URL, _MARGIN_HEADERS, _MARGIN_CACHE_TTL,
    _NORTHBOUND_SNAPSHOT_URL, _NORTHBOUND_HISTORY_URL,
    _NORTHBOUND_HEADERS, _NORTHBOUND_CACHE_TTL,
)
from cache import fetch_json


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

    n = len(items)
    return {
        'latest': fmt(n - 1) if n > 0 else None,
        'recent': [fmt(i) for i in range(max(0, n - 30), n)],
    }


def handle_margin(market='99'):
    """Handler: margin data — fetch_json provides built-in caching."""
    return fetch_margin(market)


# ── 北向资金 (Northbound Capital / 沪深港通) ─────────────────────────────────


def fetch_northbound():
    """Fetch northbound capital snapshot (实时快照).

    Returns dict with sh/sz details + total_net_inflow + total_net_buy.
    On failure, returns degraded response with _error field.
    """
    try:
        raw = json.loads(fetch_json(_NORTHBOUND_SNAPSHOT_URL, _NORTHBOUND_HEADERS,
                                    ttl=_NORTHBOUND_CACHE_TTL))
        if raw.get('status_code') != 0:
            raise ValueError(f"API error: {raw.get('status_msg', 'unknown')}")
        return _transform_northbound(raw['data'])
    except Exception as e:
        return {
            'sh': {'net_inflow': 0, 'buy_turnover': 0, 'sell_turnover': 0},
            'sz': {'net_inflow': 0, 'buy_turnover': 0, 'sell_turnover': 0},
            'total_net_inflow': 0, 'total_net_buy': 0,
            'update_date': '', '_error': str(e),
        }


def fetch_northbound_history(period='day'):
    """Fetch northbound capital history.

    Args:
        period: 'day' | 'week' | 'month' | 'quarter' | 'year'

    Returns raw JSON from 同花顺 (dates + data arrays).
    """
    if period not in ('day', 'week', 'month', 'quarter', 'year'):
        period = 'day'
    url = f'{_NORTHBOUND_HISTORY_URL}/{period}/'
    try:
        raw = json.loads(fetch_json(url, _NORTHBOUND_HEADERS, ttl=_NORTHBOUND_CACHE_TTL))
        return raw
    except Exception as e:
        return {'dates': [], 'data': [], '_error': str(e)}


def _transform_northbound(data):
    """Convert 同花顺 raw northbound data into unified format."""
    h = data.get('h') or {}
    s = data.get('s') or {}
    mv = data.get('market_value') or {}

    def _loc(d):
        return {
            'net_inflow': d.get('zjlr', 0),
            'remaining_quota': d.get('syed', 0),
            'total_quota': d.get('zed', 0),
            'buy_turnover': d.get('buy_turnover', 0),
            'sell_turnover': d.get('sell_turnover', 0),
            'net_turnover': d.get('net_turnover', 0),
            'state': d.get('state', ''),
            'up_stocks': d.get('up', 0),
            'mid_stocks': d.get('mid', 0),
            'down_stocks': d.get('down', 0),
        }

    return {
        'sh': _loc(h),
        'sz': _loc(s),
        'total_net_inflow': data.get('jlr', 0),
        'total_net_buy': data.get('jmr', 0),
        'update_date': mv.get('data_update_date', ''),
        'unit': mv.get('unit', '元'),
    }


def handle_northbound():
    """Handler: northbound snapshot — fetch_json provides built-in caching."""
    return fetch_northbound()


def handle_northbound_history(period='day'):
    """Handler: northbound history — fetch_json provides built-in caching."""
    return fetch_northbound_history(period)
