"""Unit tests for the data layer (stock_api / market_api / cdp_engine).

Covers the change-set contracts: deadline propagation, the shared code-level
failure ledger, the ``(results, errors)`` batch pipeline, pool/cache
decoupling, the enumerated error kinds, ``page_data`` defensiveness and the
Chrome restart-window state machine.
"""

import threading
import time
import unittest
from collections import OrderedDict
from unittest.mock import Mock, patch

from china_finance_rss import cdp_engine, config, metrics, market_api, stock_api
from china_finance_rss.cache import FetchError

# Captured right after import: cdp_engine publishes the initial idle window at
# module load (REV-DES-19), so the gauge must already be present.
_INITIAL_SNAPSHOT_KEYS = set(metrics.snapshot())


class _StopLoop(BaseException):
    """Escapes _prefetch_loop's `except Exception` to end the loop in tests."""


def _reset_stock_state():
    with stock_api._fail_ledger_lock:
        stock_api._fail_ledger.clear()
        # S1-3 housekeeping clocks: reset so a test can't inherit the previous
        # test's rate-limit window.
        stock_api._cooldown_published_at = 0.0
        stock_api._fail_ledger_pruned_at = 0.0
    for pool, cache, cache_ts, lock in stock_api._DOMAIN_STORES.values():
        with lock:
            pool.clear()
            cache.clear()
            cache_ts.clear()
    with stock_api._prefetch_cursor_lock:
        stock_api._prefetch_cursor.clear()
    with stock_api._sector_cache_lock:
        stock_api._sector_cache.clear()
    with stock_api._basic_sector_lock:
        stock_api._basic_sector_cache.clear()
    metrics.reset()


# ── stock_api: failure ledger ──────────────────────────────────────────────

class FailLedgerTests(unittest.TestCase):
    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    def test_cooldown_after_three_failures_blocks_network(self):
        calls = []

        def _fail(code, deadline=None, ttl=None):
            calls.append(code)
            raise FetchError('upstream_error')

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_fail):
            for _ in range(3):
                stock_api.handle_cls_stock_batch(['sh600519'])
            self.assertEqual(len(calls), 3)
            self.assertTrue(any(e[1] == 'sh600519'
                                for e in stock_api.code_cooldown_list()))
            out = stock_api.handle_cls_stock_batch(['sh600519'])
        self.assertEqual(len(calls), 3)                       # 4th: no network
        self.assertIsNone(out['sh600519'])
        self.assertEqual(out['_errors']['sh600519'], 'upstream_error')

    def test_success_clears_consecutive_failures(self):
        seq = [FetchError('upstream_error'), FetchError('upstream_error'),
               {'data': 1}, FetchError('upstream_error')]

        def _flaky(code, deadline=None, ttl=None):
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_flaky):
            for _ in range(4):
                stock_api.handle_cls_stock_batch(['sh600519'])
        entry = stock_api._fail_ledger_get('quote', 'sh600519')
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], 1)                         # reset by the success

    def test_none_result_is_no_data_not_failure(self):
        with patch.object(stock_api, 'fetch_cls_stock_detail',
                          side_effect=lambda code, deadline=None, ttl=None: None):
            out = stock_api.handle_cls_stock_batch(['sh600519'])
        self.assertIsNone(out['sh600519'])
        self.assertNotIn('_errors', out)
        self.assertIsNone(stock_api._fail_ledger_get('quote', 'sh600519'))

    def test_aged_entry_is_dropped_and_recounted(self):
        now = time.time()
        with stock_api._fail_ledger_lock:
            stock_api._fail_ledger[('quote', 'sh600519')] = [
                3, now - 1, 'upstream_error', now - stock_api.FAIL_COOLDOWN - 1]
        self.assertIsNone(stock_api._fail_ledger_get('quote', 'sh600519', now))
        with stock_api._fail_ledger_lock:
            self.assertNotIn(('quote', 'sh600519'), stock_api._fail_ledger)
        stock_api._fail_ledger_record_failure('quote', 'sh600519', 'upstream_error', now)
        self.assertEqual(stock_api._fail_ledger_get('quote', 'sh600519', now)[0], 1)

    def test_cooldown_open_is_published_as_gauge(self):
        """S1-3/P1-4: opening a cooldown still updates the published gauge.

        Publication is rate-limited to one sample per interval, so the test
        advances the interval clock rather than relying on the old (removed)
        opened-transition bypass.
        """
        now = time.time()
        stock_api._cooldown_published_at = now          # suppress the interval sample
        for _ in range(2):
            stock_api._fail_ledger_record_failure(
                'quote', 'sh600519', 'upstream_error', now)
        self.assertEqual(metrics.snapshot()['code_cooldown_list'], [])
        stock_api._cooldown_published_at = now - stock_api._COOLDOWN_PUBLISH_INTERVAL - 1
        stock_api._fail_ledger_record_failure(
            'quote', 'sh600519', 'upstream_error', now)   # 3rd ⇒ cooldown opens
        live = metrics.snapshot()['code_cooldown_list']
        self.assertIn(['quote', 'sh600519', now + stock_api.FAIL_COOLDOWN], live)

    def test_cooldown_open_publish_is_rate_limited(self):
        """P1-4: the opened transition must not bypass the publish interval.

        Bypassing it rebuilt the full O(n) `code_cooldown_list` from *inside*
        the ledger lock on every write — a cold-start upstream outage made the
        failure path pay O(n) per failure.
        """
        now = time.time()
        stock_api._cooldown_published_at = now          # inside the interval
        for _ in range(3):                              # 3rd opens the cooldown
            stock_api._fail_ledger_record_failure(
                'quote', 'sh600519', 'upstream_error', now)
        self.assertEqual(metrics.snapshot()['code_cooldown_list'], [])

    def test_ledger_cap_eviction_is_o1_and_never_sorts(self):
        """P1-4: at the hard cap, eviction must be O(1) — never a full sort.

        The old code ran `sorted()` over the whole ledger on *every* write at
        cap (serialized on the ledger lock); steady failures refreshed every
        timestamp, so the aged-scan never freed a slot and the S1-3 O(n²)
        degradation survived.  No production test ever reached the cap.
        """
        now = time.time()
        with patch.object(stock_api, '_FAIL_LEDGER_MAX', 10), \
             patch('builtins.sorted', side_effect=AssertionError('sorted at cap')):
            for i in range(25):
                stock_api._fail_ledger_record_failure(
                    'quote', f'sh{600000 + i:06d}', 'upstream_error', now)
        with stock_api._fail_ledger_lock:
            self.assertEqual(len(stock_api._fail_ledger), 10)
            self.assertNotIn(('quote', 'sh600000'), stock_api._fail_ledger)  # oldest out
            self.assertIn(('quote', 'sh600024'), stock_api._fail_ledger)

    def test_failure_path_does_not_rebuild_snapshot_per_write(self):
        """S1-3: the O(n) `code_cooldown_list` build must not run per failure.

        One rebuild per failure write made an n-failure storm O(n²) while
        holding `_fail_ledger_lock`, i.e. the failure path got *slower* as the
        failure set grew.  The build count must stay bounded.
        """
        now = time.time()
        with patch.object(stock_api, '_cooldown_snapshot_locked',
                          side_effect=stock_api._cooldown_snapshot_locked) as snap:
            for i in range(2000):
                stock_api._fail_ledger_record_failure(
                    'quote', f'sh{700000 + i}', 'upstream_error', now)
            builds = snap.call_count
        self.assertLess(builds, 10)                 # bounded, not ~2000
        with stock_api._fail_ledger_lock:
            self.assertEqual(len(stock_api._fail_ledger), 2000)

    def test_bulk_prune_is_rate_limited(self):
        """S1-3: the O(n) aged-scan is housekeeping, not per-write work."""
        now = time.time()
        with stock_api._fail_ledger_lock:
            stock_api._fail_ledger[('quote', 'sh600001')] = [
                1, 0.0, 'upstream_error', 0.0]              # long aged out
        stock_api._fail_ledger_pruned_at = now              # inside the interval
        stock_api._fail_ledger_record_failure(
            'quote', 'sh600002', 'upstream_error', now)
        with stock_api._fail_ledger_lock:
            self.assertIn(('quote', 'sh600001'), stock_api._fail_ledger)
        stock_api._fail_ledger_record_failure(
            'quote', 'sh600003', 'upstream_error',
            now + stock_api._FAIL_LEDGER_PRUNE_INTERVAL + 1)
        with stock_api._fail_ledger_lock:
            self.assertNotIn(('quote', 'sh600001'), stock_api._fail_ledger)

    def test_exhausted_budget_is_bounded_and_not_recorded(self):
        """P1-1: an exhausted *local* budget is not an upstream failure.

        It must stay out of the 120s cooldown ledger (cache.md S1-1 parity) —
        the old expectation recorded it, which is exactly what let one slow
        batch cool down the whole pool tail.  The client still sees the timeout
        error shape.
        """
        codes = [f'sh{600000 + i}' for i in range(50)]
        calls = []

        def _never(code, deadline=None, ttl=None):
            calls.append(code)
            return {'data': code}

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_never):
            start = time.time()
            out = stock_api.handle_cls_stock_batch(codes, deadline=time.time() - 1)
            elapsed = time.time() - start
        self.assertEqual(calls, [])                           # no network at all
        self.assertLess(elapsed, 0.5)
        self.assertEqual(out['_errors'][codes[0]], 'upstream_timeout')
        self.assertIsNone(stock_api._fail_ledger_get('quote', codes[0]))
        with stock_api._fail_ledger_lock:
            self.assertEqual(stock_api._fail_ledger, {})      # ledger untouched

    def test_local_budget_exhaustion_never_opens_cooldown(self):
        """P1-1: repeated local timeouts must not cool a code down.

        The old behaviour wrote every local timeout to the ledger, so a slow
        batch turned the pool tail into a 120s data outage driven purely by our
        own budget (a self-amplifying positive feedback loop).  A real fetch
        must still be attempted afterwards.
        """
        code = 'sh600519'
        with patch.object(stock_api, 'fetch_cls_stock_detail',
                          side_effect=lambda c, deadline=None, ttl=None: {'data': c}):
            for _ in range(5):
                out = stock_api.handle_cls_stock_batch([code], deadline=time.time() - 1)
                self.assertEqual(out['_errors'][code], 'upstream_timeout')
            self.assertEqual(stock_api.code_cooldown_list(), [])
            fresh = stock_api.handle_cls_stock_batch([code])   # no deadline ⇒ real path
        self.assertEqual(fresh[code], {'data': code})

    def test_three_value_domains(self):
        def _fail_or_none(code, deadline=None, ttl=None):
            if code == 'sh600001':
                raise FetchError('upstream_error')
            return None

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_fail_or_none):
            out = stock_api.handle_cls_stock_batch(['sh600001', 'badcode', 'sh600002'])
        self.assertIsNone(out['sh600001'])
        self.assertIsNone(out['badcode'])
        self.assertIsNone(out['sh600002'])
        self.assertEqual(set(out['_errors']), {'sh600001'})
        self.assertIn(out['_errors']['sh600001'], FetchError.KINDS)


