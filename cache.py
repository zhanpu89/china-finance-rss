"""URL fetch cache with stampede protection and feed cache."""

import json
import random
import threading
import time
from urllib.request import Request, urlopen

from config import CACHE_TTL, REQUEST_TIMEOUT

# Generic URL fetch cache
cache = {}
_cache_lock = threading.Lock()
_fetch_inflight = {}
# 2000 ≈ 200 max user codes × 4 URL variants × 2.5 headroom (a full watchlist
# tick touches ~600-800 URL entries; 200 would flush the URL cache every
# round → ~0 hit rate). Each entry averages ~10KB → ~20MB, fine on 2C2G.
MAX_CACHE_SIZE = 2000
CACHE_JITTER = 0.2
# Sweep expired entries at most once per interval (avoid O(n) per request).
_last_cache_sweep = 0.0
_CACHE_SWEEP_INTERVAL = 60.0
# P1-7: bound concurrent fall-through direct fetches so a leader failure
# doesn't cause an unbounded stampede to upstream.
_fallthrough_sem = threading.Semaphore(2)


def _expires_at(ttl=None):
    base = (ttl if ttl is not None else CACHE_TTL)
    return time.time() + base * (1 + random.uniform(-CACHE_JITTER, CACHE_JITTER))


def _sweep_expired(d):
    """Remove expired entries from a cache dict. Caller must hold its lock."""
    now = time.time()
    expired = [k for k, entry in d.items()
               if entry and now >= entry.get('expires_at', 0)]
    for k in expired:
        del d[k]
    return len(expired)


def _cache_put(d, key, value, ttl=None):
    with _cache_lock:
        # Proactively drop expired entries so stale data doesn't pile up
        # while the dict stays below MAX_CACHE_SIZE.
        global _last_cache_sweep
        now = time.time()
        if now - _last_cache_sweep >= _CACHE_SWEEP_INTERVAL:
            _sweep_expired(d)
            _last_cache_sweep = now
        if len(d) >= MAX_CACHE_SIZE:
            oldest = min(d, key=lambda k: d[k]['time'])
            del d[oldest]
        d[key] = {'data': value, 'time': now, 'expires_at': _expires_at(ttl)}


def _cache_fresh(entry):
    return entry and time.time() < entry.get('expires_at', 0)


def fetch_json(url, headers=None, ttl=None):
    """Fetch URL with in-memory cache and stampede protection.

    Uses a per-URL Event for leader election:
      - First thread becomes leader and fetches upstream
      - Followers wait on the Event, then read from cache
      - If the leader fails, the Event is set and the inflight slot freed;
        a waiting follower re-enters the election and becomes the new
        leader, so a failure never triggers an upstream stampede
    """
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry):
            return entry['data']

    deadline = time.time() + REQUEST_TIMEOUT
    while True:
        with _cache_lock:
            entry = cache.get(url)
            if _cache_fresh(entry):
                return entry['data']
            if url in _fetch_inflight:
                event = _fetch_inflight[url]
                is_leader = False
            else:
                _fetch_inflight[url] = threading.Event()
                event = _fetch_inflight[url]
                is_leader = True

        if is_leader:
            try:
                req = Request(url, headers=headers or {})
                with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    data = resp.read().decode('utf-8')
                _cache_put(cache, url, data, ttl=ttl)
                return data
            finally:
                with _cache_lock:
                    _fetch_inflight.pop(url, None)
                event.set()

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        event.wait(timeout=min(REQUEST_TIMEOUT, remaining))

    # P1-7: fall-through after election deadline — stagger retries with a
    # random backoff and cap concurrency so a leader failure doesn't trigger
    # an unbounded upstream stampede.
    time.sleep(random.uniform(0, 0.5))
    # Re-check cache: a concurrent direct fetch may have populated it.
    with _cache_lock:
        entry = cache.get(url)
        if _cache_fresh(entry):
            return entry['data']
    # P1-11: bounded wait on fall-through semaphore. Two slow urlopen calls
    # can hold both slots; an unbounded acquire would block the thread
    # indefinitely, compounding toward the RSSHandler timeout and risking
    # 503 cascades.  P1-14: raise instead of return None — fetch_json's
    # contract is "return str on success, raise on failure".  Callers
    # (server.py _serve_feed, stock_api fetch_*, utils warm_jin10) already
    # have try/except that either degrade to error-RSS or swallow.
    if not _fallthrough_sem.acquire(timeout=3):
        raise RuntimeError(
            "[fetch_json] fallthrough timeout: semaphore busy, "
            "upstream likely slow/unreachable"
        )
    try:
        # Re-check once more after acquiring the semaphore.
        with _cache_lock:
            entry = cache.get(url)
            if _cache_fresh(entry):
                return entry['data']
        req = Request(url, headers=headers or {})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read().decode('utf-8')
        _cache_put(cache, url, data, ttl=ttl)
        return data
    finally:
        _fallthrough_sem.release()


# Feed cache
feed_cache = {}
_feed_cache_lock = threading.Lock()
_feed_fetch_locks = {}
_feed_fetch_locks_lock = threading.Lock()
MAX_FEED_CACHE_SIZE = 100


def _fill_missing(result, data, expected_keys):
    """Fill expected keys not in data as null, preserving extra keys."""
    for key in expected_keys:
        result[key] = data.get(key)
    for k, v in data.items():
        if k not in expected_keys:
            result[k] = v
