"""Unit tests for metrics.py (metrics.md §8 MET-T1..MET-T13)."""

import json
import threading
import unittest
from unittest import mock

from china_finance_rss import metrics

# Every metric name the production code publishes (metrics.md §3.2 registry).
PUBLISHED_NAMES = {
    'http_503_total', 'stream_frame_dropped_total', 'stream_queue_bytes',
    'stream_frame_distinct', 'stream_frame_peak_bytes',
    'stream_tick_duration_ms', 'stream_tick_slip_total',
    'stream_refresh_lag_ticks', 'stream_tick_degraded_total',
    'stream_slow_client_total', 'cache_entries', 'cache_hit_ratio',
    'negative_cache_size', 'upstream_fail_total', 'upstream_fetch_total',
    'code_cooldown_list', 'cdp_restart_window', 'healthz_stale_total',
    'healthz_inflight',
}


class MetricsTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_counter_accumulates(self):                       # MET-T1
        metrics.incr('http_503_total')
        metrics.incr('http_503_total')
        metrics.incr('http_503_total')
        metrics.incr('stream_tick_slip_total', 5)
        snap = metrics.snapshot()
        self.assertEqual(snap['http_503_total'], 3)
        self.assertEqual(snap['stream_tick_slip_total'], 5)

    def test_labelled_counter(self):                          # MET-T2
        metrics.incr('upstream_fail_total', key='upstream_timeout')
        metrics.incr('upstream_fail_total', key='upstream_timeout')
        metrics.incr('upstream_fail_total', key='upstream_error')
        self.assertEqual(
            metrics.snapshot()['upstream_fail_total'],
            {'upstream_timeout': 2, 'upstream_error': 1})

    def test_gauge_label_merge(self):                         # MET-T3
        metrics.set_gauge('cache_entries', 5, key='url')
        metrics.set_gauge('cache_entries', 2, key='feed')
        self.assertEqual(metrics.snapshot()['cache_entries'],
                         {'url': 5, 'feed': 2})

    def test_gauge_scalar_overwrite(self):
        metrics.set_gauge('stream_queue_bytes', 100)
        metrics.set_gauge('stream_queue_bytes', 200)
        self.assertEqual(metrics.snapshot()['stream_queue_bytes'], 200)

    def test_snapshot_is_deep_copy(self):                     # MET-T4
        metrics.set_gauge('cache_entries', 5, key='url')
        snap = metrics.snapshot()
        snap['cache_entries']['url'] = 999
        self.assertEqual(metrics.snapshot()['cache_entries']['url'], 5)

    def test_snapshot_json_serializable(self):                # MET-T5
        metrics.set_gauge('code_cooldown_list', (('quote', 'sh600519', 1.0),))
        metrics.set_gauge('cdp_restart_window',
                          {'state': 'idle', 'window_start': None,
                           'window_end': None})
        dumped = json.dumps(metrics.snapshot())
        self.assertIn('code_cooldown_list', dumped)
        # tuple/set normalise to list
        self.assertEqual(metrics.snapshot()['code_cooldown_list'],
                         [['quote', 'sh600519', 1.0]])

    def test_concurrent_counter_exact(self):                  # MET-T6
        def work():
            for _ in range(1000):
                metrics.incr('stream_tick_slip_total')

        threads = [threading.Thread(target=work) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(metrics.snapshot()['stream_tick_slip_total'], 100000)

    def test_label_usage_mismatch_failsafe(self):             # MET-T7
        metrics.incr('http_503_total')             # unlabeled first
        metrics.incr('http_503_total', key='k')    # mismatch → ignored
        self.assertEqual(metrics.snapshot()['http_503_total'], 1)

    def test_unregistered_name_warns_but_writes(self):        # MET-T8a
        metrics.incr('typo_metric')
        self.assertEqual(metrics.snapshot()['typo_metric'], 1)
        self.assertTrue(any('unregistered metric name' in m
                            for m in metrics._warned))

    def test_published_names_are_registered(self):            # MET-T8b
        self.assertTrue(PUBLISHED_NAMES <= metrics._KNOWN)

    def test_non_int_increment_ignored(self):                 # MET-T9
        metrics.incr('http_503_total', 'x')
        metrics.incr('http_503_total', True)
        metrics.incr('http_503_total', 2)
        self.assertEqual(metrics.snapshot()['http_503_total'], 2)

    def test_reset_empties_registry(self):                    # MET-T11
        metrics.incr('http_503_total')
        metrics.set_gauge('stream_queue_bytes', 1)
        metrics.reset()
        snap = metrics.snapshot()
        # Written state is cleared ...
        self.assertEqual(snap['http_503_total'], 0)
        self.assertEqual(snap['stream_queue_bytes'], 0)
        # ... but every registered name is still published (P6C-04).
        self.assertEqual(set(snap), metrics._KNOWN)

    def test_cache_hit_ratio_name_unique(self):               # MET-T12
        metrics.set_gauge('cache_hit_ratio', 0.5)
        snap = metrics.snapshot()
        self.assertEqual(snap['cache_hit_ratio'], 0.5)
        self.assertNotIn('cache_hit_total', snap)
        self.assertNotIn('cache_miss_total', snap)

    def test_non_str_name_ignored(self):
        metrics.incr(123)
        metrics.set_gauge(None, 1)
        # Invalid names never enter the registry; the snapshot stays exactly
        # the frozen set of registered names.
        self.assertEqual(set(metrics.snapshot()), metrics._KNOWN)

    def test_registered_metrics_published_at_zero(self):      # MET-T13
        # BUG-P6C-04: a registered metric must appear even with no events, so
        # monitoring can distinguish "not happened" from "not instrumented".
        snap = metrics.snapshot()
        self.assertEqual(set(snap), metrics._KNOWN)
        for name in PUBLISHED_NAMES:
            self.assertIn(name, snap)
        self.assertEqual(snap['stream_frame_dropped_total'], 0)
        self.assertEqual(snap['negative_cache_size'], 0)
        self.assertEqual(snap['http_503_total'], 0)
        self.assertEqual(snap['upstream_fail_total'], {})
        # Snapshot must stay JSON-serialisable with zero-value fallbacks.
        json.dumps(snap)

    def test_never_raises_on_bad_input(self):
        # Total-function contract: observation must never break business code.
        for bad in (None, 1, 'http_503_total'):
            metrics.incr(bad)
            metrics.set_gauge(bad, object())
        metrics.snapshot()

    def test_gauge_shape_guards(self):                        # P2-13
        """`set_gauge` mirrors `incr`'s labelled/unlabelled shape guards."""
        metrics.set_gauge('cache_entries', 5, key='url')
        metrics.set_gauge('cache_entries', 5)                 # scalar over labeled map
        self.assertEqual(metrics.snapshot()['cache_entries'], {'url': 5})
        # A dict-valued *unlabelled* gauge (cdp_restart_window) is still legal.
        metrics.set_gauge('cdp_restart_window', {'state': 'idle'})
        metrics.set_gauge('cdp_restart_window', {'state': 'unavailable'})
        self.assertEqual(metrics.snapshot()['cdp_restart_window']['state'],
                         'unavailable')
        # A labeled write to an unlabelled gauge is refused.
        metrics.set_gauge('stream_queue_bytes', 9, key='x')
        metrics.set_gauge('stream_queue_bytes', 7)
        self.assertEqual(metrics.snapshot()['stream_queue_bytes'], 7)


class SnapshotLockTests(unittest.TestCase):
    def setUp(self):
        metrics.reset()

    def tearDown(self):
        metrics.reset()

    def test_list_values_are_copied_while_the_lock_is_held(self):   # P2-12
        """The out-of-lock clone must never iterate the registry's live list."""
        metrics.set_gauge('code_cooldown_list', [['quote', 'sh600519', 1.0]])
        registry = metrics._gauges['code_cooldown_list']
        real_clone = metrics._clone
        same_object = []

        def spy(value):
            if isinstance(value, list):
                same_object.append(value is registry)
            return real_clone(value)

        with mock.patch.object(metrics, '_clone', side_effect=spy):
            snap = metrics.snapshot()
        self.assertEqual(snap['code_cooldown_list'], [['quote', 'sh600519', 1.0]])
        self.assertTrue(same_object)
        self.assertFalse(any(same_object),
                         '_clone must receive the lock-held copy, not the live list')

    def test_deep_clone_runs_outside_lock(self):             # S1-4
        metrics.set_gauge('cache_entries', 1, key='url')
        held = []
        real_clone = metrics._clone

        def spy(value):
            acquired = metrics._lock.acquire(blocking=False)
            held.append(not acquired)          # True ⇒ lock already held
            if acquired:
                metrics._lock.release()
            return real_clone(value)

        with mock.patch.object(metrics, '_clone', side_effect=spy):
            snap = metrics.snapshot()
        self.assertTrue(held)
        self.assertFalse(any(held), '_clone must run outside metrics._lock')
        self.assertEqual(snap['cache_entries'], {'url': 1})

    def test_snapshot_stays_consistent_under_concurrent_writes(self):  # S1-4
        stop = threading.Event()
        metrics.set_gauge('cache_entries', -1, key='url')   # seed before racing

        def writer():
            i = 0
            while not stop.is_set():
                metrics.set_gauge('cache_entries', i, key='url')
                metrics.incr('stream_tick_slip_total')
                i += 1

        t = threading.Thread(target=writer)
        t.start()
        try:
            for _ in range(200):
                snap = metrics.snapshot()
                self.assertIsInstance(snap['cache_entries']['url'], int)
                json.dumps(snap)
        finally:
            stop.set()
            t.join()


if __name__ == '__main__':
    unittest.main()