# ── stock_api: batch pipeline ──────────────────────────────────────────────

class BatchPipelineTests(unittest.TestCase):
    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    def test_run_batch_returns_two_dicts(self):
        def _f(code, deadline=None, ttl=None):
            if code.endswith('1'):
                raise FetchError('upstream_timeout')
            return {'code': code}

        results, errors = stock_api._run_batch(_f, ['sh600001', 'sh600002'])
        self.assertEqual(set(results), {'sh600001', 'sh600002'})
        self.assertEqual(errors, {'sh600001': 'upstream_timeout'})

    def test_serial_batch_preserves_order(self):
        seen = []

        def _f(code, deadline=None, ttl=None):
            seen.append(code)
            return code

        stock_api._run_batch(_f, ['sh600003', 'sh600001', 'sh600002'], concurrent=False)
        self.assertEqual(seen, ['sh600003', 'sh600001', 'sh600002'])

    def test_shards_all_codes_without_truncation(self):
        codes = [f'sh{700000 + i}' for i in range(60)]
        seen = set()

        def _ok(code, deadline=None, ttl=None):
            seen.add(code)
            return {'code': code}

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_ok):
            out = stock_api.handle_cls_stock_batch(codes)
        self.assertEqual(set(out), set(codes))
        self.assertEqual(seen, set(codes))

    def test_reserved_keys_matrix(self):
        def _ok(code, deadline=None, ttl=None):
            return {'code': code}

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_ok):
            out = stock_api.handle_cls_stock_batch(['sh600519'])
        self.assertEqual(set(out), {'sh600519'})

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_ok):
            out = stock_api.handle_cls_stock_batch(['sh600519'], dropped=20)
        self.assertTrue(out['_truncated'])
        self.assertEqual(out['_dropped_count'], 20)

    def test_endpoint_ttl_matches_policy(self):
        captured = {}

        def _fake_fetch_json(url, headers=None, ttl=None, encoding='utf-8',
                             deadline=None):
            captured['ttl'] = ttl
            return '{"code": 200, "data": {"x": 1}}'

        with patch.object(stock_api, 'fetch_json', side_effect=_fake_fetch_json):
            stock_api.handle_cls_fundflow(['sh600519'])
        self.assertEqual(captured['ttl'], config.cache_policy('fundflow')['ttl'])

    def test_internal_type_error_is_not_retried(self):
        """P2-④: a TypeError raised *inside* the fetcher is a real failure.

        The old fallback swallowed it, called the fetcher a second time (double
        execution of a fetch) and still reported the wrong classification.
        """
        calls = []

        def _bad(code, deadline=None, ttl=None):
            calls.append(code)
            return 1 + 'x'                        # TypeError in the body

        results, errors = stock_api._run_batch(_bad, ['sh600001'])
        self.assertEqual(errors, {'sh600001': 'upstream_error'})
        self.assertEqual(calls, ['sh600001'])     # called exactly once

    def test_signature_mismatch_double_keeps_deadline(self):
        """P2-④: the call-frame fallback still passes the parameters a
        signature-mismatched double accepts (here `deadline`, no `ttl`), so the
        budget is not silently dropped."""
        seen = {}
        deadline = time.time() + 10

        def _old(code, deadline=None):            # rejects `ttl`
            seen['deadline'] = deadline
            return {'code': code}

        results, errors = stock_api._run_batch(_old, ['sh600001'], deadline=deadline)
        self.assertEqual(results, {'sh600001': {'code': 'sh600001'}})
        self.assertEqual(errors, {})
        self.assertEqual(seen['deadline'], deadline)

    def test_bare_double_still_supported(self):
        seen = []

        def _bare(code):                          # accepts neither kwarg
            seen.append(code)
            return {'code': code}

        results, errors = stock_api._run_batch(_bare, ['sh600001'])
        self.assertEqual(results, {'sh600001': {'code': 'sh600001'}})
        self.assertEqual(errors, {})
        self.assertEqual(seen, ['sh600001'])

    def test_pool_eviction_leaves_cache_untouched(self):
        codes = ['sh600001', 'sh600002', 'sh600003']
        pool = {c: float(i) for i, c in enumerate(codes, 1)}
        cache = OrderedDict((c, {'code': c}) for c in codes)
        cache_ts = {c: time.time() for c in codes}
        lock = threading.Lock()
        policy = {'ttl': 100, 'pool_max': 2, 'cache_max': 10}

        stock_api._process_chunk(
            ['sh600001', 'sh600002'], 'quote', policy,
            lambda code, deadline=None, ttl=None: None,
            pool=pool, cache=cache, cache_ts=cache_ts, lock=lock)

        self.assertLessEqual(len(pool), 2)
        self.assertEqual(set(cache), set(codes))              # data cache untouched
        self.assertEqual(set(cache_ts), set(codes))

    def test_cache_true_lru_eviction(self):
        cache, cache_ts = OrderedDict(), {}
        lock = threading.Lock()
        stock_api._cache_store(cache, cache_ts, lock, 'sh600001', {'a': 1}, 2, 'quote')
        stock_api._cache_store(cache, cache_ts, lock, 'sh600002', {'b': 2}, 2, 'quote')
        with lock:
            cache.move_to_end('sh600001')                     # simulate a hit
        stock_api._cache_store(cache, cache_ts, lock, 'sh600003', {'c': 3}, 2, 'quote')
        self.assertEqual(list(cache), ['sh600001', 'sh600003'])
        self.assertEqual(metrics.snapshot()['cache_entries']['quote'], 2)

    def test_cached_batch_reads_without_network(self):
        codes = ['sh600001', 'sh600002']
        with stock_api._basic_info_cache_lock:
            for code in codes:
                stock_api._basic_info_cache[code] = {'code': code}
                stock_api._basic_info_cache_ts[code] = time.time()
        with patch.object(stock_api, 'fetch_json',
                          side_effect=AssertionError('network used')):
            out = stock_api.cached_batch('quote', codes + ['sh600003'])
        self.assertEqual(set(out), set(codes))


