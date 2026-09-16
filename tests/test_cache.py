"""Unit tests for cache.py (cache.md §8 T-CACHE-*)."""

import threading
import time
import unittest
import urllib.error
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import china_finance_rss.cache as cache_mod
from china_finance_rss import config, metrics

_TRACKED_GLOBALS = ('cache', '_negative', '_fetch_inflight', '_cache_stats',
                    '_last_cache_sweep', 'feed_cache', '_last_feed_sweep',
                    'MAX_CACHE_SIZE')


class _FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _CacheTestCase(unittest.TestCase):
    """Isolate the module globals so cases do not leak into each other."""

    def setUp(self):
        self._saved = {k: getattr(cache_mod, k) for k in _TRACKED_GLOBALS}
        cache_mod.cache = OrderedDict()
        cache_mod._negative = {}
        cache_mod._fetch_inflight = {}
        cache_mod._cache_stats = {'hit': 0, 'miss': 0}
        cache_mod._last_cache_sweep = 0.0
        cache_mod.feed_cache = OrderedDict()
        cache_mod._last_feed_sweep = 0.0
        metrics.reset()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(cache_mod, k, v)
        metrics.reset()


# ── FetchError ─────────────────────────────────────────────────────────────

class FetchErrorTests(_CacheTestCase):
    def test_invalid_kind_raises_value_error(self):           # T-CACHE-16
        with self.assertRaises(ValueError):
            cache_mod.FetchError('bogus')

    def test_kinds_constructible_and_str(self):               # T-CACHE-16
        for k in ('upstream_timeout', 'upstream_error', 'cdp_unavailable'):
            exc = cache_mod.FetchError(k, url='http://x')
            self.assertEqual(exc.kind, k)
            self.assertEqual(exc.url, 'http://x')
        self.assertEqual(str(cache_mod.FetchError('upstream_error')),
                         'upstream_error')
        self.assertEqual(str(cache_mod.FetchError('upstream_error', url='u')),
                         'upstream_error: u')

    def test_cause_preserved(self):
        inner = ValueError('inner')
        exc = cache_mod.FetchError('upstream_error', url='u', cause=inner)
        self.assertIs(exc.cause, inner)


# ── _classify ──────────────────────────────────────────────────────────────

class ClassifyTests(unittest.TestCase):
    def test_classify(self):
        import socket
        self.assertEqual(cache_mod._classify(socket.timeout()),
                         'upstream_timeout')
        self.assertEqual(cache_mod._classify(TimeoutError()),
                         'upstream_timeout')
        self.assertEqual(
            cache_mod._classify(urllib.error.URLError(socket.timeout())),
            'upstream_timeout')
        self.assertEqual(cache_mod._classify(urllib.error.URLError('boom')),
                         'upstream_error')
        self.assertEqual(cache_mod._classify(ValueError('x')),
                         'upstream_error')


# ── build_batch_response ───────────────────────────────────────────────────

