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
VALID_STOCK_CODE = re.compile(r'^(sh|sz|bj)\d{6}$|^\d{6}\.(BJ|SH|SZ)$', re.IGNORECASE)

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

_ANNOUNCEMENT_BASE_URL = 'https://x-quote.cls.cn/quote/index/ann'
_ANNOUNCEMENT_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Basic info REST API (direct access, no CDP needed)
_BASIC_INFO_BASE_URL = 'https://x-quote.cls.cn/quote/stock/basic'
_BASIC_INFO_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Stock detail REST API (direct access, no CDP needed)
_STOCK_DETAIL_BASE_URL = 'https://x-quote.cls.cn/quote/stock/detail'
_STOCK_DETAIL_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Company info REST API (needs in-browser auth via CDP evaluate_fetch)
_COMPANY_INFO_BASE_URL = 'https://x-quote.cls.cn/quote/stock/company_info'
_COMPANY_INFO_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# 同花顺 data center APIs (public, no auth)
_TENJQKA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/125.0.0.0 Safari/537.36',
    'Referer': 'https://data.10jqka.com.cn/',
}

# 融资融券 (Margin / Securities Lending)
_MARGIN_URL = 'https://data.10jqka.com.cn/rzrq/fixdata/type'
_MARGIN_HEADERS = {**_TENJQKA_HEADERS, 'Referer': 'https://data.10jqka.com.cn/market/rzrq/'}
_MARGIN_CACHE_TTL = 600  # 10 min — data updates once per trading day

# 北向资金 (Northbound Capital /沪深港通)
_NORTHBOUND_SNAPSHOT_URL = 'https://data.10jqka.com.cn/hsgt/basedata/type/north/'
_NORTHBOUND_HISTORY_URL = 'https://data.10jqka.com.cn/hsgt/history/type/north/date'
_NORTHBOUND_HEADERS = {**_TENJQKA_HEADERS, 'Referer': 'https://data.10jqka.com.cn/hsgt/'}
_NORTHBOUND_CACHE_TTL = 300  # 5 min

# Pool refresh intervals and caps
_FUNDFLOW_POOL_REFRESH = 25
_FUNDFLOW_MAX_POOL = 500
_TIMELINE_POOL_REFRESH = 30
_TIMELINE_MAX_POOL = 300
_F10_POOL_REFRESH = 60
_F10_MAX_POOL = 300
_BASIC_INFO_POOL_REFRESH = 120
_BASIC_INFO_MAX_POOL = 300
_ANNOUNCEMENT_POOL_REFRESH = 60
_ANNOUNCEMENT_MAX_POOL = 300

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