# ── stock_api: canonical code identity (P1-6) ──────────────────────────────

class CanonicalCodePipelineTests(unittest.TestCase):
    """P1-6: one stock ⇒ one pool/cache/ledger key, whatever the spelling."""

    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    def test_spellings_share_one_upstream_fetch(self):
        seen = []

        def _ok(code, deadline=None, ttl=None):
            seen.append(code)
            return {'code': code}

        with patch.object(stock_api, 'fetch_cls_stock_detail', side_effect=_ok):
            out = stock_api.handle_cls_stock_batch(
                ['SH600519', '600519.SH', 'sh600519'])
        self.assertEqual(seen, ['sh600519'])                 # one canonical call
        self.assertEqual(set(out), {'SH600519', '600519.SH', 'sh600519'})
        for code in out:                                     # every spelling answered
            self.assertEqual(out[code], {'code': 'sh600519'})

    def test_pool_cache_and_ledger_use_the_canonical_key(self):
        pool, cache, cache_ts = {}, OrderedDict(), {}
        lock = threading.Lock()
        policy = {'ttl': 100, 'pool_max': 10, 'cache_max': 10}
        stock_api._process_chunk(
            ['600519.SH'], 'quote', policy,
            lambda code, deadline=None, ttl=None: {'code': code},
            pool=pool, cache=cache, cache_ts=cache_ts, lock=lock)
        self.assertEqual(list(pool), ['sh600519'])
        self.assertEqual(list(cache), ['sh600519'])

    def test_invalid_code_is_null_without_error(self):
        with patch.object(stock_api, 'fetch_cls_stock_detail',
                          side_effect=AssertionError('invalid code fetched')):
            out = stock_api.handle_cls_stock_batch(['600519', 'nope'])
        self.assertIsNone(out['600519'])
        self.assertIsNone(out['nope'])
        self.assertNotIn('_errors', out)


# ── stock_api: self-built error kinds / double-count guard ─────────────────

class ErrorClassificationTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_fetch_rest_json_counts_bad_json(self):
        with patch.object(stock_api, 'fetch_json', return_value='not json'):
            with self.assertRaises(FetchError) as cm:
                stock_api._fetch_rest_json('http://x', {}, 10)
        self.assertEqual(cm.exception.kind, 'upstream_error')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['upstream_error'], 1)

    def test_fetch_rest_json_rejects_non_dict(self):
        for payload in ('[1, 2]', '"scalar"'):
            with patch.object(stock_api, 'fetch_json', return_value=payload):
                with self.assertRaises(FetchError) as cm:
                    stock_api._fetch_rest_json('http://x', {}, 10)
            self.assertEqual(cm.exception.kind, 'upstream_error')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['upstream_error'], 2)

    def test_cache_failure_is_not_double_counted(self):
        with patch.object(stock_api, 'fetch_json',
                          side_effect=FetchError('upstream_timeout')):
            out = stock_api.handle_cls_stock_batch(['sh600519'])
        self.assertEqual(out['_errors']['sh600519'], 'upstream_timeout')
        fails = metrics.snapshot().get('upstream_fail_total', {})
        self.assertNotIn('upstream_timeout', fails)           # cache owns this count
        self.assertGreaterEqual(metrics.snapshot()['upstream_fetch_total']['quote'], 1)

    def test_rest_call_threads_deadline_into_fetch_json(self):
        """S1-5: the R13 budget must reach `fetch_json`, whose urlopen timeout
        is then clamped to the remaining budget instead of a flat 10s."""
        captured = {}

        def _fake(url, headers=None, ttl=None, encoding='utf-8', deadline=None):
            captured['deadline'] = deadline
            return '{"code": 200, "data": {}}'

        deadline = time.time() + 0.5
        with patch.object(stock_api, 'fetch_json', side_effect=_fake):
            stock_api._fetch_rest_json('http://x', {}, 10, deadline)
        self.assertEqual(captured['deadline'], deadline)

    def test_direct_fetch_uses_the_rest_funnel_and_counts_once(self):
        """P2-①: `_direct_fetch`'s REST fallback must go through `fetch_json`
        (URL/negative cache + single-flight), and one logical fetch must count
        `upstream_fetch_total` exactly once (it used to count twice)."""
        with patch.object(stock_api, '_evaluate_fetch_any', return_value=None), \
             patch.object(stock_api, 'fetch_json',
                          return_value='{"code": 200, "data": {"x": 1}}') as fj:
            out = stock_api._direct_fetch('http://x', {}, 'fundflow')
        self.assertEqual(out, {'x': 1})
        fj.assert_called_once()
        self.assertEqual(metrics.snapshot()['upstream_fetch_total']['fundflow'], 1)

    def test_direct_fetch_cdp_hit_counts_once_without_rest(self):
        with patch.object(stock_api, '_evaluate_fetch_any',
                          return_value={'code': 200, 'data': {'y': 2}}), \
             patch.object(stock_api, 'fetch_json',
                          side_effect=AssertionError('REST used')):
            out = stock_api._direct_fetch('http://x', {}, 'fundflow')
        self.assertEqual(out, {'y': 2})
        self.assertEqual(metrics.snapshot()['upstream_fetch_total']['fundflow'], 1)

    def test_direct_fetch_rest_failure_is_not_double_counted(self):
        with patch.object(stock_api, '_evaluate_fetch_any', return_value=None), \
             patch.object(stock_api, 'fetch_json',
                          side_effect=FetchError('upstream_timeout')):
            with self.assertRaises(FetchError) as cm:
                stock_api._direct_fetch('http://x', {}, 'fundflow')
        self.assertEqual(cm.exception.kind, 'upstream_timeout')   # cache counted it
        self.assertNotIn('upstream_timeout',
                         metrics.snapshot().get('upstream_fail_total', {}))