class BuildBatchResponseTests(unittest.TestCase):
    def test_reserved_key_matrix(self):                       # T-CACHE-11
        out = cache_mod.build_batch_response(['a'], {'a': 1})
        self.assertEqual(out, {'a': 1})
        self.assertNotIn('_errors', out)
        self.assertNotIn('_truncated', out)
        self.assertNotIn('_dropped_count', out)

        out = cache_mod.build_batch_response(['a'], {'a': None},
                                             {'a': 'upstream_timeout'})
        self.assertEqual(out['_errors'], {'a': 'upstream_timeout'})
        self.assertNotIn('_truncated', out)

        out = cache_mod.build_batch_response(['a'], {'a': 1}, None, dropped=20)
        self.assertIs(out['_truncated'], True)
        self.assertEqual(out['_dropped_count'], 20)
        self.assertNotIn('_errors', out)

        out = cache_mod.build_batch_response(['a'], {'a': None},
                                             {'a': 'upstream_error'}, dropped=5)
        self.assertEqual(set(out), {'a', '_errors', '_truncated', '_dropped_count'})

    def test_zero_or_negative_dropped_omits_keys(self):       # T-CACHE-11
        for dropped in (0, -1):
            out = cache_mod.build_batch_response(['a'], {'a': 1}, dropped=dropped)
            self.assertNotIn('_truncated', out)
            self.assertNotIn('_dropped_count', out)

    def test_value_domain_three_way(self):                    # T-CACHE-12
        out = cache_mod.build_batch_response(
            ['ok', 'fail', 'nodata'],
            {'ok': {'p': 1}, 'fail': None, 'nodata': None},
            {'fail': 'upstream_timeout'})
        self.assertEqual(out['ok'], {'p': 1})
        self.assertIsNone(out['fail'])
        self.assertIsNone(out['nodata'])
        self.assertEqual(out['_errors'], {'fail': 'upstream_timeout'})
        for v in out['_errors'].values():
            self.assertIn(v, cache_mod.FetchError.KINDS)

    def test_total_function(self):                            # T-CACHE-13
        out = cache_mod.build_batch_response(
            ['_internal', 'dup', 'dup', 123, 'x'],
            {'_internal': 1, 'dup': 2, 'x': None, 'extra': 9},
            {'x': 'not_a_kind', 'dup': 'upstream_error'}, dropped=-1)
        self.assertNotIn('_internal', out)             # underscore code skipped
        self.assertNotIn('extra', out)                 # results keys outside requested ignored
        self.assertIsNone(out['x'])
        self.assertEqual(out['_errors'], {'x': 'upstream_error'})  # unknown kind normalised
        self.assertNotIn('_truncated', out)
        self.assertEqual(list(out), ['dup', 'x', '_errors'])       # order + de-dup

    def test_errors_nonempty_only(self):                      # T-CACHE-14
        out = cache_mod.build_batch_response(['a'], {'a': 1},
                                             {'a': 'upstream_error'})
        self.assertNotIn('_errors', out)

    def test_data_plus_error_conflict_not_recorded(self):     # D-2
        out = cache_mod.build_batch_response(['a'], {'a': {'v': 1}},
                                             {'a': 'upstream_error'})
        self.assertNotIn('_errors', out)

    def test_never_contains_top_level_error(self):            # BR-CACHE-18
        out = cache_mod.build_batch_response(['a'], {'a': None},
                                             {'a': 'upstream_error'})
        self.assertNotIn('error', out)

    def test_handles_empty_inputs(self):
        self.assertEqual(cache_mod.build_batch_response(None, None), {})
        self.assertEqual(cache_mod.build_batch_response([], {}), {})


# ── LRU / sweep ────────────────────────────────────────────────────────────

