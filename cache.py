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
MAX_CACHE_SIZE = 200
CACHE_JITTER = 0.2
# Sweep expired entries at most once per interval (avoid O(n) per request).
_last_cache_sweep = 0.0
_CACHE_SWEEP_INTERVAL = 60.0


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
                event.set()
                with _cache_lock:
                    _fetch_inflight.pop(url, None)

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        event.wait(timeout=min(REQUEST_TIMEOUT, remaining))

    # Give up on the single-flight election; fall through to a direct fetch
    # so the caller still gets data (worst case: concurrent direct fetches).
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = resp.read().decode('utf-8')
    _cache_put(cache, url, data, ttl=ttl)
    return data


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
