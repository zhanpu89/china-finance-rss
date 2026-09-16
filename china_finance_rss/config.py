"""Configuration, constants, and shared globals for the RSS bridge.

Single authority for TTL / pool limits / endpoint cache limits / upstream
encoding (:func:`cache_policy`), the trading-hours time source, and every
env-registered IO/resource budget.  Imports stdlib only (``os`` / ``re`` /
``datetime``) and never imports a ``china_finance_rss`` module (layerIsolation).
"""

import os
import re
from datetime import datetime, timezone, timedelta

# Env-based configuration
PORT = int(os.getenv('PORT', '8053'))
STREAM_PORT = int(os.getenv('STREAM_PORT', '8054'))
STREAM_HOST = os.getenv('STREAM_HOST', '127.0.0.1')
CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '10'))
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '20'))

# Request admission / body budgets (SAD §2.2 R-1)
# MAX_INFLIGHT is derived from MAX_WORKERS so an env change to MAX_WORKERS
# keeps the 2× headroom (the '40' is no longer an implicit derivation).
MAX_INFLIGHT = int(os.getenv('MAX_INFLIGHT', str(MAX_WORKERS * 2)))
MAX_HEALTH_INFLIGHT = int(os.getenv('MAX_HEALTH_INFLIGHT', '5'))
MGMT_BODY_TIMEOUT = int(os.getenv('MGMT_BODY_TIMEOUT', '5'))

# TCP listen(2) accept backlog (BUG-P6C-03).  socketserver's default is 5,
# which overflows on burst connects: the kernel drops the SYN and the client
# retransmits after ~1s (RTO), showing up as a ~1.006s tail on AC-E1.  Must
# stay ≥ both admission caps it fronts — the main-port MAX_INFLIGHT and the
# stream MAX_STREAM_CONNS (100) — so 128 leaves headroom for both.
LISTEN_BACKLOG = int(os.getenv('LISTEN_BACKLOG', '128'))

# Negative-cache gate / half-open probe budgets (SAD §2.3 D-1, cache.md §2.1)
NEG_TTL = int(os.getenv('NEG_TTL', '5'))
PROBE_TIMEOUT = int(os.getenv('PROBE_TIMEOUT', '2'))

# Stream push (SSE) limits — 2C2G budget: 100 conns, 2000 dedup codes
MAX_STREAM_CONNS = int(os.getenv('MAX_STREAM_CONNS', '100'))
MAX_CODES_PER_SUB = int(os.getenv('MAX_CODES_PER_SUB', '200'))
MAX_DEDUP_CODES = int(os.getenv('MAX_DEDUP_CODES', '2000'))
MAX_GROUPS = int(os.getenv('MAX_GROUPS', '200'))
STREAM_PING_INTERVAL = int(os.getenv('STREAM_PING_INTERVAL', '20'))  # env (R17/S7); default 20 ⇒ socket timeout 40s
STREAM_GROUP_IDLE_TTL = float(os.getenv('STREAM_GROUP_IDLE_TTL', '300'))  # idle zombie group reaper (s)
# Distinct-frame queue budget: integer bytes only (no '128MB' suffix parsing).
STREAM_QUEUE_BYTES_BUDGET = int(os.getenv('STREAM_QUEUE_BYTES_BUDGET', str(128 * 1024 * 1024)))

# SSE frame size model — the single source for the queue-budget derivation
# (stream.md §3.4).  One distinct frame is shared by a group's connections and
# one frame per live group is retained at steady state, so the budget has to
# cover BOTH a single group's 8-deep window (8 × F_max) and the cross-group
# working set (Σ_g F_g, with live groups ≤ MAX_STREAM_CONNS).  The latter is
# enforced as an admission cap by stream.create_group / patch_group (P1-4):
# without it a perfectly legal 100×200-code subscription set would need
# ~1.4GB and force every tick to evict other groups' real frames.
STREAM_FIELDS_PER_FRAME = 3                # _FIELD_HANDLERS size (quote/fundflow/timeline)
STREAM_FRAME_BYTES_PER_FIELD = 23 * 1024   # design estimate, per code per field