class UrlCacheLruTests(_CacheTestCase):
    def test_true_lru_eviction_on_hit(self):                  # T-CACHE-7
        cache_mod.MAX_CACHE_SIZE = 3

        def ok(req, timeout=None):
            return _FakeResponse(f'body:{req.full_url}'.encode())

        with mock.patch.object(cache_mod, 'urlopen', side_effect=ok):
            for k in ('A', 'B', 'C'):
                cache_mod.fetch_json(f'http://t/{k}', ttl=60)
            self.assertEqual(list(cache_mod.cache),
                             ['http://t/A', 'http://t/B', 'http://t/C'])
            cache_mod.fetch_json('http://t/A', ttl=60)     # hit → move_to_end
            self.assertEqual(list(cache_mod.cache),
                             ['http://t/B', 'http://t/C', 'http://t/A'])
            cache_mod.fetch_json('http://t/D', ttl=60)     # evicts LRU (=B)
        self.assertNotIn('http://t/B', cache_mod.cache)
        self.assertIn('http://t/A', cache_mod.cache)

    def test_url_cap_enforced(self):                          # T-CACHE-9
        cache_mod.MAX_CACHE_SIZE = 5
        for i in range(12):
            cache_mod._cache_put(cache_mod.cache, f'u{i}', i, ttl=60)
        self.assertLessEqual(len(cache_mod.cache), 5)
        self.assertNotIn('u0', cache_mod.cache)   # oldest evicted
        self.assertIn('u11', cache_mod.cache)

    def test_timed_sweep_trigger(self):                       # T-CACHE-8 trigger ①
        cache_mod.cache['stale'] = {'data': 'x', 'time': 0,
                                    'expires_at': time.time() - 10}
        cache_mod._last_cache_sweep = 0.0                    # interval elapsed
        cache_mod._cache_put(cache_mod.cache, 'fresh', 'f', ttl=60)
        self.assertNotIn('stale', cache_mod.cache)
        self.assertIn('fresh', cache_mod.cache)

    def test_expires_at_defaults_to_news_url(self):           # BR-CACHE-2
        now = time.time()
        exp = cache_mod._expires_at()
        ttl = config.cache_policy('news_url')['ttl']
        self.assertGreaterEqual(exp - now, ttl * 0.8 - 0.5)
        self.assertLessEqual(exp - now, ttl * 1.2 + 0.5)

    def test_cache_hit_ratio_published(self):                 # T-CACHE-19
        cache_mod._cache_stats['hit'] = 3
        cache_mod._cache_stats['miss'] = 1
        cache_mod._cache_put(cache_mod.cache, 'u', 'v', ttl=60)
        snap = metrics.snapshot()
        self.assertEqual(snap['cache_hit_ratio'], 0.75)
        self.assertEqual(snap['cache_entries'], {'url': 1})
        self.assertNotIn('cache_hit_total', snap)
        self.assertNotIn('cache_miss_total', snap)


# ── feed cache ─────────────────────────────────────────────────────────────

class FeedCacheTests(_CacheTestCase):
    def test_feed_lru_and_cap(self):                          # T-CACHE-10
        cap = config.cache_policy('feed')['cache_max']
        for i in range(cap + 1):
            cache_mod.feed_cache_put(f'/feed/{i}', f'<xml>{i}</xml>', 30)
        self.assertLessEqual(len(cache_mod.feed_cache), cap)
        self.assertNotIn('/feed/0', cache_mod.feed_cache)
        self.assertEqual(cache_mod.feed_cache_get(f'/feed/{cap}'),
                         f'<xml>{cap}</xml>')

    def test_feed_get_miss_and_expiry(self):
        self.assertIsNone(cache_mod.feed_cache_get('/feed/missing'))
        cache_mod.feed_cache['/feed/exp'] = {
            'xml': '<x/>', 'time': 0, 'last_access': 0,
            'expires_at': time.time() - 1}
        self.assertIsNone(cache_mod.feed_cache_get('/feed/exp'))

    def test_feed_get_refreshes_lru(self):
        cache_mod.feed_cache_put('/feed/a', '<a/>', 30)
        cache_mod.feed_cache_put('/feed/b', '<b/>', 30)
        cache_mod.feed_cache_get('/feed/a')
        self.assertEqual(list(cache_mod.feed_cache), ['/feed/b', '/feed/a'])


# ── negative cache / half-open probe ───────────────────────────────────────

