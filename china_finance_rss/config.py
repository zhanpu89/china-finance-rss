"""Configuration, constants, and shared globals for the RSS bridge.

Single authority for TTL / pool limits / endpoint cache limits / upstream
encoding (:func:`cache_policy`), the trading-hours time source, and every
env-registered IO/resource budget.  Imports stdlib only (``os`` / ``re`` /
``datetime`` / ``urllib.parse``) and never imports a ``china_finance_rss``
module (layerIsolation).
"""

import os
import re
from datetime import datetime, timezone, timedelta
from types import MappingProxyType
from urllib.parse import urlsplit

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

# Upstream HTTP transport (cache.fetch_json — the sole HTTP egress).  A
# kept-alive connection removes the per-request TCP+TLS handshake and the DNS
# lookup (measured 340ms/request → 48ms reused on the 2C2G node).  These bound
# the per-host pool, evict idle sockets, and cache name→address lookups.
# HTTP_POOL_MAX_PER_HOST is per (scheme, host, port); excess concurrent
# requests use short-lived connections rather than blocking.  Must stay
# >= BATCH_MAX_WORKERS: a narrower pool would queue the batch fan-out on the
# pool itself and make the capacity model's worker count unreachable
# (BUG-SSE-DEPTH-01).  24 leaves headroom over the 20-wide batch phase.
HTTP_POOL_MAX_PER_HOST = int(os.getenv('HTTP_POOL_MAX_PER_HOST', '24'))
HTTP_POOL_IDLE_TTL = float(os.getenv('HTTP_POOL_IDLE_TTL', '60'))
HTTP_DNS_CACHE_TTL = float(os.getenv('HTTP_DNS_CACHE_TTL', '300'))

# Process-start transport pre-warm (`cache.warm_transport`).  The first refresh
# of a cold process is otherwise fully cold — empty connection pool and empty
# DNS cache — so a 50-code quote fan-out pays every TCP/TLS handshake and name
# lookup at once (measured ≈4.2 s, over the 0.8×tick budget).  Pre-dialing one
# connection per SSE hot-path host (and thereby filling `_DNSResolver`) removes
# that one-off cost.  Warming dials transport only — it issues no business
# request.  The timeout bounds a single dial; warming runs on a startup daemon
# thread and can never gate startup or `/healthz`.
HTTP_WARM_CONNECTIONS = int(os.getenv('HTTP_WARM_CONNECTIONS', '1'))
HTTP_WARM_TIMEOUT = float(os.getenv('HTTP_WARM_TIMEOUT', '2.0'))

# SSE refresh capacity model — the two calibration inputs behind
# `stream.refresh_capacity` (BR-STR-16).  Registered here (config.md §1.1 env
# 注册中心) so the model can be retuned per deployment without a code change;
# `stock_api`/`stream` read them once at import and keep their module-level
# names (`BATCH_MAX_WORKERS` / `_PER_FETCH_EST`) unchanged.
#
# BATCH_MAX_WORKERS: bounded parallelism of one batch phase — both
# `stock_api._run_batch` and the per-field phase in `stream._refresh_pool`.
# 20 is aligned with HTTP_POOL_MAX_PER_HOST (24, so the fan-out never queues
# on the per-host pool) and is sized by the SSE capacity model: at the
# quote-driven tick=4, coverage = int(0.8 × 4 × 20 / 0.3) = 213 fetch-calls,
# so 50 codes × 4 calls/code = 200 fit one C1 refresh (BUG-SSE-DEPTH-01: at
# 16 workers coverage_codes was 42 < 50, forcing a 2-tick C2 shard and a
# 12.33 s cold first frame).  The upstream tolerated 48 concurrent in the r5
# measurement (no throttling observed).
BATCH_MAX_WORKERS = int(os.getenv('BATCH_MAX_WORKERS', '20'))
# STREAM_PER_FETCH_EST: serial-equivalent seconds one upstream REST call
# occupies one batch worker.  Recalibrated (r5) to the pool-warmed path:
# `cache.fetch_json` keep-alive pooling + cached DNS took single-request
# latency to 139 ms p50 / 167 ms max (from 340 ms), so 0.3 leaves ≈2.2×
# headroom for concurrency queueing, upstream jitter and a cold first call.
# The previous 2.2 priced the pre-pooling cold path and over-estimated the
# per-call cost ≈16×, capping SSE coverage so 50 codes could not refresh
# within one 8 s tick.
STREAM_PER_FETCH_EST = float(os.getenv('STREAM_PER_FETCH_EST', '0.3'))

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

    Canonical form is the **internal identity key** — the lowercase
    exchange-prefixed spelling: ``sh600519`` / ``sz000001`` / ``bj430047``.
    Accepted inputs (case-insensitive, surrounding whitespace stripped):

      * ``sh600519`` / ``SH600519``
      * ``600519.SH`` / ``000001.SZ`` / ``430047.BJ``

    Anything else (non-str, blank, wrong length, unknown exchange) returns
    ``None``; callers decide whether that is a rejection (HTTP/stream ingress)
    or a ``cdp_unavailable`` count (CDP mismatch).  Every ingress and every
    cache/pool/ledger key must go through this helper so one stock cannot mint
    two identities.

    This key is deliberately **not** always the upstream wire spelling:
    x-quote accepts the prefixed form for SH/SZ but the dotted ``430047.BJ``
    form for BSE, so URL construction goes through :func:`upstream_secu_code`.
    Keeping the identity fixed while only URL construction converts is what
    lets one stock stay one pool/cache/ledger key.

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


