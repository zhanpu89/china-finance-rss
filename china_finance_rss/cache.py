"""URL fetch cache with stampede protection, negative cache, feed cache and
the batch-response contract assembler (cache.md v1.1).

Layer-0 pure cache/contract layer: imports only stdlib + ``config`` + ``metrics``.
It never imports ``server`` / ``stream`` / ``stock_api`` / ``market_api``.
"""

import atexit
import http.client
import logging
import random
import socket
import threading
import time
import urllib.error
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit
from urllib.request import Request

from . import metrics
from .config import (HTTP_DNS_CACHE_TTL, HTTP_POOL_IDLE_TTL,
                     HTTP_POOL_MAX_PER_HOST, HTTP_WARM_CONNECTIONS,
                     HTTP_WARM_TIMEOUT, NEG_TTL, PROBE_TIMEOUT,
                     REQUEST_TIMEOUT, cache_policy, warm_hosts)

log = logging.getLogger('cache')

# Generic URL fetch cache. OrderedDict ⇒ true LRU (move_to_end on hit,
# popitem(last=False) on eviction). 2000 ≈ 200 max user codes × 4 URL variants
# × 2.5 headroom (a full watchlist tick touches ~600-800 entries; 200 would
# flush the cache every round → ~0 hit rate). Each entry ~10KB → ~20MB.
cache = OrderedDict()
_cache_lock = threading.Lock()
_fetch_inflight = {}          # url -> threading.Event (single-flight election)
MAX_CACHE_SIZE = 2000
CACHE_JITTER = 0.2
# Sweep expired entries at most once per interval (avoid O(n) per request).
_last_cache_sweep = 0.0
_CACHE_SWEEP_INTERVAL = 60.0

# URL-level negative cache (failure state layer). Its own lock — never nested
# with _cache_lock (cache.md §7.2 lock-order discipline).
_negative = {}
_neg_lock = threading.Lock()

# Local hit/miss counters (Q1 observation item, NOT registered metric names).
# Guarded by _cache_lock; the derived cache_hit_ratio gauge is published by
# _publish_url_stats, which every hit path (and the write path) calls *after*
# releasing the lock.
_cache_stats = {'hit': 0, 'miss': 0}


def _record_hit_locked():
    """Count a positive-cache hit; caller must hold ``_cache_lock``.

    Every non-network hit path funnels through here (segment 1, the segment-3
    double-check and the segment-4 follower read).  Counting only segment 1
    biased ``cache_hit_ratio`` down by exactly the concurrent / slow-upstream
    traffic the gauge exists to observe (P2-11).  Returns the ``(hit, miss,
    entries)`` triple to publish after the lock is released (S1-4).
    """
    _cache_stats['hit'] += 1
    return _cache_stats['hit'], _cache_stats['miss'], len(cache)


def _publish_url_stats(hit, miss, entries, metric_key='url'):
    """Publish the URL-cache gauges (call *outside* ``_cache_lock`` — S1-4)."""
    total = hit + miss
    metrics.set_gauge('cache_entries', entries, key=metric_key)
    metrics.set_gauge('cache_hit_ratio',
                      round(hit / total, 4) if total else 0.0)


# Failure-history ageing window: a cache mechanism constant (not a domain TTL).
# Once a failure streak is older than this, the next probe gets the full budget.
_HISTORY_AGE = 600.0

# Follower wait margin (S1-1).  A follower waits the leader's budget plus this
# small epsilon so the leader's post-fetch publish (_cache_put / _clear_negative,
# microseconds) can never lose the race against the follower's wait window and
# push the follower into the gap branch.  The margin only absorbs scheduling
# jitter, it is not a network budget of its own.
_FOLLOWER_WAIT_MARGIN = 1.0

# Half-open probe-budget cap (AC-S3 裁决).  The escalating probe (S1-6) tops
# out here rather than at REQUEST_TIMEOUT: a sustained black-hole upstream then
# settles at a ~10s cycle (5s probe + 5s NEG_TTL), so roughly half the requests
# are slow and P95 ≈ 5s, while a single request can never exceed 15s.  Derived
# from the previous 2s→4s→8s→REQUEST_TIMEOUT ladder by capping the 8s rung.
_PROBE_BUDGET_CAP = 5.0


class FetchError(Exception):
    """The single failure type raised by :func:`fetch_json` (cache.md §2.2)."""

    KINDS = frozenset({'upstream_timeout', 'upstream_error', 'cdp_unavailable'})

    def __init__(self, kind, *, url=None, cause=None):
        if kind not in self.KINDS:
            raise ValueError(
                f'invalid FetchError kind {kind!r}; known: {sorted(self.KINDS)}')
        self.kind = kind
        self.url = url
        self.cause = cause
        super().__init__(kind if url is None else f'{kind}: {url}')