class NegativeCacheTests(_CacheTestCase):
    def _failing_urlopen(self, delay=0.0):
        state = {'active': 0, 'max_active': 0, 'calls': 0}

        def _f(req, timeout=None):
            state['active'] += 1
            state['max_active'] = max(state['max_active'], state['active'])
            state['calls'] += 1
            try:
                if delay:
                    time.sleep(delay)
                raise urllib.error.URLError('boom')
            finally:
                state['active'] -= 1

        return state, _f

    def test_leader_failure_no_stampede(self):                # T-CACHE-2
        state, fail = self._failing_urlopen(delay=0.1)
        url = 'http://t/neg'
        with mock.patch.object(cache_mod, 'urlopen', side_effect=fail):
            errs = 0
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = [pool.submit(cache_mod.fetch_json, url, None, 60)
                        for _ in range(8)]
                for f in as_completed(futs):
                    try:
                        f.result()
                    except cache_mod.FetchError:
                        errs += 1
        self.assertEqual(errs, 8)
        self.assertEqual(state['max_active'], 1)
        self.assertEqual(state['calls'], 1)
        self.assertIn(url, cache_mod._negative)

    def test_negative_gate_short_circuits(self):              # T-CACHE-1/3
        url = 'http://t/gate'
        state, fail = self._failing_urlopen()
        with mock.patch.object(cache_mod, 'urlopen', side_effect=fail):
            with self.assertRaises(cache_mod.FetchError) as ctx:
                cache_mod.fetch_json(url, ttl=60)
            self.assertEqual(ctx.exception.kind, 'upstream_error')
            self.assertEqual(state['calls'], 1)
            with self.assertRaises(cache_mod.FetchError):
                cache_mod.fetch_json(url, ttl=60)
            self.assertEqual(state['calls'], 1)               # no network (segment 2)

    def test_probe_success_clears_history(self):              # T-CACHE-5
        url = 'http://t/recover'
        cache_mod._record_failure(url, 'upstream_error')
        cache_mod._negative[url]['until'] = time.time() - 1   # gate expired
        self.assertIn(url, cache_mod._negative)
        with mock.patch.object(
                cache_mod, 'urlopen',
                side_effect=lambda req, timeout=None: _FakeResponse(b'ok')):
            body = cache_mod.fetch_json(url, ttl=60)
        self.assertEqual(body, 'ok')
        self.assertNotIn(url, cache_mod._negative)
        self.assertEqual(cache_mod.cache[url]['data'], 'ok')

    def test_fetch_budget_progression(self):                  # T-CACHE-4b
        url = 'http://t/budget'
        self.assertEqual(cache_mod._fetch_budget(url), config.REQUEST_TIMEOUT)
        cache_mod._record_failure(url, 'upstream_timeout')
        self.assertEqual(cache_mod._fetch_budget(url), config.PROBE_TIMEOUT)
        cache_mod._negative[url]['first_at'] = time.time() - cache_mod._HISTORY_AGE - 1
        self.assertEqual(cache_mod._fetch_budget(url), config.REQUEST_TIMEOUT)

    def test_first_at_not_refreshed_until_aged(self):         # T-CACHE-6b
        url = 'http://t/first'
        cache_mod._record_failure(url, 'upstream_error')
        first = cache_mod._negative[url]['first_at']
        cache_mod._record_failure(url, 'upstream_error')
        self.assertEqual(cache_mod._negative[url]['first_at'], first)
        self.assertEqual(cache_mod._negative[url]['fail_count'], 2)
        cache_mod._negative[url]['first_at'] = time.time() - cache_mod._HISTORY_AGE - 1
        cache_mod._record_failure(url, 'upstream_error')
        self.assertGreater(cache_mod._negative[url]['first_at'], first)

    def test_history_survives_gate_expiry(self):              # T-CACHE-6
        url = 'http://t/keep'
        cache_mod._record_failure(url, 'upstream_error')
        cache_mod._negative[url]['until'] = time.time() - 1
        self.assertIn(url, cache_mod._negative)               # not deleted on expiry
        cache_mod._record_failure(url, 'upstream_error')
        self.assertEqual(cache_mod._negative[url]['fail_count'], 2)


# ── S1-6 probe-budget escalation ───────────────────────────────────────────