# ── stock_api: basic_info sector cache (BUG-P6C-01 fix path) ───────────────

class BasicInfoSectorCacheTests(unittest.TestCase):
    """BUG-P6C-01 root cause 2: `fetch_cls_basic_info`'s second REST call
    (stock detail → `sector_name`) must be served from the 7-day sector cache,
    so a per-tick quote refresh costs 1 call/code after first sight — with the
    returned value byte-identical to the uncached path."""

    CODE = 'sh600519'
    SECTOR = '食品饮料行业'

    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    def _canned(self, calls):
        def _fake(url, headers, ttl, deadline=None):
            calls.append(url)
            if '/stock/basic' in url:                 # phase 1: quote (fatal)
                return {'code': 200,
                        'data': {'secu_code': self.CODE, 'last_px': 1.0}}
            return {'code': 200,                      # phase 2: detail (sector)
                    'data': {'secu_code': self.CODE,
                             'primary_industry': {'plate_name': self.SECTOR}}}
        return _fake

    def test_second_detail_call_is_served_from_cache(self):
        calls = []
        with patch.object(stock_api, '_fetch_rest_json', side_effect=self._canned(calls)):
            first = stock_api.fetch_cls_basic_info(self.CODE)
            second = stock_api.fetch_cls_basic_info(self.CODE)

        self.assertEqual(first['sector_name'], self.SECTOR)
        self.assertEqual(second['sector_name'], self.SECTOR)   # same value
        self.assertEqual(calls.count(f'{config._STOCK_DETAIL_BASE_URL}'
                                     f'?secu_code={self.CODE}'), 1)  # cached
        detail = [c for c in calls if '/detail?' in c]
        self.assertEqual(len(detail), 1)

    def test_cache_hit_makes_no_detail_call_at_all(self):
        calls = []
        with patch.object(stock_api, '_fetch_rest_json', side_effect=self._canned(calls)):
            stock_api.fetch_cls_basic_info(self.CODE)
            calls.clear()
            second = stock_api.fetch_cls_basic_info(self.CODE)

        self.assertEqual(second['sector_name'], self.SECTOR)
        # only the fatal quote call and the (always-fresh) depth call remain —
        # the sector detail call is fully served from its 7-day cache
        self.assertEqual(calls, [
            f'{config._BASIC_INFO_BASE_URL}?secu_code={self.CODE}',
            f'{config._STOCK_DEPTH_URL}?secu_code={self.CODE}&field=five',
        ])
        self.assertEqual([c for c in calls if '/detail?' in c], [])

    def test_unexpired_entry_is_served_from_cache(self):
        """Within the TTL the entry is returned verbatim (boundary-safe: the
        cut-off is `now - ts > ttl`, so `ttl - 1` is still a hit)."""
        stock_api._basic_sector_put(self.CODE, self.SECTOR, now=0.0)
        ttl = config.cache_policy('sector')['ttl']
        self.assertEqual(stock_api._basic_sector_get(self.CODE, now=ttl - 1),
                         self.SECTOR)

    def test_expired_entry_is_not_served_and_is_dropped(self):
        """Past the TTL the stale value must not be returned.  Expiry is a
        lazy delete, so this single read both refuses the value and evicts the
        entry — a second read cannot resurrect it."""
        stock_api._basic_sector_put(self.CODE, self.SECTOR, now=0.0)
        ttl = config.cache_policy('sector')['ttl']
        self.assertIsNone(stock_api._basic_sector_get(self.CODE, now=ttl + 1))
        with stock_api._basic_sector_lock:
            self.assertNotIn(self.CODE, stock_api._basic_sector_cache)

    def test_expired_entry_triggers_refetch(self):
        """An expired entry is a cache miss on the product path: the next
        `fetch_cls_basic_info` re-pays the detail call and returns the fresh
        value, rather than serving the stale one."""
        stock_api._basic_sector_put(self.CODE, self.SECTOR + '_stale', now=0.0)
        calls = []
        with patch.object(stock_api, '_fetch_rest_json',
                          side_effect=self._canned(calls)):
            out = stock_api.fetch_cls_basic_info(self.CODE)

        self.assertEqual(out['sector_name'], self.SECTOR)     # not the stale one
        self.assertEqual([c for c in calls if '/detail?' in c],
                         [f'{config._STOCK_DETAIL_BASE_URL}?secu_code={self.CODE}'])

    def test_empty_sector_is_not_cached(self):
        with patch.object(stock_api, '_fetch_rest_json',
                          return_value={'code': 200, 'data': {}}):
            stock_api.fetch_cls_basic_info(self.CODE)
        self.assertIsNone(stock_api._basic_sector_get(self.CODE))

    def test_failed_phase_one_skips_the_detail_call(self):
        """The sector would be discarded anyway ⇒ no wasted upstream call."""
        calls = []

        def _fail(url, headers, ttl, deadline=None):
            calls.append(url)
            return {'code': 500}

        with patch.object(stock_api, '_fetch_rest_json', side_effect=_fail):
            with self.assertRaises(FetchError):
                stock_api.fetch_cls_basic_info(self.CODE)
        self.assertEqual(calls, [f'{config._BASIC_INFO_BASE_URL}?secu_code={self.CODE}'])


# ── stock_api: five-level order book (depth domain) ────────────────────────