def _expires_at(ttl=None):
    """expires_at = now + ttl ×(1 ± jitter); ttl None ⇒ news_url domain TTL."""
    base = ttl if ttl is not None else cache_policy('news_url')['ttl']
    return time.time() + base * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))


def _sweep_expired(d):
    """Remove expired entries from a cache dict. Caller must hold its lock.

    Contract unchanged: returns the number removed and keeps ``None`` entries
    (the read path handles them itself).
    """
    now = time.time()
    expired = [k for k, entry in d.items()
               if entry and now >= entry.get('expires_at', 0)]
    for k in expired:
        del d[k]
    return len(expired)


def _cache_fresh(entry, refresh_epoch=None):
    """Fresh while within its TTL and, for a scheduled refresh, recent enough.

    ``refresh_epoch`` (absolute epoch seconds) is the start of the scheduled
    refresh round that is reading.  A refresh writes its entry δ s *after* that
    round started, so at the next round (``t0 + tick``) the entry's age is only
    ``tick − δ`` — shorter than a TTL equal to the tick — and the round would be
    served from cache with no upstream request, silently degrading a nominal 4 s
    quote cadence to an effective 8 s (every other tick skipped).

    Requiring ``write_time >= refresh_epoch`` removes that phase coupling
    deterministically: an entry carried over from an earlier round can never be
    reused, while an entry written *during* this round (a concurrent REST
    refresh, or a single-flight leader this round) still is.  ``None`` — the
    default, and every non-stream caller — keeps the plain TTL semantics
    ``urlopen``-observable behaviour unchanged.
    """
    if not entry or time.time() >= entry.get('expires_at', 0):
        return False
    return refresh_epoch is None or entry.get('time', 0) >= refresh_epoch


def _cache_put(d, key, value, ttl=None, metric_key='url'):
    """Insert into a cache dict with double-trigger sweep + true-LRU eviction.

    Metrics are published *after* ``_cache_lock`` is released (S1-4): the
    critical section only reads the values it must keep consistent, so a
    ``/healthz`` snapshot can never block the fetch hot path.
    """
    with _cache_lock:
        now = time.time()
        global _last_cache_sweep
        if now - _last_cache_sweep >= _CACHE_SWEEP_INTERVAL:        # trigger ①
            _sweep_expired(d)
            _last_cache_sweep = now
        if len(d) >= MAX_CACHE_SIZE:                                # trigger ②
            _sweep_expired(d)
            while len(d) >= MAX_CACHE_SIZE:
                d.popitem(last=False)                               # BR-CACHE-10
        d[key] = {'data': value, 'time': now, 'last_access': now,
                  'expires_at': _expires_at(ttl)}
        if hasattr(d, 'move_to_end'):
            d.move_to_end(key)
        entries = len(d)
        # cache_hit_ratio: _cache_stats is guarded by _cache_lock which we
        # already hold ⇒ consistent read.
        hit, miss = _cache_stats['hit'], _cache_stats['miss']
    _publish_url_stats(hit, miss, entries, metric_key)


def _probe_budget(fail_count):
    """Escalating half-open probe budget (S1-6): 2s → 4s → 5s (cap, AC-S3).

    A slow-not-dead upstream (e.g. one needing ~5s) used to stay pinned at
    ``PROBE_TIMEOUT`` until the failure streak aged out (``_HISTORY_AGE``,
    600s), because ``first_at`` is only refreshed on ageing.  Doubling the
    budget per consecutive failure lets such an upstream clear its history
    within a few cycles instead of ten minutes.  ``fail_count < 1`` behaves
    like a single failure.

    AC-S3 裁决封顶 ``_PROBE_BUDGET_CAP`` (5s) 而非 ``REQUEST_TIMEOUT`` (10s)：
    持续黑洞下稳态周期 ≈ 5s 探测 + 5s 负缓存 = 10s，慢请求占比 ≈ 50% ⇒
    P95 ≈ 5s；单请求 ≤15s 恒成立。  ``_fetch_budget`` 对老化 (``_HISTORY_AGE``)
    的失败历史仍返回 ``REQUEST_TIMEOUT``——那是"一次性全预算探测"，不走上限。
    """
    budget = PROBE_TIMEOUT
    steps = max(int(fail_count), 1) - 1
    while steps > 0 and budget < _PROBE_BUDGET_CAP:
        budget = min(budget * 2, _PROBE_BUDGET_CAP)
        steps -= 1
    return budget