class ProbeEscalationTests(_CacheTestCase):
    def test_probe_budget_escalates_then_caps(self):          # S1-6
        url = 'http://t/escalate'
        cache_mod._record_failure(url, 'upstream_timeout')     # fail_count 1
        self.assertEqual(cache_mod._fetch_budget(url), config.PROBE_TIMEOUT)
        cache_mod._record_failure(url, 'upstream_timeout')     # 2
        self.assertEqual(cache_mod._fetch_budget(url), config.PROBE_TIMEOUT * 2)
        cache_mod._record_failure(url, 'upstream_timeout')     # 3
        self.assertEqual(cache_mod._fetch_budget(url), config.PROBE_TIMEOUT * 4)
        cache_mod._record_failure(url, 'upstream_timeout')     # 4
        self.assertEqual(cache_mod._fetch_budget(url), config.REQUEST_TIMEOUT)
        cache_mod._record_failure(url, 'upstream_timeout')     # 5 → stays capped
        self.assertEqual(cache_mod._fetch_budget(url), config.REQUEST_TIMEOUT)

    def test_slow_upstream_gets_full_budget_within_a_few_probes(self):  # S1-6
        # A 5s-needing upstream no longer waits the full 600s streak for a
        # usable budget: the 3rd consecutive failure already probes at 8s.
        url = 'http://t/slow-upstream'
        cache_mod._record_failure(url, 'upstream_timeout')
        cache_mod._record_failure(url, 'upstream_timeout')
        self.assertGreaterEqual(cache_mod._fetch_budget(url), 4.0)

    def test_aged_streak_still_gets_full_budget(self):        # BR-CACHE-20
        url = 'http://t/aged'
        cache_mod._record_failure(url, 'upstream_timeout')
        cache_mod._negative[url]['first_at'] = time.time() - cache_mod._HISTORY_AGE - 1
        self.assertEqual(cache_mod._fetch_budget(url), config.REQUEST_TIMEOUT)

    def test_single_failure_keeps_probe_timeout(self):        # T-CACHE-4b regression
        url = 'http://t/one'
        cache_mod._record_failure(url, 'upstream_timeout')
        self.assertEqual(cache_mod._fetch_budget(url), config.PROBE_TIMEOUT)


# ── S1-5 deadline plumbing ─────────────────────────────────────────────────