class StockDepthTests(unittest.TestCase):
    """任务 2b: `fetch_cls_stock_depth` — 21-field payload, honest empty
    semantics (None, never a fabricated all-zero book) and non-fatal failure."""

    CODE = 'sh600519'
    INDEX = 'sh000001'
    BJ = 'bj430047'

    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    @staticmethod
    def _book():
        """A realistic five-band payload (20 value fields + preclose_px)."""
        data = {'preclose_px': 1500.0}
        for level in range(1, 6):
            data[f'b_px_{level}'] = 1499.0 - level
            data[f'b_amount_{level}'] = 100 * level
            data[f's_px_{level}'] = 1501.0 + level
            data[f's_amount_{level}'] = 200 * level
        return data

    def test_url_uses_canonical_prefixed_form_and_field_five(self):
        calls = []

        def _fake(url, headers, ttl, deadline=None):
            calls.append(url)
            return {'code': 200, 'data': self._book()}

        with patch.object(stock_api, '_fetch_rest_json', side_effect=_fake):
            out = stock_api.fetch_cls_stock_depth(self.CODE)
        self.assertEqual(calls, [
            f'{config._STOCK_DEPTH_URL}?secu_code={self.CODE}&field=five'])
        self.assertEqual(out['b_px_1'], 1498.0)
        self.assertEqual(out['preclose_px'], 1500.0)

    def test_returns_none_for_empty_data_dict(self):
        """北京所 (`bj*`) / 非法码: upstream returns `data: {}` — no book."""
        for code in (self.BJ, 'sh999999'):
            with patch.object(stock_api, '_fetch_rest_json',
                              return_value={'code': 200, 'data': {}}):
                self.assertIsNone(stock_api.fetch_cls_stock_depth(code))

    def test_returns_none_for_all_zero_band(self):
        """指数 (sh000001 / sz399001) have no order book: every band field 0."""
        zero = {f: 0 for f in stock_api._DEPTH_VALUE_FIELDS}
        zero['preclose_px'] = 3200.0
        with patch.object(stock_api, '_fetch_rest_json',
                          return_value={'code': 200, 'data': zero}):
            self.assertIsNone(stock_api.fetch_cls_stock_depth(self.INDEX))

    def test_returns_none_when_one_band_field_is_nonzero(self):
        """The all-zero test must not be over-broad: a single live band means a
        real book."""
        data = {f: 0 for f in stock_api._DEPTH_VALUE_FIELDS}
        data['s_amount_5'] = 1
        with patch.object(stock_api, '_fetch_rest_json',
                          return_value={'code': 200, 'data': data}):
            self.assertEqual(stock_api.fetch_cls_stock_depth(self.CODE), data)
        # the successful fetch also populates the depth terminal cache, making
        # DOMAIN_MATRIX['depth']'s pool_max/cache_max live settings
        self.assertEqual(stock_api.cached_batch('depth', [self.CODE]),
                         {self.CODE: data})
        with stock_api._basic_depth_cache_lock:
            self.assertIn(self.CODE, stock_api._basic_depth_pool)

    def test_transport_failure_is_non_fatal(self):
        """A depth outage returns None and does not raise a FetchError."""
        with patch.object(stock_api, '_fetch_rest_json',
                          side_effect=FetchError('upstream_timeout', url='u')):
            self.assertIsNone(stock_api.fetch_cls_stock_depth(self.CODE))

    def test_semantic_failure_is_non_fatal(self):
        with patch.object(stock_api, '_fetch_rest_json',
                          return_value={'code': 500}):
            self.assertIsNone(stock_api.fetch_cls_stock_depth(self.CODE))

    def test_depth_failure_does_not_withhold_the_quote(self):
        """任务 2b: 五档取数失败不得影响 quote 主数据."""
        def _fake(url, headers, ttl, deadline=None):
            if '/volume?' in url:
                raise FetchError('upstream_error', url=url)
            if '/stock/basic' in url:
                return {'code': 200, 'data': {'secu_code': self.CODE, 'last_px': 1.0}}
            return {'code': 200, 'data': {}}

        with patch.object(stock_api, '_fetch_rest_json', side_effect=_fake):
            out = stock_api.fetch_cls_basic_info(self.CODE)
        self.assertEqual(out['data']['last_px'], 1.0)   # quote survived
        self.assertNotIn('depth', out)                 # no fabricated book

    def test_depth_is_attached_to_the_quote_payload(self):
        book = self._book()

        def _fake(url, headers, ttl, deadline=None):
            if '/volume?' in url:
                return {'code': 200, 'data': book}
            if '/stock/basic' in url:
                return {'code': 200, 'data': {'secu_code': self.CODE, 'last_px': 1.0}}
            return {'code': 200, 'data': {}}

        with patch.object(stock_api, '_fetch_rest_json', side_effect=_fake):
            out = stock_api.fetch_cls_basic_info(self.CODE)
        self.assertEqual(out['depth'], book)           # additive, same tick


# ── stock_api: f10 CDP degradation (A') ────────────────────────────────────

class _FakePage:
    def __init__(self):
        self._navigate_lock = threading.RLock()

    def get_data(self):
        return {}


class F10CdpTests(unittest.TestCase):
    def setUp(self):
        self._saved_engine = config.cdp_engine
        _reset_stock_state()

    def tearDown(self):
        config.cdp_engine = self._saved_engine
        _reset_stock_state()

    def test_engine_none_raises_cdp_unavailable(self):
        config.cdp_engine = None
        metrics.reset()
        with self.assertRaises(FetchError) as cm:
            stock_api.fetch_cls_f10('sh600519')
        self.assertEqual(cm.exception.kind, 'cdp_unavailable')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['cdp_unavailable'], 1)

    def test_no_nav_pages_raises(self):
        class _Eng:
            ready = True

            def get_page(self, name):
                return None

        config.cdp_engine = _Eng()
        metrics.reset()
        with self.assertRaises(FetchError) as cm:
            stock_api.fetch_cls_f10('sh600519')
        self.assertEqual(cm.exception.kind, 'cdp_unavailable')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['cdp_unavailable'], 1)

    def test_spent_budget_raises(self):
        class _Eng:
            ready = True

            def get_page(self, name):
                return _FakePage()

        config.cdp_engine = _Eng()
        metrics.reset()
        with self.assertRaises(FetchError) as cm:
            stock_api.fetch_cls_f10('sh600519', deadline=time.time() - 1)
        self.assertEqual(cm.exception.kind, 'cdp_unavailable')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['cdp_unavailable'], 1)

    def test_navigated_but_dateless_raises(self):
        class _Eng:
            ready = True

            def get_page(self, name):
                return _FakePage()

        config.cdp_engine = _Eng()
        metrics.reset()
        with patch.object(stock_api, '_navigate_f10', return_value=True), \
             patch.object(stock_api, 'page_data', return_value=None):
            with self.assertRaises(FetchError) as cm:
                stock_api.fetch_cls_f10('sh600519')
        self.assertEqual(cm.exception.kind, 'cdp_unavailable')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['cdp_unavailable'], 1)

    def test_data_for_another_stock_counts_cdp_unavailable(self):
        """P1-6: 'has data but does not match' is counted, never a silent None.

        ``None`` means "no data, not counted", so the old behaviour re-paid a
        full CDP navigation on every tick with no `_errors` signal.  It must now
        degrade as `cdp_unavailable`.
        """
        class _Eng:
            ready = True

            def get_page(self, name):
                return _FakePage()

        config.cdp_engine = _Eng()
        metrics.reset()
        with patch.object(stock_api, '_navigate_f10', return_value=True), \
             patch.object(stock_api, 'page_data',
                          return_value={'stock_company_info': {
                              'basic_info': {'SecuCode': 'sz000001'}}}):
            with self.assertRaises(FetchError) as cm:
                stock_api.fetch_cls_f10('sh600519')
        self.assertEqual(cm.exception.kind, 'cdp_unavailable')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['cdp_unavailable'], 1)

    def test_matching_spelling_variants_match(self):
        """P1-6: the upstream fixed spelling matches either accepted ingress form."""
        self.assertTrue(stock_api._company_info_matches(
            {'basic_info': {'SecuCode': 'sh600519'}}, '600519.SH'))
        self.assertTrue(stock_api._company_info_matches(
            {'basic_info': {'SecuCode': '600519.SH'}}, 'sh600519'))
        self.assertFalse(stock_api._company_info_matches(
            {'basic_info': {'SecuCode': 'sz000001'}}, 'sh600519'))
        self.assertFalse(stock_api._company_info_matches({}, 'sh600519'))
        self.assertFalse(stock_api._company_info_matches({'basic_info': 'x'}, 'sh600519'))

    def test_handler_degrades_to_null_plus_errors(self):
        config.cdp_engine = None
        out = stock_api.handle_cls_f10(['sh600519'])
        self.assertIsNone(out['sh600519'])
        self.assertEqual(out['_errors']['sh600519'], 'cdp_unavailable')
        self.assertNotIn('error', out)


# ── stock_api: prefetch loops ──────────────────────────────────────────────

