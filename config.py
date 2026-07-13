"""Configuration, constants, and shared globals for the RSS bridge."""

import os
import re
from datetime import datetime, timezone, timedelta

# Env-based configuration
PORT = int(os.getenv('PORT', '8053'))
CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')
CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '10'))
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '20'))

# Stock code validation
VALID_STOCK_CODE = re.compile(r'^(sh|sz|bj)\d{6}$', re.IGNORECASE)

# Cache & batch limits
_MAX_CACHE_AGE = 120
_MAX_BATCH_SIZE = 50

# Expected CDP data keys per page
_FINANCE_EXPECTED_KEYS = frozenset({
    'market_sentiment', 'articles', 'advance_decline',
    'live_refresh', 'anchor', 'basic_info',
})

_QUOTATION_EXPECTED_KEYS = frozenset({
    'hot_plate', 'stock_ranking', 'stock_ipo',
    'bj_stock_info', 'index_home', 'basic_info',
})

_STOCK_EXPECTED_KEYS = frozenset({
    'articles', 'stock_plate',
    'stock_announcement', 'stock_detail',
})

_F10_EXPECTED_KEYS = frozenset({
    'stock_company_info',
})

# API URLs and headers
_HOTPLATE_BASE_URL = 'https://x-quote.cls.cn/web_quote/plate/plate_list'
_HOTPLATE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/hotplate'}

_FUNDFLOW_BASE_URL = 'https://x-quote.cls.cn/quote/stock/fundflow'
_FUNDFLOW_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

_TIMELINE_BASE_URL = 'https://x-quote.cls.cn/quote/stock/tline'
_TIMELINE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

_F10_BASE_URL = 'https://x-quote.cls.cn/quote/stock/f10'
_F10_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Pool refresh intervals and caps
_FUNDFLOW_POOL_REFRESH = 25
_FUNDFLOW_MAX_POOL = 500
_TIMELINE_POOL_REFRESH = 30
_TIMELINE_MAX_POOL = 300
_F10_POOL_REFRESH = 60
_F10_MAX_POOL = 300
_BASIC_INFO_POOL_REFRESH = 120
_BASIC_INFO_MAX_POOL = 300

# Shared runtime globals (set by server.py init)
cdp_engine = None
jin10_public_headers = None


def _china_trading_ttl():
    """Return (base_ttl, stagger_step) for China A-share trading status.

    Trading hours (Mon-Fri, UTC+8): 09:30-11:30, 13:00-15:00.
    During trading → short TTL (30s). Outside → normal TTL (300s).
    """
    now_utc = datetime.now(timezone.utc)
    now_cst = now_utc + timedelta(hours=8)
    if now_cst.weekday() >= 5:
        return (300, 90)
    h, m = now_cst.hour, now_cst.minute
    in_morning = (h == 9 and m >= 30) or (10 <= h <= 10) or (h == 11 and m <= 30)
    in_afternoon = (13 <= h <= 14)
    if in_morning or in_afternoon:
        return (30, 15)
    return (300, 90)