class DeadlineTests(_CacheTestCase):
    def test_signature_fifth_param_is_deadline(self):         # S1-5 frozen interface
        import inspect
        self.assertEqual(
            list(inspect.signature(cache_mod.fetch_json).parameters),
            ['url', 'headers', 'ttl', 'encoding', 'deadline'])

    def test_elapsed_deadline_raises_without_network(self):    # S1-5
        called = {'n': 0}

        def _boom(req, timeout=None):
            called['n'] += 1
            raise AssertionError('network must not be touched')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom):
            with self.assertRaises(cache_mod.FetchError) as ctx:
                cache_mod.fetch_json('http://t/dl-expired', ttl=60,
                                     deadline=time.time() - 0.001)
        self.assertEqual(ctx.exception.kind, 'upstream_timeout')
        self.assertEqual(called['n'], 0)
        self.assertNotIn('http://t/dl-expired', cache_mod._negative)
        self.assertEqual(metrics.snapshot()['upstream_fail_total'], {})

    def test_deadline_clamps_network_timeout(self):            # S1-5
        seen = {}

        def _ok(req, timeout=None):
            seen['timeout'] = timeout
            return _FakeResponse(b'ok')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_ok):
            body = cache_mod.fetch_json('http://t/dl-clamp', ttl=60,
                                        deadline=time.time() + 1.5)
        self.assertEqual(body, 'ok')
        self.assertLessEqual(seen['timeout'], 1.5)
        self.assertGreater(seen['timeout'], 0.0)

    def test_no_deadline_keeps_request_timeout(self):          # backward compat
        seen = {}

        def _ok(req, timeout=None):
            seen['timeout'] = timeout
            return _FakeResponse(b'ok')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_ok):
            cache_mod.fetch_json('http://t/dl-none', ttl=60)
        self.assertEqual(seen['timeout'], config.REQUEST_TIMEOUT)

    def test_expired_deadline_still_serves_a_cache_hit(self):  # P1-5
        """The deadline gate must sit *after* the positive cache.

        A slow batch's exhausted budget must never reject data already cached —
        that is exactly the situation the cache exists to absorb.  The old gate
        ran first and returned ``null`` + ``upstream_timeout`` for a fresh hit.
        """
        url = 'http://t/dl-hit'
        cache_mod.cache[url] = {
            'data': 'cached', 'time': time.time(), 'last_access': time.time(),
            'expires_at': time.time() + 100}
        called = {'n': 0}

        def _boom(req, timeout=None):
            called['n'] += 1
            raise AssertionError('network must not be touched on a cache hit')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom):
            body = cache_mod.fetch_json(url, ttl=60, deadline=time.time() - 5)
        self.assertEqual(body, 'cached')
        self.assertEqual(called['n'], 0)

    def test_miss_with_expired_deadline_still_fails_fast(self):  # P1-5 preserved
        called = {'n': 0}

        def _boom(req, timeout=None):
            called['n'] += 1
            raise AssertionError('network must not be touched')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom):
            with self.assertRaises(cache_mod.FetchError) as ctx:
                cache_mod.fetch_json('http://t/dl-miss', ttl=60,
                                     deadline=time.time() - 5)
        self.assertEqual(ctx.exception.kind, 'upstream_timeout')
        self.assertEqual(called['n'], 0)
        self.assertNotIn('http://t/dl-miss', cache_mod._negative)

    def test_election_token_is_released_when_budget_lookup_raises(self):  # P2-10
        """A raise in the election/budget helpers must not leak the token.

        `_effective_timeout` used to run *before* the try/finally, so an
        exception there left the URL permanently elected: every later request
        became a follower and timed out (a permanent single-URL outage).
        """
        url = 'http://t/leak'
        with mock.patch.object(cache_mod, '_effective_timeout',
                               side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                cache_mod.fetch_json(url, ttl=60)
        self.assertNotIn(url, cache_mod._fetch_inflight)      # token released
        # ... and the URL is still usable afterwards.
        with mock.patch.object(cache_mod, 'urlopen',
                               side_effect=lambda req, timeout=None:
                               _FakeResponse(b'ok')):
            self.assertEqual(cache_mod.fetch_json(url, ttl=60), 'ok')


# ── S1-4 / P2-11 hit accounting ────────────────────────────────────────────

class CacheHitRatioTests(_CacheTestCase):
    def test_hit_path_publishes_the_ratio(self):              # P2-11
        url = 'http://t/ratio'
        cache_mod.cache[url] = {
            'data': 'cached', 'time': time.time(), 'last_access': time.time(),
            'expires_at': time.time() + 100}
        cache_mod._cache_stats['hit'] = 3
        cache_mod._cache_stats['miss'] = 1
        with mock.patch.object(cache_mod, 'urlopen',
                               side_effect=AssertionError('no network')):
            self.assertEqual(cache_mod.fetch_json(url, ttl=60), 'cached')
        self.assertEqual(cache_mod._cache_stats['hit'], 4)    # hit was counted
        snap = metrics.snapshot()
        self.assertEqual(snap['cache_hit_ratio'], 0.8)        # 4 / (4 + 1)
        self.assertEqual(snap['cache_entries'], {'url': 1})

    def test_follower_hit_is_counted(self):                   # P2-11
        """The segment-4 follower read used to return without recording a hit."""
        url = 'http://t/follower-hit'

        class _SignallingEvent(threading.Event):
            def __init__(self):
                super().__init__()
                self.waiting = threading.Event()

            def wait(self, timeout=None):
                self.waiting.set()
                return super().wait(timeout)

        ev = _SignallingEvent()
        cache_mod._fetch_inflight[url] = ev

        def fake_leader():
            self.assertTrue(ev.waiting.wait(timeout=2.0))
            cache_mod._cache_put(cache_mod.cache, url, 'body', ttl=60)
            with cache_mod._cache_lock:
                cache_mod._fetch_inflight.pop(url, None)
            ev.set()

        def _boom(req, timeout=None):
            raise AssertionError('network must not be touched')

        t = threading.Thread(target=fake_leader)
        t.start()
        try:
            with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom), \
                    mock.patch.object(cache_mod, 'REQUEST_TIMEOUT', 1.0):
                self.assertEqual(cache_mod.fetch_json(url, ttl=60), 'body')
        finally:
            t.join()
        self.assertEqual(cache_mod._cache_stats['hit'], 1)
        self.assertEqual(cache_mod._cache_stats['miss'], 1)
        self.assertEqual(metrics.snapshot()['cache_hit_ratio'], 0.5)