class PrefetchLoopTests(unittest.TestCase):
    def setUp(self):
        _reset_stock_state()

    def tearDown(self):
        _reset_stock_state()

    def test_interval_comes_from_policy(self):
        captured = []

        def _sleep(secs):
            captured.append(secs)
            raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep), \
             patch.object(stock_api, '_prefetch_rotate', return_value=[]):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow',
                                         lambda code, deadline=None: None,
                                         {}, OrderedDict(), {}, threading.Lock())
        self.assertEqual(captured[0], config.cache_policy('fundflow')['pool_refresh'])

    def test_per_call_budget_propagates(self):
        """T2: drive the REAL rotation/advance (no `_prefetch_rotate` patch).

        Patching the rotation away bypassed the production counting semantics
        (`_prefetch_advance(name, visited, len(codes))`), so a broken cursor
        could stay invisible.  A real one-code pool exercises both.
        """
        seen = []
        cycles = {'n': 0}
        pool = {'sh600519': time.time()}

        def _fetch(code, deadline=None):
            seen.append(deadline)
            return {'code': code}

        def _sleep(_secs):
            cycles['n'] += 1
            if cycles['n'] > 1:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('f10', 'f10', _fetch, pool, OrderedDict(),
                                         {}, threading.Lock(), per_call_budget=4)
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0])
        self.assertLessEqual(seen[0], time.time() + 4 + 1)

    def test_no_data_codes_still_advance_the_cursor(self):
        """S1-2 / T-①: 'visited' — not 'processed' — advances round-robin.

        A pool whose fetches succeed but return no data (``None``: not a
        failure, so never counted) used to leave the cursor frozen, so the head
        was re-fetched every pass and the tail was never reached.  With a pass
        deadline that expires after the 3rd code, every one of the 10 codes must
        still be visited within a bounded number of passes.
        """
        codes = [f'sh{600000 + i}' for i in range(10)]
        pool = {c: time.time() for c in codes}
        seen = []
        cycles = {'n': 0}
        clock = {'t': 1_000_000.0}

        def _fetch(code, deadline=None):
            seen.append(code)
            clock['t'] += 1.0                     # each call burns 1s of budget
            return None                           # success-but-empty

        def _sleep(_secs):
            cycles['n'] += 1
            clock['t'] += 100.0                   # fresh window per pass
            if cycles['n'] > 5:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep), \
             patch.object(stock_api, 'time', new=lambda: clock['t']), \
             patch.object(stock_api, '_PREFETCH_PASS_BUDGET', 3.0):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, pool,
                                         OrderedDict(), {}, threading.Lock())
        self.assertEqual(set(seen), set(codes))   # whole pool reached, no starvation

    def test_empty_pool_issues_zero_upstream_calls(self):
        """Hard property: an empty domain pool ⇒ zero upstream calls, cycle after cycle.

        Runs the REAL ``_prefetch_rotate`` (no patch) so the guard under test is
        the production one (`if not codes: continue`).  The r4 report's P6C-05
        lesson applies: a test that patches away the production path can stay
        green while the real scheduler is broken.
        """
        calls = []
        cycles = {'n': 0}

        def _fetch(code, deadline=None):
            calls.append(code)
            return {'code': code}

        def _sleep(_secs):
            cycles['n'] += 1
            if cycles['n'] > 3:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, {},
                                         OrderedDict(), {}, threading.Lock())
        self.assertEqual(cycles['n'], 4)          # the loop really cycled >= 3 times
        self.assertEqual(calls, [])               # and never touched the upstream

    def test_pool_is_the_only_code_source_and_emptying_it_stops_the_calls(self):
        """The prefetch code set is the *domain pool*, not the SSE subscription set.

        A pooled code is refreshed once per pass; once the pool is empty every
        later pass is a no-op (zero upstream calls, sleeping between passes —
        no busy spin).
        """
        calls = []
        pool = {'sh600519': time.time()}
        lock = threading.Lock()
        cycles = {'n': 0}

        def _fetch(code, deadline=None):
            calls.append(code)
            return {'code': code}

        def _sleep(_secs):
            cycles['n'] += 1
            if cycles['n'] == 2:
                with lock:
                    pool.clear()                  # demand gone, pool drained
            if cycles['n'] > 3:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, pool,
                                         OrderedDict(), {}, lock)
        self.assertEqual(calls, ['sh600519'])     # pass 1 only; passes 2-3: zero

    def test_cooldown_code_is_skipped_without_upstream_call(self):
        """BR-SA-11 / SA-T8: prefetch honours the shared ledger's cooldown gate.

        A pooled code already in cooldown is ``skipped`` — no network, same rule
        the batch path applies (`_process_chunk` step ④).
        """
        calls = []
        pool = {'sh600519': time.time()}
        now = time.time()
        with stock_api._fail_ledger_lock:
            stock_api._fail_ledger[('fundflow', 'sh600519')] = [
                3, now + 60, 'upstream_error', now]
        cycles = {'n': 0}

        def _fetch(code, deadline=None):
            calls.append(code)
            return {'code': code}

        def _sleep(_secs):
            cycles['n'] += 1
            if cycles['n'] > 2:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, pool,
                                         OrderedDict(), {}, threading.Lock())
        self.assertEqual(cycles['n'], 3)          # >= 2 passes
        self.assertEqual(calls, [])               # zero upstream calls in cooldown

    def test_repeated_failure_cools_after_three_and_never_retries_each_pass(self):
        """BR-SA-6 / AC-S6: prefetch failures are recorded in the shared ledger.

        The 3rd consecutive failure opens the 120s cooldown, so every later pass
        skips the code: retries are bounded by the cooldown, never one per pass
        (no self-amplification).
        """
        calls = []
        pool = {'sh600519': time.time()}
        cycles = {'n': 0}

        def _fetch(code, deadline=None):
            calls.append(code)
            raise FetchError('upstream_error')

        def _sleep(_secs):
            cycles['n'] += 1
            if cycles['n'] > 4:
                raise _StopLoop()

        with patch.object(stock_api, 'sleep', side_effect=_sleep):
            with self.assertRaises(_StopLoop):
                stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, pool,
                                         OrderedDict(), {}, threading.Lock())
        self.assertEqual(len(calls), 3)           # exactly 3 attempts, then cooled
        entry = stock_api._fail_ledger_get('fundflow', 'sh600519')
        self.assertIsNotNone(entry)
        self.assertGreater(entry[1], time.time())  # 120s cooldown is open


# ── market_api ─────────────────────────────────────────────────────────────

class MarketApiTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_margin_ttl_comes_from_policy(self):
        captured = {}

        def _fake(url, headers=None, ttl=None, encoding='utf-8', deadline=None):
            captured['ttl'] = ttl
            return '{"status_code": 0, "data": {"date": [], "item": []}}'

        with patch.object(market_api, 'fetch_json', side_effect=_fake):
            market_api.fetch_margin('99')
        self.assertEqual(captured['ttl'], config.cache_policy('margin')['ttl'])

    def test_margin_deadline_reaches_fetch_json(self):
        """S1-5: `fetch_margin` must thread its deadline into `fetch_json`
        (a keyword, so a fixed 10s urlopen can't outlive the budget)."""
        captured = {}

        def _fake(url, headers=None, ttl=None, encoding='utf-8', deadline=None):
            captured['deadline'] = deadline
            return '{"status_code": 0, "data": {"date": [], "item": []}}'

        deadline = time.time() + 0.5
        with patch.object(market_api, 'fetch_json', side_effect=_fake):
            market_api.fetch_margin('99', deadline=deadline)
        self.assertEqual(captured['deadline'], deadline)

    def test_no_data_is_not_failure(self):
        with patch.object(market_api, 'fetch_json',
                          return_value='{"status_code": 0, "data": {"date": [], "item": []}}'):
            out = market_api.fetch_margin('99')
        self.assertEqual(out, {'latest': None, 'recent': []})

    def test_market_whitelist_blocks_url_injection(self):
        # P1-1: same-host path/query injection must never reach the URL, and a
        # bogus value must not mint a cache key / burn an outbound request.
        with patch.object(market_api, 'fetch_json') as mocked:
            out = market_api.handle_margin('1?foo=bar')
        mocked.assert_not_called()
        self.assertEqual(out['_error'], 'upstream_error')

        with patch.object(market_api, 'fetch_json') as mocked:
            market_api.handle_margin('../../other/path')
        mocked.assert_not_called()

    def test_valid_markets_build_contract_url(self):
        for market in market_api.VALID_MARKETS:
            with patch.object(
                    market_api, 'fetch_json',
                    return_value='{"status_code": 0, "data": {"date": [], "item": []}}'
            ) as mocked:
                market_api.fetch_margin(market)
            self.assertEqual(mocked.call_args[0][0],
                             f'{config._MARGIN_URL}/{market}/')

    def test_semantic_failure_raises_and_counts(self):
        with patch.object(market_api, 'fetch_json',
                          return_value='{"status_code": 1, "status_msg": "boom"}'):
            with self.assertRaises(FetchError) as cm:
                market_api.fetch_margin('99')
        self.assertEqual(cm.exception.kind, 'upstream_error')
        self.assertEqual(metrics.snapshot()['upstream_fail_total']['upstream_error'], 1)

    def test_deadline_entry_does_not_touch_network(self):
        with patch.object(market_api, 'fetch_json',
                          side_effect=AssertionError('network used')):
            with self.assertRaises(FetchError) as cm:
                market_api.fetch_margin('99', deadline=time.time() - 1)
        self.assertEqual(cm.exception.kind, 'upstream_timeout')

    def test_zb_sentinel_never_leaks_into_a_numeric_field(self):
        """P2-7: `zb` is normalised like every other numeric field.

        It used to bypass `to_100m` and return the raw `'--'` sentinel (a str)
        while the degraded body returns int 0 — an unstable contract the frontend
        then does arithmetic on.
        """
        raw = {'date': ['d1'], 'item': [{'zb': '--', 'rzye': 100000000}]}
        out = market_api._transform_margin(raw)
        self.assertEqual(out['latest']['zb'], 0.0)
        self.assertIsInstance(out['latest']['zb'], float)

    def test_one_dirty_field_degrades_only_itself(self):
        """P2-8: per-field tolerance — a junk cell must not void the response."""
        raw = {'date': ['d1'], 'item': [
            {'rzye': 'not-a-number', 'rqye': 200000000, 'zb': 'x'}]}
        out = market_api._transform_margin(raw)
        self.assertEqual(out['latest']['rzye'], 0.0)
        self.assertAlmostEqual(out['latest']['rqye'], 2.0, places=3)
        self.assertEqual(out['latest']['zb'], 0.0)

    def test_non_dict_item_row_degrades_only_that_row(self):
        raw = {'date': ['d1', 'd2'], 'item': [{'rzye': 100000000}, 'junk']}
        out = market_api._transform_margin(raw)
        self.assertEqual(out['latest']['date'], 'd2')
        self.assertEqual(out['latest']['rzye'], 0.0)
        self.assertAlmostEqual(out['recent'][0]['rzye'], 1.0, places=3)

    def test_network_failure_is_not_double_counted(self):
        with patch.object(market_api, 'fetch_json',
                          side_effect=FetchError('upstream_timeout')):
            out = market_api.handle_margin('99')
        self.assertEqual(out['_error'], 'upstream_timeout')
        self.assertNotIn('upstream_timeout',
                         metrics.snapshot().get('upstream_fail_total', {}))
        self.assertGreaterEqual(metrics.snapshot()['upstream_fetch_total']['margin'], 1)

    def test_handler_never_raises(self):
        with patch.object(market_api, 'fetch_margin', side_effect=RuntimeError('x')):
            out = market_api.handle_margin('99')
        self.assertEqual(out['_error'], 'upstream_error')

    def test_error_field_is_enum_closed(self):
        out = market_api._degraded('bogus kind')
        self.assertEqual(out['_error'], 'upstream_error')
        self.assertEqual(set(out), {'latest', 'recent', '_error'})


# ── cdp_engine ─────────────────────────────────────────────────────────────

class PageDataTests(unittest.TestCase):
    def test_boundary_matrix(self):
        class _Raises:
            def get_data(self):
                raise RuntimeError('boom')

        class _NoneValue:
            def get_data(self):
                return None

        class _ListValue:
            def get_data(self):
                return []

        class _EmptyDict:
            def get_data(self):
                return {}

        class _Data:
            def get_data(self):
                return {'a': 1}

        self.assertIsNone(cdp_engine.page_data(None))
        self.assertIsNone(cdp_engine.page_data(_Raises()))
        self.assertIsNone(cdp_engine.page_data(_NoneValue()))
        self.assertIsNone(cdp_engine.page_data(_ListValue()))
        self.assertIsNone(cdp_engine.page_data(_EmptyDict()))
        self.assertEqual(cdp_engine.page_data(_Data()), {'a': 1})