def stream_frame_bytes(num_codes, num_fields):
    """Upper bound on one distinct SSE frame payload, in bytes.

    Single source of truth for the frame-size model: ``F = codes × fields ×
    STREAM_FRAME_BYTES_PER_FIELD``.  Consumers (the queue budget, the admission
    cap in ``stream.create_group``/``patch_group``) must use this helper instead
    of re-deriving the constant.
    """
    return max(0, int(num_codes)) * max(0, int(num_fields)) * STREAM_FRAME_BYTES_PER_FIELD


# Stock code validation / normalisation.
# ``VALID_STOCK_CODE`` accepts both the exchange-prefixed form (``sh600519``)
# and the dotted form (``600519.SH``).  :func:`canonical_code` is the **single
# authority** that folds both spellings into one canonical code: without it the
# same stock can mint several pools / cache keys / upstream URLs, and the CDP
# comparisons (which mix exact-equality and ``.upper()``) can only ever match
# one of the two accepted spellings (P1-6).
VALID_STOCK_CODE = re.compile(r'^(sh|sz|bj)\d{6}$|^\d{6}\.(BJ|SH|SZ)$', re.IGNORECASE)
_DOTTED_STOCK_CODE = re.compile(r'^(\d{6})\.(SH|SZ|BJ)$', re.IGNORECASE)


def canonical_code(code):
    """Return the canonical stock code, or ``None`` when ``code`` is invalid.

    Canonical form is the lowercase exchange-prefixed spelling the upstream
    ``secu_code`` parameter uses: ``sh600519`` / ``sz000001`` / ``bj430047``.
    Accepted inputs (case-insensitive, surrounding whitespace stripped):

      * ``sh600519`` / ``SH600519``
      * ``600519.SH`` / ``000001.SZ`` / ``430047.BJ``

    Anything else (non-str, blank, wrong length, unknown exchange) returns
    ``None``; callers decide whether that is a rejection (HTTP/stream ingress)
    or a ``cdp_unavailable`` count (CDP mismatch).  Every ingress and every
    cache/pool/ledger key must go through this helper so one stock cannot mint
    two identities.

    Frozen interface: ``server.py`` / ``stream.py`` consume it by this name.
    """
    if not isinstance(code, str):
        return None
    text = code.strip()
    dotted = _DOTTED_STOCK_CODE.match(text)
    if dotted:
        return f'{dotted.group(2).lower()}{dotted.group(1)}'
    lowered = text.lower()
    return lowered if VALID_STOCK_CODE.match(lowered) else None


# Batch limits
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

_PLATE_INFO_URL = 'https://x-quote.cls.cn/web_quote/plate/info'
_PLATE_STOCKS_URL = 'https://x-quote.cls.cn/web_quote/plate/stocks'
_PLATE_INDUSTRY_URL = 'https://x-quote.cls.cn/web_quote/plate/industry'
_PLATE_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/plate'}

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


# CDP page pool sizing & memory watchdog
CDP_RESTART_INTERVAL = int(os.getenv('CDP_RESTART_INTERVAL', '7200'))
# Chrome (re)start throttle in seconds: minimum gap between two ensure_chrome()
# launches, and the base of the 2x back-to-back guard in full_chrome_restart /
# watchdog_restart_skip_reason (cdp_engine). Registered here so cdp_engine does
# not read the env itself (config.md §1.1 env 注册中心).
CDP_RESTART_THROTTLE = int(os.getenv('CDP_RESTART_THROTTLE', '15'))


def stock_nav_page_names():
    """Persistent CDP stock navigation page names (cls_f10 + N stock pages).

    Kept small (default 3) — each page holds a persistent Chrome renderer
    (~150MB+). /stock/data no longer navigates, so only f10/basic_info need
    a few nav pages. Concurrency is satisfied via fair _navigate_lock queueing.

    Reads CDP_STOCK_PAGES live (not cached at import) so an env change takes
    effect without editing code; restarted container re-reads it.
    """
    count = int(os.getenv('CDP_STOCK_PAGES', '3'))
    names = ['cls_f10', 'cls_stock']
    i = 2
    while len(names) < count:
        names.append(f'cls_stock_{i}')
        i += 1
    return tuple(names)