# ── S1-1 follower gap path ─────────────────────────────────────────────────

class FollowerGapTests(_CacheTestCase):
    def test_follower_wait_timeout_reports_timeout_not_error(self):   # T7 / S1-1
        """Follower's wait window expires while the leader is still alive.

        Before the fix the follower fell into the 'unreachable' gap branch and
        raised ``upstream_error`` (the true cause was publish latency), which
        then fed the code-level cooldown ledger.  It must report a local
        ``upstream_timeout`` and record no failure.
        """
        url = 'http://t/slow-leader'
        entered = threading.Event()

        def slow_ok(req, timeout=None):
            entered.set()
            time.sleep(0.4)
            return _FakeResponse(b'ok')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=slow_ok), \
                mock.patch.object(cache_mod, 'REQUEST_TIMEOUT', 0.05), \
                mock.patch.object(cache_mod, '_FOLLOWER_WAIT_MARGIN', 0.05):
            with ThreadPoolExecutor(max_workers=1) as pool:
                leader = pool.submit(cache_mod.fetch_json, url, None, 60)
                self.assertTrue(entered.wait(timeout=2.0))
                with self.assertRaises(cache_mod.FetchError) as ctx:
                    cache_mod.fetch_json(url, None, 60)
                self.assertEqual(ctx.exception.kind, 'upstream_timeout')
                self.assertEqual(leader.result(timeout=5), 'ok')
        # The follower's local wait must not poison the failure ledger ...
        self.assertEqual(metrics.snapshot()['upstream_fail_total'], {})
        self.assertNotIn(url, cache_mod._negative)
        # ... and the leader's success is cached.
        self.assertEqual(cache_mod.cache[url]['data'], 'ok')

    def test_gap_without_state_or_leader_is_upstream_error(self):     # S1-1 fallback
        """No cache, no negative entry and no live leader ⇒ fail closed."""
        url = 'http://t/gap'

        class _SignallingEvent(threading.Event):
            """An Event that reports when a follower has actually parked on it."""

            def __init__(self):
                super().__init__()
                self.waiting = threading.Event()

            def wait(self, timeout=None):
                self.waiting.set()
                return super().wait(timeout)

        ev = _SignallingEvent()
        cache_mod._fetch_inflight[url] = ev
        released = threading.Event()

        def fake_leader():
            # Simulate a leader that finished the wait window but published
            # nothing (e.g. REV-DES-09 cache-write failure).
            self.assertTrue(ev.waiting.wait(timeout=2.0))
            with cache_mod._cache_lock:
                cache_mod._fetch_inflight.pop(url, None)
            ev.set()
            released.set()

        def _boom(req, timeout=None):
            raise AssertionError('network must not be touched on the gap path')

        t = threading.Thread(target=fake_leader)
        t.start()
        try:
            with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom):
                with self.assertRaises(cache_mod.FetchError) as ctx:
                    cache_mod.fetch_json(url, None, 60)
            self.assertEqual(ctx.exception.kind, 'upstream_error')
            self.assertTrue(released.wait(timeout=2.0))
        finally:
            t.join()


# ── S1-4 metrics published outside the cache locks ─────────────────────────