def _fetch_budget(url):
    """BR-CACHE-5/20: no entry → REQUEST_TIMEOUT; aged streak → REQUEST_TIMEOUT
    (full-budget probe once); otherwise the escalating probe budget for the
    current streak (S1-6)."""
    with _neg_lock:
        neg = _negative.get(url)
        if neg is None:
            return REQUEST_TIMEOUT
        if time.time() - neg['first_at'] >= _HISTORY_AGE:
            return REQUEST_TIMEOUT
        return _probe_budget(neg.get('fail_count', 1))


def _effective_timeout(url, deadline=None):
    """Leader network timeout = min(probe budget, remaining deadline) (S1-5).

    ``deadline`` is an absolute epoch-seconds instant shared across a batch.
    Returns ``None`` when the deadline has already elapsed, so the caller can
    fail without touching the network.
    """
    budget = _fetch_budget(url)
    if deadline is None:
        return budget
    remaining = deadline - time.time()
    if remaining <= 0:
        return None
    return min(budget, max(0.05, remaining))


def _follower_wait_budget(url, deadline=None):
    """Follower wait window: leader budget + epsilon, clamped to the deadline."""
    budget = _fetch_budget(url) + _FOLLOWER_WAIT_MARGIN
    if deadline is None:
        return budget
    remaining = deadline - time.time()
    return max(0.0, min(budget, remaining))


def _classify(exc):
    """Map an upstream exception to one of the FetchError kinds."""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'upstream_timeout'
    if isinstance(exc, urllib.error.URLError) and isinstance(
            getattr(exc, 'reason', None), (socket.timeout, TimeoutError)):
        return 'upstream_timeout'
    return 'upstream_error'


def _record_failure(url, kind):
    """Record a negative-cache entry; keeps failure history across NEG_TTL."""
    with _neg_lock:
        now = time.time()
        prev = _negative.get(url)
        aged = prev is not None and (now - prev['first_at']) >= _HISTORY_AGE
        _negative[url] = {                                          # BR-CACHE-6/20
            'until': now + NEG_TTL,
            'kind': kind,
            'fail_count': (prev['fail_count'] if prev else 0) + 1,
            'first_at': now if (prev is None or aged) else prev['first_at'],
        }
        if len(_negative) >= MAX_CACHE_SIZE:                        # BR-CACHE-8
            victim = min(_negative, key=lambda k: _negative[k]['until'])
            del _negative[victim]
        size = len(_negative)
    metrics.incr('upstream_fail_total', key=kind)                   # S1-4: lock released
    metrics.set_gauge('negative_cache_size', size)


def _clear_negative(url):
    """Success clears failure history (BR-CACHE-7)."""
    with _neg_lock:
        removed = _negative.pop(url, None)
        size = len(_negative)
    if removed is not None:
        metrics.set_gauge('negative_cache_size', size)              # S1-4: lock released


# ── HTTP transport: per-host keep-alive pool + process DNS cache ───────────
# `fetch_json` is the project's only HTTP egress.  `urllib.request.urlopen`
# opens a fresh TCP+TLS connection *and* re-resolves the host on every call:
# measured on the 2C2G node one upstream request cost ~340ms, of which ~176ms
# was DNS (with a 5.5% chance of a ~4s resolver retry) and ~78ms was the
# TCP+TLS handshake.  Both disappear once the connection is kept alive, so the
# transport below reuses one connection per (scheme, host, port) across
# requests while preserving `urlopen`'s observable contract: a read()able body
# on success, `HTTPError` on 4xx/5xx, `URLError` on transport failure, and
# redirect following.  DNS results are additionally cached (2b), which only
# affects how a *new* connection's address is found — TLS still dials the
# hostname, so SNI / certificate hostname verification are unchanged.

_MAX_REDIRECTS = 5
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

# Once a kept-alive connection is reused the server may already have closed it
# (idle timeout / restart).  These errors mean "this socket is stale", not
# "the upstream is down", so they are safe to retry exactly once on a fresh
# connection.  Retrying only on the *reused* attempt keeps a genuinely failing
# upstream from doubling its budget.
_STALE_CONNECTION_ERRORS = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    http.client.CannotSendHeader,
    ConnectionResetError,
    BrokenPipeError,
)


def _close_quietly(closeable):
    try:
        closeable.close()
    except Exception:
        pass