# Domain cache matrix — the single authority for TTL / pool refresh / pool max /
# endpoint cache max / upstream encoding (SAD §2.1, BR-CFG-*).
#   domain -> (tier, ttl_factor, pool_refresh_factor, pool_max, cache_max)
#     ttl_factor            : float | 'override:<seconds>'
#     pool_refresh_factor   : float | 'n/a'
#     pool_max              : 'dedup' (=MAX_DEDUP_CODES) | 'fixed:<n>' | 'n/a'
#     cache_max             : int | 'n/a'
# `cache_max` bounds a domain's *terminal* cache (stock_api._cache_store) or its
# feed cache (cache.feed_cache_put).  Domains served only through the shared URL
# cache (cache.fetch_json — plate / news_url / longhu / margin) declare 'n/a':
# their entries are bounded by the global cache.MAX_CACHE_SIZE, so a per-domain
# int there would be a dead setting an operator could not act on (P2-9).
# 'n/a' literals are kept in the matrix for 1:1 SAD reading; cache_policy
# normalises them to None (BR-CFG-11).
DOMAIN_MATRIX = {
    'quote':        ('L1', 1.0, 1.0, 'dedup', 2000),                  # stock/data, basic_info, 实时价
    'fundflow':     ('L1', 1.0, 1.0, 'dedup', 2000),
    'timeline':     ('L1', 1.0, 1.0, 'dedup', 2000),
    'plate':        ('L2', 1.0, 1.0, 'fixed:200', 'n/a'),             # cls/hotplate, cls/plate (URL cache)
    'news_url':     ('L3', 1.0, 1.0, 'n/a', 'n/a'),                   # 5 源 RSS URL (share cache{})
    'feed':         ('L3', 1.0, 1.0, 'fixed:100', 100),
    'announcement': ('L3', 1.0, 1.0, 'dedup', 500),
    'longhu':       ('L4', 1.0, 1.0, 'n/a', 'n/a'),                   # GBK upstream, 日更 (URL cache)
    'margin':       ('L4', 2.0, 2.0, 'fixed:16', 'n/a'),              # = 600s / 1200s (URL cache)
    'f10':          ('L4', 1.0, 1.0, 'dedup', 500),
    'sector':       ('L4', 'override:604800', 'n/a', 'fixed:2000', 2000),  # 7d 行业名
}

# Only domains whose upstream is not utf-8 declare an encoding here.
_DOMAIN_ENCODING = {'longhu': 'gbk'}

# Shared runtime globals (set by server.py init)
cdp_engine = None
jin10_public_headers = None


def _parse_holidays(raw):
    """Parse a comma-separated ``YYYY-MM-DD`` list into a frozenset of dates.

    Blank tokens are skipped; a malformed date raises ``ValueError`` at import
    time (fail-fast, consistent with the other env parsing here).
    """
    days = set()
    for token in (raw or '').split(','):
        token = token.strip()
        if token:
            days.add(datetime.strptime(token, '%Y-%m-%d').date())
    return frozenset(days)


# Market holidays (env ``TRADING_HOLIDAYS``, e.g. '2026-10-01,2026-10-02').
# Empty by default ⇒ _is_trading_hours() is unchanged (weekday + session only).
TRADING_HOLIDAYS = _parse_holidays(os.getenv('TRADING_HOLIDAYS', ''))