class MetricsLockDisciplineTests(_CacheTestCase):
    def _lock_held_during(self, lock, fn, *args, **kwargs):
        """Run fn and report the lock-held state observed at each metric write."""
        held = []
        real_incr = cache_mod.metrics.incr
        real_set = cache_mod.metrics.set_gauge

        def _probe():
            acquired = lock.acquire(blocking=False)
            held.append(not acquired)
            if acquired:
                lock.release()

        def spy_incr(name, n=1, key=None):
            _probe()
            return real_incr(name, n=n, key=key)

        def spy_set(name, value, key=None):
            _probe()
            return real_set(name, value, key=key)

        with mock.patch.object(cache_mod.metrics, 'incr', side_effect=spy_incr), \
                mock.patch.object(cache_mod.metrics, 'set_gauge',
                                  side_effect=spy_set):
            fn(*args, **kwargs)
        return held

    def test_cache_put_publishes_after_release(self):         # S1-4
        held = self._lock_held_during(cache_mod._cache_lock,
                                      cache_mod._cache_put,
                                      cache_mod.cache, 'u', 'v', 60)
        self.assertTrue(held)
        self.assertFalse(any(held), 'metrics published while _cache_lock held')

    def test_feed_cache_put_publishes_after_release(self):    # S1-4
        held = self._lock_held_during(cache_mod._feed_cache_lock,
                                      cache_mod.feed_cache_put,
                                      '/feed/x', '<x/>', 30)
        self.assertTrue(held)
        self.assertFalse(any(held), 'metrics published while _feed_cache_lock held')

    def test_record_failure_publishes_after_release(self):    # S1-4
        held = self._lock_held_during(cache_mod._neg_lock,
                                      cache_mod._record_failure,
                                      'http://t/m', 'upstream_error')
        self.assertTrue(held)
        self.assertFalse(any(held), 'metrics published while _neg_lock held')


# ── encoding / hit path ────────────────────────────────────────────────────

class FetchEncodingTests(_CacheTestCase):
    def test_gbk_decoding(self):                              # T-CACHE-15
        body = '龙虎榜'.encode('gbk')
        with mock.patch.object(
                cache_mod, 'urlopen',
                side_effect=lambda req, timeout=None: _FakeResponse(body)):
            out = cache_mod.fetch_json('http://t/gbk', ttl=300, encoding='gbk')
        self.assertEqual(out, '龙虎榜')

    def test_default_utf8_unchanged(self):                    # T-CACHE-15
        with mock.patch.object(
                cache_mod, 'urlopen',
                side_effect=lambda req, timeout=None:
                _FakeResponse('中文'.encode('utf-8'))):
            out = cache_mod.fetch_json('http://t/utf8', ttl=300)
        self.assertEqual(out, '中文')

    def test_hit_path_skips_network(self):                    # T-CACHE-1
        cache_mod.cache['http://t/hit'] = {
            'data': 'cached', 'time': time.time(), 'last_access': time.time(),
            'expires_at': time.time() + 100}
        called = {'n': 0}

        def _boom(req, timeout=None):
            called['n'] += 1
            raise AssertionError('network must not be touched on a cache hit')

        with mock.patch.object(cache_mod, 'urlopen', side_effect=_boom):
            self.assertEqual(cache_mod.fetch_json('http://t/hit', ttl=60),
                             'cached')
        self.assertEqual(called['n'], 0)
        self.assertEqual(cache_mod._cache_stats['hit'], 1)

    def test_post_fetch_cache_write_error_not_poisoning(self):  # T-CACHE-20
        url = 'http://t/poison'
        with mock.patch.object(
                cache_mod, 'urlopen',
                side_effect=lambda req, timeout=None: _FakeResponse(b'ok')), \
                mock.patch.object(cache_mod, '_cache_put',
                                  side_effect=RuntimeError('boom')):
            self.assertEqual(cache_mod.fetch_json(url, ttl=60), 'ok')
        self.assertNotIn(url, cache_mod._negative)            # not classed as failure
        self.assertEqual(metrics.snapshot().get('upstream_fail_total', {}), {})


if __name__ == '__main__':
    unittest.main()