def upstream_secu_code(code):
    """Return the ``secu_code`` spelling x-quote.cls.cn actually accepts.

    Upstream accepts **two different formats**, measured against
    ``https://x-quote.cls.cn/quote/stock/{basic,volume,detail}``:

      * **Shanghai / Shenzhen** — the lowercase exchange-prefixed form, i.e.
        the canonical code itself: ``sh600519`` / ``sz000001``.  The dotted
        form (``600519.SH``) returns an all-null "empty shell" (basic) or an
        empty ``data`` dict (volume).
      * **Beijing (北交所 / BSE)** — the dotted, uppercase-suffixed form
        ``430047.BJ`` / ``832000.BJ``.  The prefixed form (``bj430047``)
        returns that same all-null shell, which is why every BSE quote used to
        arrive blank while SH/SZ stayed healthy.

    ``code`` is the internal canonical form (:func:`canonical_code` — the
    pool/cache/ledger identity key, whose value domain is unchanged).  This
    helper is the **single authority** for the upstream spelling, so the
    conversion lives only in URL construction and the identity never forks.
    An unrecognised input is returned verbatim (ingress already validates).
    """
    canon = canonical_code(code)
    if canon is None:
        return code
    if canon.startswith('bj'):
        return f'{canon[2:]}.BJ'
    return canon


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

# Five-level order book REST API (direct access, no CDP / no sign).
# `field=five` selects the 21-field five-band payload; the same endpoint
# without it serves volume aggregates.  `secu_code` must be the upstream wire
# spelling from `upstream_secu_code` (prefixed `sh600519` for SH/SZ, but the
# dotted `430047.BJ` for BSE — the prefixed BSE form returns an empty dict).
_STOCK_DEPTH_URL = 'https://x-quote.cls.cn/quote/stock/volume'
_STOCK_DEPTH_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Stock detail REST API (direct access, no CDP needed)
_STOCK_DETAIL_BASE_URL = 'https://x-quote.cls.cn/quote/stock/detail'
_STOCK_DETAIL_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# Company info REST API (needs in-browser auth via CDP evaluate_fetch)
_COMPANY_INFO_BASE_URL = 'https://x-quote.cls.cn/quote/stock/company_info'
_COMPANY_INFO_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/stock'}

# SSE hot-path upstream URLs: the domains a quote/fundflow/timeline subscription
# refreshes every tick.  `warm_hosts()` derives the transport keys from these
# constants, so moving an upstream can never leave the warm list stale.
_SSE_HOT_PATH_URLS = (
    _BASIC_INFO_BASE_URL, _STOCK_DEPTH_URL, _STOCK_DETAIL_BASE_URL,
    _FUNDFLOW_BASE_URL, _TIMELINE_BASE_URL,
)


