"""URL fetch cache with stampede protection, negative cache, feed cache and
the batch-response contract assembler (cache.md v1.1).

Layer-0 pure cache/contract layer: imports only stdlib + ``config`` + ``metrics``.
It never imports ``server`` / ``stream`` / ``stock_api`` / ``market_api``.
"""

import logging
import random
import socket
import threading
import time
import urllib.error
from collections import OrderedDict
from urllib.request import Request, urlopen

from . import metrics
from .config import NEG_TTL, PROBE_TIMEOUT, REQUEST_TIMEOUT, cache_policy

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


def _cache_fresh(entry):
    return bool(entry) and time.time() < entry.get('expires_at', 0)


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


def fetch_json(url, headers=None, ttl=None, encoding='utf-8', deadline=None):
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

    The elapsed-deadline gate sits **after** segment ① (P1-5): a fresh cached
    body costs zero network and zero latency, so the caller's exhausted batch
    budget must never reject data we already hold — otherwise the cache can
    never save the slow batch it exists to absorb.
    """
    # ── segment 1: positive cache ──────────────────────────────────────────
    hit_stats = None
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry):
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
        if _cache_fresh(entry):
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
        if _cache_fresh(entry):
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