class RestartWindowTests(unittest.TestCase):
    def setUp(self):
        self._saved_window = dict(cdp_engine._restart_window)
        self._saved_engine = config.cdp_engine
        self._saved_last_restart = cdp_engine._last_chrome_restart

    def tearDown(self):
        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window.update(self._saved_window)
        cdp_engine._publish_window()          # keep the gauge in sync with the restored window
        config.cdp_engine = self._saved_engine
        cdp_engine._last_chrome_restart = self._saved_last_restart

    def _enter_idle_window(self):
        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window.update(
                {'state': 'idle', 'window_start': None, 'window_end': None})
        cdp_engine._last_chrome_restart = 0   # outside the restart throttle

    def assert_window_is_terminal(self, expected):
        """P1-2: the window must always leave 'restarting' (never a permanent
        'restarting' state, which pins the watchdog skip reason forever)."""
        snap = cdp_engine.restart_window_snapshot()
        self.assertEqual(snap['state'], expected)
        self.assertNotEqual(snap['state'], 'restarting')
        self.assertIsNotNone(snap['window_end'])

    def test_initial_idle_window_is_published_at_import(self):
        self.assertIn('cdp_restart_window', _INITIAL_SNAPSHOT_KEYS)

    def test_transitions_and_idempotence(self):
        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window.update(
                {'state': 'idle', 'window_start': None, 'window_end': None})
        cdp_engine._mark_restarting()
        snap = cdp_engine.restart_window_snapshot()
        self.assertEqual(snap['state'], 'restarting')
        self.assertIsNone(snap['window_end'])
        start = snap['window_start']
        cdp_engine._mark_restarting()                         # idempotent
        self.assertEqual(cdp_engine.restart_window_snapshot()['window_start'], start)
        cdp_engine._mark_idle()
        snap = cdp_engine.restart_window_snapshot()
        self.assertEqual(snap['state'], 'idle')
        self.assertIsNotNone(snap['window_end'])
        self.assertEqual(metrics.snapshot()['cdp_restart_window']['state'], 'idle')

    def test_watchdog_skip_reasons(self):
        class _Eng:
            ready = True

        config.cdp_engine = None
        self.assertEqual(cdp_engine.watchdog_restart_skip_reason(), 'not_ready')

        config.cdp_engine = _Eng()
        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window['state'] = 'restarting'
        self.assertEqual(cdp_engine.watchdog_restart_skip_reason(), 'already_restarting')

        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window['state'] = 'idle'
        with patch.object(config, '_is_trading_hours', return_value=True):
            self.assertEqual(cdp_engine.watchdog_restart_skip_reason(), 'trading_hours')

        with patch.object(config, '_is_trading_hours', return_value=False):
            cdp_engine._last_chrome_restart = time.time()
            self.assertEqual(cdp_engine.watchdog_restart_skip_reason(), 'recent_restart')
            cdp_engine._last_chrome_restart = time.time() - 10 ** 6
            self.assertIsNone(cdp_engine.watchdog_restart_skip_reason())

    def test_throttled_ensure_chrome_keeps_state(self):
        with cdp_engine._restart_window_lock:
            cdp_engine._restart_window.update(
                {'state': 'idle', 'window_start': None, 'window_end': None})
        cdp_engine._last_chrome_restart = time.time()          # inside throttle
        with patch.object(cdp_engine.urllib.request, 'urlopen',
                          side_effect=OSError('down')):
            ok = cdp_engine.ensure_chrome()
        self.assertFalse(ok)
        self.assertEqual(cdp_engine.restart_window_snapshot()['state'], 'idle')

    def test_ensure_chrome_probe_exception_ends_unavailable(self):
        """P1-2: `which` raising (fork ENOMEM) must not escape the restart
        flow — the window closes as 'unavailable'."""
        self._enter_idle_window()
        with patch.object(cdp_engine, '_kill_chrome_on_port'), \
             patch.object(cdp_engine.urllib.request, 'urlopen',
                          side_effect=OSError('down')), \
             patch.object(cdp_engine.subprocess, 'run',
                          side_effect=OSError('fork: ENOMEM')):
            self.assertFalse(cdp_engine.ensure_chrome())      # must not raise
        self.assert_window_is_terminal('unavailable')

    def test_ensure_chrome_launch_exception_ends_unavailable(self):
        """P1-2: `Popen` raising (fork ENOMEM) must not escape either."""
        self._enter_idle_window()
        with patch.object(cdp_engine, '_kill_chrome_on_port'), \
             patch.object(cdp_engine.urllib.request, 'urlopen',
                          side_effect=OSError('down')), \
             patch.object(cdp_engine.subprocess, 'run',
                          return_value=Mock(returncode=0)), \
             patch.object(cdp_engine.subprocess, 'Popen',
                          side_effect=OSError('fork: ENOMEM')):
            self.assertFalse(cdp_engine.ensure_chrome())      # must not raise
        self.assert_window_is_terminal('unavailable')

    def test_full_restart_exception_closes_the_window(self):
        """P1-2: any exception inside the restart critical section must still
        leave a terminal state and must not reach the caller."""
        self._enter_idle_window()
        with patch.object(cdp_engine, '_kill_chrome_on_port'), \
             patch.object(cdp_engine.urllib.request, 'urlopen',
                          side_effect=OSError('down')), \
             patch.object(cdp_engine, 'ensure_chrome',
                          side_effect=RuntimeError('boom')):
            self.assertFalse(cdp_engine.full_chrome_restart())
        self.assert_window_is_terminal('unavailable')

        # Regression (P1-2): the watchdog is no longer pinned at
        # 'already_restarting' — the next cycle reaches the throttle branch.
        class _Eng:
            ready = True

        config.cdp_engine = _Eng()
        cdp_engine._last_chrome_restart = 0
        with patch.object(config, '_is_trading_hours', return_value=False):
            self.assertIsNone(cdp_engine.watchdog_restart_skip_reason())

    def test_full_restart_pre_launch_exception_closes_the_window(self):
        """P1-2: the window is already open ('restarting') when the kill/gc
        steps run — an exception there must still end in a terminal state."""
        self._enter_idle_window()
        with patch.object(cdp_engine, '_kill_chrome_on_port',
                          side_effect=OSError('kill failed')), \
             patch.object(cdp_engine.urllib.request, 'urlopen',
                          side_effect=OSError('down')):
            self.assertFalse(cdp_engine.full_chrome_restart())
        self.assert_window_is_terminal('unavailable')

    def test_heartbeat_interval_follows_config(self):
        page = cdp_engine.CDPPage.__new__(cdp_engine.CDPPage)
        with patch.object(config, '_is_trading_hours', return_value=True):
            self.assertEqual(page._heartbeat_interval(), 10)
        with patch.object(config, '_is_trading_hours', return_value=False):
            self.assertEqual(page._heartbeat_interval(), 60)


class LastDataEvictionTests(unittest.TestCase):
    """P2-⑤: the `_last_data` hard cap must keep its side tables in sync."""

    def _page(self):
        page = cdp_engine.CDPPage.__new__(cdp_engine.CDPPage)
        page.cache = {}
        page._last_data = {}
        page._last_data_ts = {}
        page._key_last_seen = {}
        page._api_urls = {}
        page._lock = threading.Lock()
        return page

    def test_eviction_cleans_the_side_tables(self):
        page = self._page()
        cap = cdp_engine.CDPPage._LAST_DATA_MAX_KEYS
        now = time.time()
        for i in range(cap + 1):                     # k0 is the stalest
            page._last_data[f'k{i}'] = {'i': i}
            page._last_data_ts[f'k{i}'] = now - (cap + 1 - i)
            page._key_last_seen[f'k{i}'] = now - (cap + 1 - i)
        with page._lock:
            page._evict_stalest_last_data_locked()
        self.assertEqual(len(page._last_data), cap)
        self.assertEqual(set(page._last_data_ts), set(page._last_data))
        self.assertEqual(set(page._key_last_seen), set(page._last_data))
        self.assertNotIn('k0', page._last_data)

    def test_key_last_seen_survives_while_key_is_still_in_cache(self):
        """`_key_last_seen` is the freshness clock for `self.cache`'s TTL sweep;
        dropping it for a key still in the live cache would leak that cache
        entry forever."""
        page = self._page()
        now = time.time()
        page._last_data['basic_info'] = {'a': 1}
        page._last_data_ts['basic_info'] = now
        page._key_last_seen['basic_info'] = now
        page.cache['basic_info'] = {'a': 1}          # still live in the cache
        page._last_data['other'] = {'b': 2}
        page._last_data_ts['other'] = now - 10       # stalest
        page._key_last_seen['other'] = now - 10
        page._api_urls['other'] = 'http://x/other'
        with page._lock:
            page._evict_stalest_last_data_locked()
        self.assertNotIn('other', page._last_data)
        self.assertNotIn('other', page._last_data_ts)
        self.assertNotIn('other', page._key_last_seen)
        self.assertNotIn('other', page._api_urls)
        self.assertIn('basic_info', page._key_last_seen)

    def test_hard_cap_holds_when_multiple_over(self):
        page = self._page()
        cap = cdp_engine.CDPPage._LAST_DATA_MAX_KEYS
        now = time.time()
        for i in range(cap + 10):
            page._last_data[f'k{i}'] = {'i': i}
            page._last_data_ts[f'k{i}'] = now - (cap + 10 - i)
            page._key_last_seen[f'k{i}'] = now - (cap + 10 - i)
        with page._lock:
            while len(page._last_data) > cap:
                page._evict_stalest_last_data_locked()
        self.assertEqual(len(page._last_data), cap)
        self.assertEqual(set(page._last_data_ts), set(page._last_data))
        self.assertEqual(set(page._key_last_seen), set(page._last_data))


if __name__ == '__main__':
    unittest.main()