def warm_hosts():
    """Distinct ``(scheme, host, port)`` of the SSE hot-path upstreams.

    Derived from ``_SSE_HOT_PATH_URLS`` (the URL constants are the single
    authority), deduped, in a stable order.  Consumed by ``cache.warm_transport``
    so the pre-warm follows the configured upstreams instead of a host literal.
    """
    seen, out = set(), []
    for url in _SSE_HOT_PATH_URLS:
        parsed = urlsplit(url)
        key = (parsed.scheme, parsed.hostname,
               parsed.port or (443 if parsed.scheme == 'https' else 80))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return tuple(out)


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


# PRF-MEM-01（2026-09-20）每域池上限 —— env 注册（BR-CFG-16 / §1.1#5）。
# 池是 code→最近触碰时刻 的廉价账本，上限决定该域 prefetch 轮转覆盖多少码；
# 在此注册使部署可免改码调参。终端缓存 cache_max 才是真实内存界，按既有模式
# 保持为矩阵内的整数字面量（与其余 9 域一致）。
MAX_QUOTE_POOL = int(os.getenv('MAX_QUOTE_POOL', '1000'))
MAX_FUNDFLOW_POOL = int(os.getenv('MAX_FUNDFLOW_POOL', '1000'))
MAX_TIMELINE_POOL = int(os.getenv('MAX_TIMELINE_POOL', '500'))
# 名单与取值同源：键即唯一合法 NAME，值即冻结的池上限（新增 env 只改这里一处）。
# 池上限的注册映射在导入期建成并冻结（MappingProxyType）⇒ 运行期改写键/值都抛
# TypeError，池上限结构性不可被改写（BR-CFG-10）；`'dedup'` 分支仍取导入期常量
# MAX_DEDUP_CODES。未注册 NAME 一律 ValueError，与 `cache_policy` 的
# KeyError(domain) 契约解耦（不再像 globals() 那样对"白名单内但未定义"的名字抛
# KeyError——那会与 KeyError(domain) 契约撞型）。
_POOL_MAX_ENVS = MappingProxyType({
    'MAX_QUOTE_POOL': MAX_QUOTE_POOL,
    'MAX_FUNDFLOW_POOL': MAX_FUNDFLOW_POOL,
    'MAX_TIMELINE_POOL': MAX_TIMELINE_POOL,
})


# Domain cache matrix — the single authority for TTL / pool refresh / pool max /
# endpoint cache max / upstream encoding (SAD §2.1, BR-CFG-*).
#   domain -> (tier, ttl_factor, pool_refresh_factor, pool_max, cache_max)
#     ttl_factor            : float | 'override:<seconds>'
#     pool_refresh_factor   : float | 'n/a'
#     pool_max              : 'dedup' (=MAX_DEDUP_CODES) | 'fixed:<n>' | 'n/a' | 'env:<NAME>'(env 注册常量)
#     cache_max             : int | 'n/a'
# `cache_max` bounds a domain's *terminal* cache (stock_api._cache_store /
# market_api._margin_cache) or its feed cache (cache.feed_cache_put).  Domains
# served only through the shared URL cache (cache.fetch_json — plate /
# news_url / longhu) declare 'n/a': their entries are bounded by the global
# cache.MAX_CACHE_SIZE, so a per-domain int there would be a dead setting an
# operator could not act on (P2-9).  `margin` left that group (PRF-LAT-02): a
# URL-cache hit still re-ran json.loads + _transform_margin on every request
# (hot-path P50 ≈8-9ms), so it now keeps its own 8-entry terminal cache.
# 'n/a' literals are kept in the matrix for 1:1 SAD reading; cache_policy
# normalises them to None (BR-CFG-11).
# 2026-09-20 PRF-MEM-01 / PRF-MEM-02（内存调优，A/B 实测更正）：3 域 pool/cache
# 同源收缩（pool 经 env 注册可调；cache_max 1000/1000/500 为内存硬界）。实测 run
# 20260920-110805：python RSS 1.095→1.012GiB（−83MiB）、容器 1.449→1.41GiB
# ⇒ 终端缓存只是小头。纠偏：共享 URL 缓存存**解码文本**（cache.py:851-866，
# json.loads 在调用方命中后才做），仅约几十 MB，非大头（上一轮"条目存解析后
# Python 对象 / 真大头"归因已证伪）。真因＝glibc per-thread arena 碎片：33 线程
# × 默认最多 8×ncores 个 64MB arena、VmSize 8.96GB、300 个匿名 rw-p 映射；设
# MALLOC_ARENA_MAX=2（docker-compose env）后 python RSS −248MiB 至 0.772GiB、
# 容器 1.259GiB（83.95%）、VmSize 1.15GB、匿名映射 166；tier1000 timeline
# ok_rate 89.6%→100%（单次观测，或含上游波动，勿写成结论）。累计 python RSS
# 1.095→0.772GiB；仍未到 0.65GiB 级，剩余＝缓存解析对象＋运行时/分配器残余。
DOMAIN_MATRIX = {
    'quote':        ('L0', 1.0, 1.0, 'env:MAX_QUOTE_POOL', 1000),    # stock/data, basic_info, 实时价
    'depth':        ('L0', 1.0, 1.0, 'dedup', 500),                   # 五档盘口 (与 quote 同拍)
    'fundflow':     ('L1', 1.0, 1.0, 'env:MAX_FUNDFLOW_POOL', 1000),
    'timeline':     ('L1', 1.0, 1.0, 'env:MAX_TIMELINE_POOL', 500),
    'plate':        ('L2', 1.0, 1.0, 'fixed:200', 'n/a'),             # cls/hotplate, cls/plate (URL cache)
    'news_url':     ('L3', 1.0, 1.0, 'n/a', 'n/a'),                   # 5 源 RSS URL (share cache{})
    'feed':         ('L3', 1.0, 1.0, 'fixed:100', 100),
    'announcement': ('L3', 1.0, 1.0, 'dedup', 500),
    'longhu':       ('L4', 1.0, 1.0, 'n/a', 'n/a'),                   # GBK upstream, 日更 (URL cache)
    'margin':       ('L4', 2.0, 2.0, 'fixed:16', 8),                  # = 600s / 1200s (终端缓存 8)
    'f10':          ('L4', 1.0, 1.0, 'dedup', 500),
    'sector':       ('L4', 'override:604800', 'n/a', 'fixed:2000', 2000),  # 7d 行业名
}