class _DNSResolver:
    """Process-wide TTL cache over ``socket.getaddrinfo`` (2b).

    The host is still dialled by *name* (TLS needs the name for SNI and
    certificate verification); only the name→address step is cached.  Lookups
    that fail are never cached, and a cached address that refuses to connect is
    re-resolved once before giving up, so a re-addressed upstream recovers
    without waiting for the TTL.  ``ttl <= 0`` disables caching entirely.
    """

    _MAX_ENTRIES = 256

    def __init__(self, ttl):
        self._ttl = float(ttl)
        self._lock = threading.Lock()
        self._cache = {}                       # (host, port) -> (expires_at, infos)

    def resolve(self, host, port, force=False):
        """Return the cached/tuple ``getaddrinfo`` result for (host, port)."""
        key = (host, port)
        now = time.time()
        if self._ttl > 0 and not force:
            with self._lock:
                entry = self._cache.get(key)
                if entry is not None and now < entry[0]:
                    return entry[1]
        infos = tuple(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        if infos and self._ttl > 0:
            with self._lock:
                self._cache[key] = (now + self._ttl, infos)
                if len(self._cache) > self._MAX_ENTRIES:
                    for stale_key in [k for k, (exp, _) in self._cache.items()
                                      if now >= exp]:
                        del self._cache[stale_key]
                    while len(self._cache) > self._MAX_ENTRIES:
                        self._cache.pop(next(iter(self._cache)))
        return infos

    def connect(self, address, timeout, source_address):
        """``socket.create_connection``-compatible connect using the cache."""
        host, port = address
        try:
            infos = self.resolve(host, port)
        except OSError:
            # Resolver unavailable ⇒ stdlib path (it raises the gaierror).
            return socket.create_connection(address, timeout, source_address)
        if not infos:
            return socket.create_connection(address, timeout, source_address)
        last_error = None
        for force in (False, True):
            if force:
                try:
                    infos = self.resolve(host, port, force=True)
                except OSError:
                    break
                if not infos:
                    break
            for family, socktype, proto, _canon, sockaddr in infos:
                sock = None
                try:
                    sock = socket.socket(family, socktype, proto)
                    default_timeout = getattr(
                        socket, '_GLOBAL_DEFAULT_TIMEOUT', None)
                    if timeout is not None and timeout is not default_timeout:
                        sock.settimeout(timeout)
                    if source_address:
                        sock.bind(source_address)
                    sock.connect(sockaddr)
                    return sock
                except OSError as exc:
                    last_error = exc
                    if sock is not None:
                        _close_quietly(sock)
        if last_error is not None:
            raise last_error
        return socket.create_connection(address, timeout, source_address)


class _CachedDNSConnection:
    """Mixin: dial through :class:`_DNSResolver` (SNI stays on the hostname)."""

    def _create_connection(self, address, timeout=None, source_address=None,
                           all_errors=False):
        return _resolver.connect(address, timeout, source_address)


class _PooledHTTPConnection(_CachedDNSConnection, http.client.HTTPConnection):
    pass


class _PooledHTTPSConnection(_CachedDNSConnection, http.client.HTTPSConnection):
    pass


def _open_connection(key, timeout):
    """Open a fresh connection for ``key`` = ``(scheme, host, port)``."""
    scheme, host, port = key
    if scheme == 'https':
        conn = _PooledHTTPSConnection(host, port, timeout=timeout)
    else:
        conn = _PooledHTTPConnection(host, port, timeout=timeout)
    conn.connect()
    return conn


class _ConnectionPool:
    """Bounded per-``(scheme, host, port)`` keep-alive connection pool (2a).

    Policy:

    * **Reuse** — an idle connection is handed out LIFO when present.
    * **Bounded** — at most ``max_per_host`` *pooled* connections per key.  When
      the cap is reached and nothing is idle, a short-lived *ephemeral*
      connection is opened and closed after the request instead of waiting for
      a slot: waiting would re-serialise exactly the concurrency the pool
      exists to preserve.  Ephemeral connections are never retained.
    * **Eviction** — idle connections older than ``idle_ttl`` are closed lazily
      on the next checkout (no reaper thread).
    * **Healing** — the caller discards a connection that raises a stale-socket
      error and retries once on a fresh one (see :func:`_pool_request`).

    ``_lock`` guards the bucket bookkeeping only; connect / close / request IO
    always happens outside it (lock discipline: never hold a lock across IO).
    """

    def __init__(self, max_per_host, idle_ttl):
        self._lock = threading.Lock()
        self._idle = {}                        # key -> [(conn, idle_since)] LIFO
        self._live = {}                        # key -> pooled connection count
        self._max_per_host = max(1, int(max_per_host))
        self._idle_ttl = max(0.0, float(idle_ttl))
        self.stats = {'reuse': 0, 'new': 0, 'stale': 0, 'evicted': 0,
                      'ephemeral': 0}

    def acquire(self, key, timeout):
        """Check out ``(conn, reused, ephemeral)`` for ``key``."""
        now = time.time()
        expired = []
        conn = None
        reused = False
        ephemeral = False
        reserved = False
        with self._lock:
            bucket = self._idle.get(key)
            if bucket:
                while bucket:
                    candidate, idle_since = bucket.pop()
                    if now - idle_since <= self._idle_ttl:
                        conn, reused = candidate, True
                        break
                    expired.append(candidate)
                    self._live[key] = max(0, self._live.get(key, 1) - 1)
                    self.stats['evicted'] += 1
                if not bucket:
                    self._idle.pop(key, None)
            if conn is None:
                if self._live.get(key, 0) < self._max_per_host:
                    self._live[key] = self._live.get(key, 0) + 1
                    reserved = True
                else:
                    ephemeral = True
                    self.stats['ephemeral'] += 1
        for dead in expired:
            _close_quietly(dead)

        if reused:
            try:
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
            except OSError:
                # Died between checkout and reuse: free the slot and dial fresh.
                self._discard_live(key, conn)
                conn = None
                reused = False
                with self._lock:
                    if self._live.get(key, 0) < self._max_per_host:
                        self._live[key] = self._live.get(key, 0) + 1
                        reserved = True
                    else:
                        ephemeral = True
                        self.stats['ephemeral'] += 1
            else:
                self.stats['reuse'] += 1
                return conn, True, False

        try:
            conn = _open_connection(key, timeout)
        except BaseException:
            if reserved:
                with self._lock:
                    self._live[key] = max(0, self._live.get(key, 1) - 1)
            raise
        self.stats['new'] += 1
        return conn, False, ephemeral

    def release(self, key, conn, ephemeral=False):
        """Return a still-healthy connection to the idle bucket."""
        if ephemeral:
            _close_quietly(conn)
            return
        now = time.time()
        overflow = []
        with self._lock:
            bucket = self._idle.setdefault(key, [])
            bucket.append((conn, now))
            # The idle list can never exceed the per-host cap (also covers a
            # cap lowered at runtime).
            while len(bucket) > self._max_per_host:
                overflow.append(bucket.pop(0)[0])
                self._live[key] = max(0, self._live.get(key, 1) - 1)
        for dead in overflow:
            _close_quietly(dead)

    def discard(self, key, conn, ephemeral=False):
        """Drop an unusable connection (never returned to the pool)."""
        if ephemeral:
            _close_quietly(conn)
            return
        self._discard_live(key, conn)

    def note_stale(self):
        with self._lock:
            self.stats['stale'] += 1

    def _discard_live(self, key, conn):
        with self._lock:
            self._live[key] = max(0, self._live.get(key, 1) - 1)
        _close_quietly(conn)

    def close_all(self):
        """Close every *idle* pooled connection and empty the buckets.

        Process-exit teardown.  Without it the kept-alive sockets outlive the
        pool and are reclaimed by the GC at interpreter shutdown, which emits a
        ``ResourceWarning: unclosed <ssl.SSLSocket ...>`` (one per retained
        connection) on every run — noise in tests and logs, and a genuinely
        unclosed socket in production.

        Only idle connections are touched: a checked-out connection is not the
        pool's to close (closing it would abort an in-flight request), so its
        ``_live`` slot is kept and it may still be released back later.  The
        bookkeeping swap happens under ``_lock`` (bucket snapshot, no IO) and
        each ``close()`` runs *after* the lock is released, preserving the
        module's "never hold a lock across IO" discipline.

        Total and idempotent: an empty pool, a repeated call, or an
        already-closed connection is a no-op, never an error.
        """
        with self._lock:
            drained = []                                # [(conn)] — one flat list
            for key, bucket in self._idle.items():
                for conn, _idle_since in bucket:
                    drained.append(conn)
                self._live[key] = max(0, self._live.get(key, 0) - len(bucket))
            self._idle = {}                             # all host buckets emptied
        for conn in drained:                            # ★ lock released: close IO
            _close_quietly(conn)


_pool = _ConnectionPool(HTTP_POOL_MAX_PER_HOST, HTTP_POOL_IDLE_TTL)
_resolver = _DNSResolver(HTTP_DNS_CACHE_TTL)


def close_transport():
    """Close the keep-alive pool's idle sockets (process-exit teardown).

    Module-level public hook so the owner of ``_pool`` also owns its cleanup.
    Registered with :mod:`atexit` at import time (below): the pool is created at
    import, so its teardown belongs there too — a caller that only imports
    ``cache`` (the test suite, a one-shot fetch script) still gets the cleanup,
    which registering in ``server.main()`` could not provide.  Total function:
    it never raises and repeated calls are no-ops.
    """
    try:
        _pool.close_all()
    except Exception:                                   # never let exit raise
        pass


atexit.register(close_transport)


class _PooledResponse:
    """Minimal read-only response façade (the ``urlopen`` contract fetch uses)."""

    def __init__(self, body, status, headers):
        self._body = body
        self.status = status
        self.headers = headers

    def read(self, amt=None):
        if amt is None or amt < 0:
            body, self._body = self._body, b''
            return body
        chunk, self._body = self._body[:amt], self._body[amt:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _send(conn, method, path, headers):
    """Run one request on ``conn`` and return (status, headers, body, close?)."""
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    body = resp.read()
    will_close = bool(getattr(resp, 'will_close', True)) or conn.sock is None
    return resp.status, getattr(resp, 'msg', None), body, will_close


def _pool_request(method, url, headers, timeout):
    """Perform one pooled GET/HEAD request, retrying a stale socket once."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or '').lower()
    if scheme not in ('http', 'https'):
        raise urllib.error.URLError(
            f'unsupported URL scheme {scheme!r} in {url!r}')
    host = parsed.hostname
    if not host:
        raise urllib.error.URLError(f'missing host in URL {url!r}')
    port = parsed.port or (443 if scheme == 'https' else 80)
    path = parsed.path or '/'
    if parsed.query:
        path = f'{path}?{parsed.query}'
    key = (scheme, host, port)

    for attempt in (0, 1):
        conn, reused, ephemeral = _pool.acquire(key, timeout)
        try:
            status, resp_headers, body, will_close = _send(
                conn, method, path, headers)
        except _STALE_CONNECTION_ERRORS as exc:
            _pool.note_stale()
            _pool.discard(key, conn, ephemeral=ephemeral)
            if reused and attempt == 0:
                continue                    # stale keep-alive ⇒ retry once fresh
            raise urllib.error.URLError(exc) from exc
        except (socket.timeout, TimeoutError):
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise
        except urllib.error.URLError:
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise
        except OSError as exc:
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise urllib.error.URLError(exc) from exc
        except http.client.HTTPException as exc:
            _pool.discard(key, conn, ephemeral=ephemeral)
            raise urllib.error.URLError(exc) from exc
        if will_close:
            _pool.discard(key, conn, ephemeral=ephemeral)
        else:
            _pool.release(key, conn, ephemeral=ephemeral)
        return status, resp_headers, body
    raise urllib.error.URLError('stale connection retry exhausted')


def urlopen(req, timeout=None):
    """Pooled drop-in for ``urllib.request.urlopen`` (http/https).

    Accepts the ``Request`` object ``fetch_json`` builds (module-level so tests
    keep patching ``cache.urlopen`` as the single network seam) and returns a
    context-manager response whose ``read()`` yields the body bytes.  Redirects
    are followed (≤ :data:`_MAX_REDIRECTS`), 4xx/5xx raise
    ``urllib.error.HTTPError`` and transport failures raise
    ``urllib.error.URLError`` — matching the stdlib contract ``_classify`` and
    every caller already rely on.  The difference is transport: same-host
    requests reuse a kept-alive connection from ``_pool``.
    """
    if isinstance(req, Request):
        url = req.full_url
        headers = dict(req.header_items())
        method = req.get_method()
    else:
        url = str(req)
        headers = {}
        method = 'GET'
    current = url
    redirects = 0
    while True:
        status, resp_headers, body = _pool_request(method, current, headers,
                                                   timeout)
        if status in _REDIRECT_CODES and resp_headers is not None:
            location = resp_headers.get('location')
            if location:
                redirects += 1
                if redirects > _MAX_REDIRECTS:
                    raise urllib.error.HTTPError(
                        current, status, 'too many redirects',
                        resp_headers, None)
                current = urljoin(current, location)
                continue
        if status >= 400:
            raise urllib.error.HTTPError(
                current, status,
                http.client.responses.get(status, ''), resp_headers, None)
        return _PooledResponse(body, status, resp_headers)


def warm_transport(hosts=None, count=None, timeout=None):
    """Pre-warm DNS + pooled connections for the upstream hot path.

    Total, best-effort function: it never raises and never performs a business
    request — it only dials the transport (which fills ``_DNSResolver`` and
    leaves the socket in ``_pool`` for the first real refresh to reuse), so
    warming adds no upstream data load.  A dial failure for one host is
    swallowed and the next host is tried; each attempt is bounded by
    ``timeout``.  Returns the number of fresh connections left in the pool.

    Called from a startup daemon thread (``server.main``), so it can never gate
    startup or ``/healthz``; the caller does not need to wait for the result.
    """
    try:
        hosts = tuple(hosts) if hosts else warm_hosts()
    except Exception:                       # defensive: never let warming raise
        return 0
    if count is None:
        count = HTTP_WARM_CONNECTIONS
    count = max(0, int(count))
    if timeout is None:
        timeout = HTTP_WARM_TIMEOUT
    warmed = 0
    for key in hosts:
        for _ in range(count):
            try:
                conn, reused, ephemeral = _pool.acquire(key, timeout)
            except Exception:               # dial failed ⇒ silent, next host
                break
            _pool.release(key, conn, ephemeral=ephemeral)
            if reused:
                break                       # host already had a warm connection
            if ephemeral:
                break                       # pool full ⇒ retrying adds nothing
            warmed += 1
    return warmed


def fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None,
               refresh_epoch=None):
    """Fetch a URL through the four-segment cache protocol (cache.md §2.1).

    Segments: ① positive cache hit → return; ② un-expired negative gate →
    raise without networking; ③ leader election, a single attempt (half-open
    probe budget when a failure history exists); ④ follower waits then reads
    state, never re-entering the election.  Network IO never holds a lock.

    ``deadline`` (S1-5) is an optional absolute epoch-seconds instant, added as
    the 5th positional parameter so all existing callers are unchanged.  When
    given, the leader's network timeout becomes ``min(_fetch_budget(url),
    max(0.05, deadline - now))``, the follower wait is clamped to the same
    instant, and an elapsed deadline with nothing cached raises
    ``FetchError('upstream_timeout')`` without any network IO.

    ``refresh_epoch`` (6th, keyword) is the scheduled refresh round's start
    instant; a positive entry written *before* it is not a hit (see
    :func:`_cache_fresh`).  The scheduled refresh path passes it so the domain
    that sets the tick is genuinely re-fetched every tick instead of being
    served by the entry the previous tick wrote δ s into its round.  ``None``
    (every REST / prefetch caller) keeps plain TTL semantics, and the write TTL
    is always the full domain TTL, so REST remains protected across the window.

    The elapsed-deadline gate sits **after** segment ① (P1-5): a fresh cached
    body costs zero network and zero latency, so the caller's exhausted batch
    budget must never reject data we already hold — otherwise the cache can
    never save the slow batch it exists to absorb.  The epoch floor applies to
    segments ①/③/④ alike, so a "not recent enough" entry never resolves as a hit.
    """
    # ── segment 1: positive cache ──────────────────────────────────────────
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry, refresh_epoch):
            cache.move_to_end(url)                                  # BR-CACHE-10
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()
            cached_data = entry['data']
        else:
            _cache_stats['miss'] += 1
            cached_data = None
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                              # S1-4: lock released
        return cached_data

    if deadline is not None and deadline - time.time() <= 0:
        # Caller's end-to-end budget is gone and nothing is cached: fail fast,
        # no network, and do NOT record a negative-cache entry (this is our own
        # budget, not an upstream failure).
        raise FetchError('upstream_timeout', url=url)

    # ── segment 2: negative cache (no network) ─────────────────────────────
    with _neg_lock:
        neg = _negative.get(url)
    if neg is not None and time.time() < neg['until']:              # BR-CACHE-4
        raise FetchError(neg['kind'], url=url)

    # ── segment 3: leader election, a single attempt ───────────────────────
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)                                      # double-check
        if _cache_fresh(entry, refresh_epoch):
            cache.move_to_end(url)
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()
            cached_data = entry['data']
        elif url in _fetch_inflight:
            event = _fetch_inflight[url]
            is_leader = False
        else:
            event = threading.Event()
            _fetch_inflight[url] = event
            is_leader = True
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                              # S1-4: lock released
        return cached_data

    if is_leader:
        try:
            timeout = _effective_timeout(url, deadline)             # BR-CACHE-5/20
            if timeout is None:
                # The deadline elapsed after the top gate but before election:
                # local timeout, no network attempt and no negative-cache write.
                raise FetchError('upstream_timeout', url=url)
            try:
                req = Request(url, headers=headers or {})
                with urlopen(req, timeout=timeout) as resp:         # ★ no lock held
                    data = resp.read().decode(encoding, errors='replace')
            except Exception as exc:
                kind = _classify(exc)
                _record_failure(url, kind)                          # BR-CACHE-6
                raise FetchError(kind, url=url) from exc

            # REV-DES-09: cache writes live OUTSIDE the network try, so a
            # programming error here is not misclassified as an upstream
            # failure (which would poison the negative cache).
            try:
                _cache_put(cache, url, data, ttl=ttl)               # BR-CACHE-11/12
                _clear_negative(url)                                # BR-CACHE-7
            except Exception:
                log.exception('[fetch_json] post-fetch cache write failed: %s', url)
            return data
        finally:
            # The election/budget helpers run *inside* the try (P2-10): an
            # exception there used to leak this URL's election token forever,
            # turning every later request into a follower that times out.
            with _cache_lock:
                _fetch_inflight.pop(url, None)
            event.set()                                             # release lock first

    # ── segment 4: follower — wait then read state; never re-elect ─────────
    # Wait leader budget + epsilon (S1-1) so the leader's post-fetch publish
    # never loses the race against this window.
    event.wait(timeout=_follower_wait_budget(url, deadline))
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry, refresh_epoch):
            cache.move_to_end(url)
            entry['last_access'] = time.time()
            hit_stats = _record_hit_locked()
            cached_data = entry['data']
        else:
            leader_alive = url in _fetch_inflight
    if hit_stats is not None:
        _publish_url_stats(*hit_stats)                              # S1-4: lock released
        return cached_data
    with _neg_lock:
        neg = _negative.get(url)          # ignore expiry: gap path is deterministic
    if neg is not None:
        raise FetchError(neg['kind'], url=url)
    if leader_alive:
        # The leader is still fetching/publishing past our wait window: this is
        # our local wait budget, not an upstream failure ⇒ report a timeout and
        # never record it in the negative cache (S1-1).
        raise FetchError('upstream_timeout', url=url)
    # No positive cache, no negative entry and no live leader: fail closed
    # without touching upstream.
    raise FetchError('upstream_error', url=url)


# Feed cache — the single implementation point for feed LRU / sweep.
feed_cache = OrderedDict()
_feed_cache_lock = threading.Lock()
_feed_fetch_locks = {}
_feed_fetch_locks_lock = threading.Lock()
_last_feed_sweep = 0.0


def feed_cache_get(path):
    """Return the cached feed XML (refreshing LRU), or None on miss/expiry."""
    with _feed_cache_lock:
        entry = feed_cache.get(path)
        if not entry or time.time() >= entry.get('expires_at', 0):
            return None
        feed_cache.move_to_end(path)
        entry['last_access'] = time.time()
        return entry['xml']


def feed_cache_put(path, xml, ttl):
    """Store feed XML with double-trigger sweep + LRU eviction (cap from policy)."""
    with _feed_cache_lock:
        now = time.time()
        global _last_feed_sweep
        if now - _last_feed_sweep >= _CACHE_SWEEP_INTERVAL:         # trigger ①
            _sweep_expired(feed_cache)
            _last_feed_sweep = now
        cap = cache_policy('feed')['cache_max']                     # BR-CACHE-12
        if len(feed_cache) >= cap:
            _sweep_expired(feed_cache)
            while len(feed_cache) >= cap:
                feed_cache.popitem(last=False)
        feed_cache[path] = {'xml': xml, 'time': now, 'last_access': now,
                            'expires_at': _expires_at(ttl)}
        feed_cache.move_to_end(path)
        entries = len(feed_cache)
    metrics.set_gauge('cache_entries', entries, key='feed')         # S1-4: lock released


def build_batch_response(requested, results, errors=None, dropped=0):
    """Assemble the flat batch-response mapping (sole reserved-key assembler).

    Total function: always returns a dict, never raises.  Output key order is
    the requested order; ``_errors`` appears only when non-empty and
    ``_truncated`` / ``_dropped_count`` only when ``dropped > 0`` (both or
    neither).
    """
    errors = errors or {}
    results = results or {}
    requested = requested or ()
    out, seen = {}, set()
    for code in requested:                                          # BR-CACHE-15
        if not isinstance(code, str) or code.startswith('_') or code in seen:
            continue
        seen.add(code)
        out[code] = results.get(code)                               # missing → None

    err_out = {}
    for code in requested:                                          # BR-CACHE-16 (ordered)
        if code not in seen or code in err_out:
            continue
        if out.get(code) is not None:        # has data ⇒ not a failure
            if errors.get(code):
                log.warning('[build_batch_response] %s has data but error kind '
                            '%r; dropped', code, errors[code])
            continue
        kind = errors.get(code)
        if not kind:
            continue
        if kind not in FetchError.KINDS:
            log.warning('[build_batch_response] unknown kind %r for %s → '
                        'upstream_error', kind, code)
            kind = 'upstream_error'
        err_out[code] = kind
    if err_out:
        out['_errors'] = err_out
    if dropped > 0:                                                 # BR-CACHE-17
        out['_truncated'] = True
        out['_dropped_count'] = int(dropped)
    return out


def _fill_missing(result, data, expected_keys):
    """Fill expected keys not in data as null, preserving extra keys."""
    for key in expected_keys:
        result[key] = data.get(key)
    for k, v in data.items():
        if k not in expected_keys:
            result[k] = v