def _is_trading_hours(now=None):
    """Return True if the CST time is within China A-share trading hours.

    ``now`` is an epoch-seconds injection point (default: current clock).  With
    ``now=None`` behaviour is byte-for-byte identical to the previous zero-arg
    version, so existing callers are unaffected.

    ``TRADING_HOLIDAYS`` (env ``TRADING_HOLIDAYS``, comma-separated
    ``YYYY-MM-DD`` dates, empty by default) names closed market days: a
    configured holiday is treated as off-hours, so the system does not poll at
    the in-session cadence on a closed day and the CDP watchdog may restart
    Chrome instead of holding off all day.
    """
    if now is None:
        now_cst = datetime.now(timezone.utc) + timedelta(hours=8)
    else:
        now_cst = datetime.fromtimestamp(now, timezone.utc) + timedelta(hours=8)
    if now_cst.date() in TRADING_HOLIDAYS:                          # configured holiday
        return False
    if now_cst.weekday() >= 5:
        return False
    h, m = now_cst.hour, now_cst.minute
    in_morning = (h == 9 and m >= 30) or (10 <= h <= 10) or (h == 11 and m <= 30)
    in_afternoon = (13 <= h <= 14)
    return in_morning or in_afternoon


def _trading_tiers(now=None):
    """Return dict of tier base TTLs for the given (or current) trading status.

    Tiers (short-line trading priority):
      L1  极实时  个股行情 (fundflow, timeline, basic_info)
      L2  实时    板块轮动 (hotplate, plate)
      L3  准实时  新闻快讯 (telegraph, kuaixun, flash)
      L4  参考    静态日更 (f10, margin) — unchanged
    """
    if _is_trading_hours(now):
        return {'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}
    return {'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}


def _resolve_int_factor(spec, base):
    """float -> round(base * factor); 'override:<n>' -> int(n) (ignores tier)."""
    if isinstance(spec, str) and spec.startswith('override:'):
        return int(spec.split(':', 1)[1])
    return int(round(base * float(spec)))


def _resolve_pool_max(spec):
    """'n/a' -> None; 'dedup' -> MAX_DEDUP_CODES; 'fixed:<n>' -> int(n)."""
    if spec == 'n/a':
        return None
    if spec == 'dedup':
        return MAX_DEDUP_CODES
    if isinstance(spec, str) and spec.startswith('fixed:'):
        return int(spec.split(':', 1)[1])
    raise ValueError(f'bad pool_max spec: {spec!r}')


def _materialize(domain, matrix_row, tiers):
    """Build one policy dict (fresh object) from a DOMAIN_MATRIX row."""
    tier, ttl_factor, refresh_factor, pool_max_spec, cache_max_spec = matrix_row
    base = tiers[tier]                                            # BR-CFG-1
    ttl = _resolve_int_factor(ttl_factor, base)                   # BR-CFG-2
    if refresh_factor == 'n/a':                                   # BR-CFG-3
        pool_refresh = None
    else:
        # factor >= 1.0 by construction ⇒ pool_refresh >= ttl (INV-1a落点 1)
        pool_refresh = int(round(ttl * float(refresh_factor)))
    policy = {
        'tier': tier,
        'ttl': ttl,
        'pool_refresh': pool_refresh,
        'pool_max': _resolve_pool_max(pool_max_spec),             # BR-CFG-4
        'cache_max': None if cache_max_spec == 'n/a' else int(cache_max_spec),  # BR-CFG-5/11
    }
    enc = _DOMAIN_ENCODING.get(domain)                            # BR-CFG-7
    if enc is not None:
        policy['encoding'] = enc
    return policy


def cache_policy(domain, now=None):
    """Return the fresh cache/TTL policy dict for ``domain`` (SAD §2.1, INV-1a).

    Keys are fixed: ``tier`` / ``ttl`` / ``pool_refresh`` / ``pool_max`` /
    ``cache_max`` (+ ``encoding`` only for non-utf-8 domains).  Unknown domains
    raise ``KeyError`` — there is deliberately no default-domain fallback.
    """
    if domain not in DOMAIN_MATRIX:                               # BR-CFG-8
        raise KeyError(
            f'unknown cache domain {domain!r}; known: {sorted(DOMAIN_MATRIX)}')
    tiers = _trading_tiers(now)                                   # BR-CFG-9: once per call
    return _materialize(domain, DOMAIN_MATRIX[domain], tiers)     # BR-CFG-10: fresh dict