# HTTP response compression (server._send_text).  Responses below the
# minimum size are sent raw (compression overhead not worth it); gzip
# applies only when the client advertises Accept-Encoding: gzip.
GZIP_MIN_BYTES = int(os.getenv('GZIP_MIN_BYTES', '1024'))
GZIP_COMPRESSLEVEL = int(os.getenv('GZIP_COMPRESSLEVEL', '1'))  # speed over ratio (CPU cost under 2-core stress)

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
      L0  最快    个股五档+实时价 (quote, depth) — 上游盘中 3s 一跳的物理下限
      L1  极实时  个股行情 (fundflow, timeline, basic_info)
      L2  实时    板块轮动 (hotplate, plate)
      L3  准实时  新闻快讯 (telegraph, kuaixun, flash)
      L4  参考    静态日更 (f10, margin) — unchanged

    L0 is 4s in-session (≈1.3× the upstream's measured 3.0s tick, so a 4s
    poll still sees every upstream change while halving the 8s waste).  Off
    hours it is pinned to the L1 baseline (120s) so a non-trading session never
    pays extra upstream requests for a market that is not moving.
    """
    if _is_trading_hours(now):
        return {'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}
    return {'L0': 120, 'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300}


def _resolve_int_factor(spec, base):
    """float -> round(base * factor); 'override:<n>' -> int(n) (ignores tier)."""
    if isinstance(spec, str) and spec.startswith('override:'):
        return int(spec.split(':', 1)[1])
    return int(round(base * float(spec)))


def _resolve_pool_max(spec):
    """'n/a' -> None; 'dedup' -> MAX_DEDUP_CODES; 'fixed:<n>' -> int(n);
    'env:<NAME>' -> 导入期冻结的注册表取值（未知 NAME 立即 ValueError）。"""
    if spec == 'n/a':
        return None
    if spec == 'dedup':
        return MAX_DEDUP_CODES
    if isinstance(spec, str) and spec.startswith('fixed:'):
        return int(spec.split(':', 1)[1])
    if isinstance(spec, str) and spec.startswith('env:'):
        name = spec.split(':', 1)[1]
        try:
            return int(_POOL_MAX_ENVS[name])           # 名单与值同源 + 类型归一（BR-CFG-4）
        except KeyError:
            raise ValueError(f'bad pool_max env name: {name!r}') from None
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
