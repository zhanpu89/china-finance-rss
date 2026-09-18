"""HTTP/SSE layer unit tests (code group C).

Exercises server.py's routing/shape table, `_guard` degradation matrix, the
plate stagger derivation, the ≤3-concurrency fan-out, longhu's unified GBK
fetch, feed double-check, `_cache_age` policy mapping, the healthz payload and
the stream inflight cap — plus stream.py's immutability of group state.

These tests depend on the shared change-set's base/data layers (config
`cache_policy`/`DOMAIN_MATRIX`/`MAX_*`, cache `feed_cache_get/put`/
`build_batch_response`, metrics, cdp_engine `page_data`/`restart_window_snapshot`,
stock_api `cached_batch`/`_prefetch_slice`/`BATCH_MAX_WORKERS`). Until those
land, importing `china_finance_rss.server` raises ImportError.
"""

import gzip
import http.client
import json
import re
import threading
import time
import unittest
from collections import OrderedDict
from email.utils import formatdate, parsedate_to_datetime
from unittest.mock import patch
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from china_finance_rss import cache as cache_mod
from china_finance_rss import config
from china_finance_rss import server as srv
from china_finance_rss import utils as utils_mod
from china_finance_rss import stock_api
from china_finance_rss import stream
from china_finance_rss.cache import FetchError, build_batch_response
from china_finance_rss.config import cache_policy
from china_finance_rss.server import (
    BoundedThreadPoolServer,
    RSSHandler,
    build_health_payload,
    _base_feed_entries,
)


class ShapeTableTests(unittest.TestCase):
    def test_json_shapes_complete_and_consistent(self):
        self.assertEqual(srv._SHAPES, frozenset({'batch', 'object', 'rss', 'text'}))
        self.assertEqual(len(srv._JSON_SHAPES), 14)
        self.assertEqual(
            {p for p, s in srv._JSON_SHAPES.items() if s == 'batch'},
            set(srv._STOCK_BATCH_HANDLERS))

    def test_healthz_not_in_json_shapes(self):
        self.assertNotIn('/healthz', srv._JSON_SHAPES)

    def test_every_shape_path_has_a_routed_branch(self):
        """P2: the shape registry is consumed by the router — a new entry without
        a branch (or vice versa) is caught here, not by a silent 404."""
        self.assertEqual(srv._JSON_DISPATCHED_PATHS, frozenset(srv._JSON_SHAPES))


class GuardTests(unittest.TestCase):
    @staticmethod
    def _boom():
        raise RuntimeError('boom')

    def test_object_and_text_degrade(self):
        for shape in ('object', 'text'):
            self.assertEqual(srv._guard(self._boom, shape=shape),
                             {'error': 'boom'})

    def test_batch_degrade_all_null_plus_errors(self):
        out = srv._guard(self._boom, shape='batch',
                         requested=['sh600519', 'sz000001'])
        self.assertIsNone(out['sh600519'])
        self.assertIsNone(out['sz000001'])
        self.assertEqual(out['_errors'],
                         {'sh600519': 'upstream_error',
                          'sz000001': 'upstream_error'})

    def test_rss_degrade_is_valid_feed(self):
        xml, last_modified = srv._guard(
            self._boom, shape='rss',
            rss_info={'title': 'T', 'link': 'L', 'description': 'D'},
            feed_url='http://x/f')
        root = ET.fromstring(xml)
        self.assertIsNotNone(root.find('./channel/item'))
        self.assertIsNone(last_modified)     # degrade ⇒ IMS not evaluable

    def test_invalid_shape_raises(self):
        with self.assertRaises(ValueError):
            srv._guard(lambda: 1, shape='nope')

    def test_keyboard_interrupt_passes_through(self):
        def kbi():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            srv._guard(kbi, shape='object')


class PlateStaggerTests(unittest.TestCase):
    """BR-SRV-10..13: three distinct stagger tiers derived from policy."""

    def _capture_ttls(self, call):
        captured = []

        def fake_fetch_json(url, headers=None, ttl=None, encoding=None):
            captured.append(ttl)
            return json.dumps({'code': 200, 'data': {'main_fund_diff': {}}})

        with patch.object(srv, 'fetch_json', side_effect=fake_fetch_json):
            call()
        return captured

    def test_hotplate_three_tiers(self):
        captured = self._capture_ttls(srv.handle_cls_hotplate)
        base, stagger = srv._plate_ttls()
        self.assertEqual(stagger, max(3, base // 4))
        self.assertEqual(sorted(captured),
                         sorted([base, base + stagger, base + stagger * 2]))
        self.assertEqual(len(set(captured)), 3)      # never collapsed to one TTL

    def test_plate_three_tiers(self):
        captured = self._capture_ttls(lambda: srv.handle_cls_plate('cls80484'))
        base, stagger = srv._plate_ttls()
        self.assertEqual(sorted(captured),
                         sorted([base, base + stagger, base + stagger * 2]))
        self.assertEqual(len(set(captured)), 3)

    def test_fanout_uses_three_specs_once(self):
        real = srv._fetch_concurrent
        calls = []

        def spy(specs):
            calls.append(len(specs))
            return real(specs)

        with patch.object(srv, '_fetch_concurrent', side_effect=spy), \
             patch.object(srv, 'fetch_json',
                          side_effect=lambda *a, **k: json.dumps({'data': {}})):
            srv.handle_cls_hotplate()
            srv.handle_cls_plate('cls80484')
        self.assertEqual(calls, [3, 3])


class FanoutLatencyTests(unittest.TestCase):
    """SRV-T35 / AC-E2: 3 specs cost ≈ max, not sum (≤3 real concurrency)."""

    SLEEP = 0.4

    def _slow_fetch(self, payload):
        def slow(url, headers=None, ttl=None, encoding=None):
            time.sleep(self.SLEEP)
            return json.dumps(payload)
        return slow

    def test_hotplate_latency_is_max_not_sum(self):
        with patch.object(srv, 'fetch_json',
                          side_effect=self._slow_fetch({'data': {'main_fund_diff': {}}})):
            start = time.monotonic()
            srv.handle_cls_hotplate()
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2 * self.SLEEP)     # serial ⇒ 3×SLEEP

    def test_plate_latency_is_max_not_sum(self):
        with patch.object(srv, 'fetch_json',
                          side_effect=self._slow_fetch({'code': 200, 'data': {}})):
            start = time.monotonic()
            srv.handle_cls_plate('cls80484')
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2 * self.SLEEP)

    def test_longhu_latency_is_max_not_sum(self):
        with patch.object(srv, 'fetch_json',
                          side_effect=self._slow_fetch('<html></html>')):
            start = time.monotonic()
            srv.handle_ths_longhu()
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2 * self.SLEEP)


class FanoutWaitBoundTests(unittest.TestCase):
    """P1-2: a saturated shared pool must not stretch the request bound."""

    def test_busy_pool_degrades_within_budget(self):
        ex = srv._get_fanout_executor()
        release = threading.Event()
        blockers = [ex.submit(release.wait, 10.0)
                    for _ in range(srv._FANOUT_MAX_WORKERS)]
        try:
            with patch.object(srv, '_FANOUT_WAIT_BUDGET', 0.3):
                start = time.monotonic()
                out = srv._fetch_concurrent([('a', lambda: 'A'),
                                             ('b', lambda: 'B')])
                elapsed = time.monotonic() - start
            self.assertLess(elapsed, 1.5)            # no unbounded queuing
            for key in ('a', 'b'):
                self.assertIsInstance(out[key], FetchError)
                self.assertEqual(out[key].kind, 'upstream_timeout')
        finally:
            release.set()
            for fut in blockers:
                fut.result(timeout=10)

    def test_single_spec_runs_inline_without_pool(self):
        calls = []

        def fn():
            calls.append(threading.current_thread())
            return 'ok'

        self.assertEqual(srv._fetch_concurrent([('only', fn)]), {'only': 'ok'})
        self.assertEqual(calls, [threading.current_thread()])


class HotplateFailureShapeTests(unittest.TestCase):
    def test_all_partitions_fail_adds_top_level_error(self):
        def boom(url, headers=None, ttl=None, encoding=None):
            raise RuntimeError('upstream down')

        with patch.object(srv, 'fetch_json', side_effect=boom):
            res = srv.handle_cls_hotplate()

        for key in ('plate_industry', 'plate_concept', 'plate_area'):
            self.assertIn('error', res[key])
        self.assertIn('error', res)                  # BR-SRV-31

    def test_partial_failure_has_no_top_level_error(self):
        def mixed(url, headers=None, ttl=None, encoding=None):
            if 'type=concept' in url:
                raise RuntimeError('down')
            return json.dumps({'data': {'main_fund_diff': {}}})

        with patch.object(srv, 'fetch_json', side_effect=mixed):
            res = srv.handle_cls_hotplate()

        self.assertIn('error', res['plate_concept'])
        self.assertNotIn('error', res)


class LonghuTests(unittest.TestCase):
    """BR-SRV-9 / R15: both upstreams via fetch_json(encoding='gbk') + L4 TTL."""

    def test_gbk_and_shared_ttl_and_no_urlopen(self):
        captured = []

        def fake_fetch_json(url, headers=None, ttl=None, encoding=None):
            captured.append((url, ttl, encoding))
            return '<html></html>'

        with patch.object(srv, 'fetch_json', side_effect=fake_fetch_json):
            res = srv.handle_ths_longhu()

        self.assertEqual(len(captured), 2)
        self.assertEqual({c[2] for c in captured}, {'gbk'})
        self.assertEqual({c[1] for c in captured},
                         {cache_policy('longhu')['ttl']})
        self.assertEqual(res, {'data': [], 'total': 0})


class LonghuSeatPairingTests(unittest.TestCase):
    """P0: broker seats are paired to stocks positionally (two tables per stock,
    in order).  A matching table that parses 0 entries must still advance the
    pairing index — otherwise every later stock's buy/sell seats shift by one
    and fund data is silently mis-attributed (HTTP 200, no error signal)."""

    TABLE = ('<html><table>'
             '<tr><td>1</td><td>600519</td><td>贵州茅台</td><td>1700</td>'
             '<td>+1%</td><td>10亿</td><td>2亿</td></tr>'
             '<tr><td>2</td><td>000001</td><td>平安银行</td><td>11</td>'
             '<td>-1%</td><td>5亿</td><td>-1亿</td></tr>'
             '</table></html>')

    @staticmethod
    def _row(name):
        return f'<tr><td>{name}</td><td>100</td><td>2</td><td>98</td></tr>'

    @classmethod
    def _table(cls, label, rows):
        return f'<table><th>{label}</th>' + ''.join(rows) + '</table>'

    def _run(self, page):
        def fake(url, headers=None, ttl=None, encoding=None):
            return self.TABLE if url == srv._LHBTABLE_URL else page
        with patch.object(srv, 'fetch_json', side_effect=fake):
            return srv.handle_ths_longhu()

    def test_empty_table_does_not_shift_later_stocks(self):
        page = (
            self._table('买入金额最大的前5名营业部', [self._row('营业部A')]) +
            # P0 trigger: a matching sell table that parses 0 entries (its data
            # rows use <th>), so broker_idx must still advance.
            self._table('卖出金额最大的前5名营业部',
                        ['<tr><th>营业部B</th><th>1</th><th>2</th>'
                         '<th>3</th></tr>']) +
            self._table('买入金额最大的前5名营业部', [self._row('营业部C')]) +
            self._table('卖出金额最大的前5名营业部', [self._row('营业部D')])
        )
        stocks = self._run(page)['data']
        self.assertEqual(len(stocks), 2)
        self.assertEqual(stocks[0]['buy_top5'][0]['name'], '营业部A')
        self.assertNotIn('sell_top5', stocks[0])          # empty table ⇒ no seats
        # ★ the regression: without the unconditional increment this buy table
        # lands on stock 0 (overwriting A) and stock 1 gets no buy seats.
        self.assertEqual(stocks[1]['buy_top5'][0]['name'], '营业部C')
        self.assertEqual(stocks[1]['sell_top5'][0]['name'], '营业部D')

    def test_mismatched_table_count_warns(self):
        page = (self._table('买入金额最大的前5名营业部', [self._row('A')]) +
                self._table('卖出金额最大的前5名营业部', [self._row('B')]) +
                self._table('买入金额最大的前5名营业部', [self._row('C')]))
        with self.assertLogs('server', level='WARNING') as cm:
            self._run(page)
        self.assertTrue(any('misaligned' in m for m in cm.output), cm.output)


class FeedDoubleCheckTests(unittest.TestCase):
    """BR-SRV-6: concurrent misses on the same path cause exactly one fetch."""

    TIME = 1234.0

    def _handler(self):
        return RSSHandler.__new__(RSSHandler)

    @staticmethod
    def _entry(xml):
        # Six fields (BR-CACHE-32/34): last_modified is the Last-Modified source
        # and fingerprint the inheritance key.
        return {'xml': xml, 'time': FeedDoubleCheckTests.TIME,
                'last_modified': FeedDoubleCheckTests.TIME, 'fingerprint': None,
                'last_access': FeedDoubleCheckTests.TIME,
                'expires_at': FeedDoubleCheckTests.TIME + 30}

    @staticmethod
    def _store_put(state):
        def _put(p, xml, ttl, fingerprint=None):
            state['entry'] = FeedDoubleCheckTests._entry(xml)
            return state['entry']            # F5: put returns the written entry
        return _put

    def test_double_check_single_fetch_single_thread(self):
        state = {'entry': None}
        calls = {'n': 0}

        def fetch():
            calls['n'] += 1
            return '<rss/>'

        h = self._handler()
        with patch.object(srv, 'feed_cache_get_entry',
                          side_effect=lambda p: state['entry']), \
             patch.object(srv, 'feed_cache_put',
                          side_effect=self._store_put(state)):
            self.assertEqual(h._get_or_fetch_feed('/cls/telegraph', fetch),
                             ('<rss/>', self.TIME))
            self.assertEqual(h._get_or_fetch_feed('/cls/telegraph', fetch),
                             ('<rss/>', self.TIME))
        self.assertEqual(calls['n'], 1)

    def test_double_check_single_fetch_concurrent(self):
        state = {'entry': None}
        calls = {'n': 0}
        lock = threading.Lock()

        def fetch():
            with lock:
                calls['n'] += 1
            return '<rss/>'

        h = self._handler()
        errors = []

        def worker():
            try:
                h._get_or_fetch_feed('/cls/telegraph', fetch)
            except Exception as exc:      # pragma: no cover
                errors.append(exc)

        with patch.object(srv, 'feed_cache_get_entry',
                          side_effect=lambda p: state['entry']), \
             patch.object(srv, 'feed_cache_put',
                          side_effect=self._store_put(state)):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        self.assertEqual(calls['n'], 1)


class CacheAgeTests(unittest.TestCase):
    """BR-SRV-8: every path resolves through its policy domain."""

    def test_registered_paths_follow_policy(self):
        h = RSSHandler.__new__(RSSHandler)
        for path, domain in srv._CACHE_AGE_DOMAINS.items():
            h.path = path
            self.assertEqual(h._cache_age(), cache_policy(domain)['ttl'], path)

    def test_realtime_panels_use_quote_domain(self):
        """P2: the 4 CDP panels are real-time surfaces, not the 300s default."""
        h = RSSHandler.__new__(RSSHandler)
        for path in ('/finance/market', '/finance/timeline',
                     '/quotation/market', '/market/timeline'):
            h.path = path
            self.assertEqual(h._cache_age(), cache_policy('quote')['ttl'], path)

    def test_rss_paths_use_feed_domain(self):
        """F4 / SRV-T11: the 5 RSS max-age values read the *feed* domain (the
        same authority as the feed cache TTL / <ttl>), not news_url."""
        h = RSSHandler.__new__(RSSHandler)
        for path in srv.ROUTES:
            self.assertEqual(srv._CACHE_AGE_DOMAINS[path], 'feed', path)
            h.path = path
            self.assertEqual(h._cache_age(), cache_policy('feed')['ttl'], path)

    def test_unregistered_path_uses_default_domain(self):
        h = RSSHandler.__new__(RSSHandler)
        for path in ('/healthz', '/', '/opml.xml'):
            h.path = path
            self.assertEqual(h._cache_age(), cache_policy('f10')['ttl'], path)

    def test_query_string_is_stripped(self):
        h = RSSHandler.__new__(RSSHandler)
        h.path = '/stock/data?code=sh600519'
        self.assertEqual(h._cache_age(), cache_policy('quote')['ttl'])

    def test_absolute_form_request_line_resolves_the_path(self):
        """P2: `GET http://host/stock/data?...` must still map to the quote
        domain, not fall through to the 300s default (real-time quotes stamped
        `max-age=300` in a shared cache)."""
        h = RSSHandler.__new__(RSSHandler)
        h.path = 'http://feeds.example.com/stock/data?code=sh600519'
        self.assertEqual(h._cache_age(), cache_policy('quote')['ttl'])


class BaseUrlHardeningTests(unittest.TestCase):
    """S2-3: a request-derived base URL is validated and never published as
    public cacheable content without Vary (cache poisoning / link hijack)."""

    @staticmethod
    def _handler(headers):
        h = RSSHandler.__new__(RSSHandler)
        h.headers = headers
        return h

    def test_public_base_url_always_wins(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', 'https://feeds.example.com'):
            h = self._handler({'Host': 'evil.test'})
            self.assertEqual(h._base_url(), 'https://feeds.example.com')

    def test_forged_host_falls_back_to_localhost(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            for bad in ('evil.test/../x', 'a@b', 'host\r\nX: y', ''):
                h = self._handler({'Host': bad})
                self.assertEqual(h._base_url(),
                                 f'http://localhost:{srv.PORT}', repr(bad))

    def test_valid_host_and_proto_are_used(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            h = self._handler({'Host': 'feeds.example.com',
                               'X-Forwarded-Proto': 'https'})
            self.assertEqual(h._base_url(), 'https://feeds.example.com')

    def test_bad_proto_falls_back_to_http(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            h = self._handler({'Host': 'feeds.example.com',
                               'X-Forwarded-Proto': 'javascript'})
            self.assertEqual(h._base_url(), 'http://feeds.example.com')

    def test_bad_x_forwarded_host_is_ignored(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            h = self._handler({'Host': 'ok.test',
                               'X-Forwarded-Host': 'bad host'})
            self.assertEqual(h._base_url(), f'http://localhost:{srv.PORT}')

    def test_serve_feed_marks_host_derived_url_non_public(self):
        h = RSSHandler.__new__(RSSHandler)
        h.headers = {}
        captured = {}
        h._send_text = lambda *a, **k: captured.update(k)
        with patch.object(srv.RSSHandler, '_get_or_fetch_feed',
                          return_value=('<rss/>', None)), \
             patch.object(srv, 'PUBLIC_BASE_URL', ''):
            h._serve_feed('/cls/telegraph', 'http://feeds.example.com')
        self.assertTrue(captured.get('varies_on_host'))

    def test_serve_feed_is_public_with_configured_base_url(self):
        h = RSSHandler.__new__(RSSHandler)
        h.headers = {}
        captured = {}
        h._send_text = lambda *a, **k: captured.update(k)
        with patch.object(srv.RSSHandler, '_get_or_fetch_feed',
                          return_value=('<rss/>', None)), \
             patch.object(srv, 'PUBLIC_BASE_URL', 'https://feeds.example.com'):
            h._serve_feed('/cls/telegraph', 'https://feeds.example.com')
        self.assertFalse(captured.get('varies_on_host'))


class HealthPayloadTests(unittest.TestCase):
    def test_schema_check0_zero_upstream(self):
        payload = build_health_payload('https://feeds.example.com')
        self.assertEqual(set(payload),
                         {'status', 'cache_ttl', 'request_timeout', 'feeds',
                          'metrics', 'policy', 'cdp'})
        self.assertNotIn('stale', payload)
        self.assertEqual(payload['cache_ttl'], cache_policy('feed')['ttl'])
        self.assertEqual(payload['request_timeout'], config.REQUEST_TIMEOUT)
        self.assertEqual(len(payload['feeds']), 15)
        for entry in payload['feeds']:
            self.assertTrue({'name', 'path', 'url', 'status'} <= set(entry))
            self.assertNotIn('items', entry)      # check=0 never fetches
        self.assertEqual(set(payload['policy']), set(config.DOMAIN_MATRIX))
        self.assertEqual(set(payload['cdp']),
                         {'state', 'window_start', 'window_end'})

    def test_feed_status_corrections(self):
        entries = {e['path']: e['status']
                   for e in _base_feed_entries('http://x')}
        self.assertEqual(len(entries), 15)
        self.assertEqual(entries['/stock/data'], 'configured')
        self.assertEqual(entries['/stock/basic_info'], 'configured')
        self.assertEqual(entries['/stock/f10'], 'requires_chrome_cdp')
        self.assertEqual(entries['/finance/market'], 'requires_chrome_cdp')
        self.assertEqual(entries['/quotation/market'], 'requires_chrome_cdp')
        self.assertEqual(entries['/market/margin'], 'configured')
        self.assertEqual(entries['/cls/telegraph'], 'configured')

    def test_bounded_admission_stale_path(self):
        # occupy every admission slot, then confirm stale fallback is immediate.
        acquired = [srv._health_sem.acquire(blocking=False)
                    for _ in range(config.MAX_HEALTH_INFLIGHT)]
        self.assertTrue(all(acquired))
        try:
            with patch.object(srv, '_run_health_checks') as runner:
                payload = build_health_payload('http://x', check_sources=True)
            runner.assert_not_called()            # no upstream contact
            self.assertTrue(payload.get('stale'))
            snap = srv.metrics.snapshot()
            self.assertGreaterEqual(snap.get('healthz_stale_total', 0), 1)
        finally:
            for _ in range(config.MAX_HEALTH_INFLIGHT):
                srv._health_sem.release()

    def test_check_failure_releases_admission_slot(self):
        """P1-5: an exception in the check path settles the admission slot and
        gauge exactly once — 5 leaks used to pin every later `?check=1` stale."""
        before = srv.metrics.snapshot()['healthz_inflight']
        with patch.object(srv, '_run_health_checks',
                          side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                build_health_payload('http://x', check_sources=True)
        self.assertEqual(srv.metrics.snapshot()['healthz_inflight'], before)
        # every slot is genuinely available again
        acquired = [srv._health_sem.acquire(blocking=False)
                    for _ in range(config.MAX_HEALTH_INFLIGHT)]
        self.assertTrue(all(acquired))
        for _ in range(config.MAX_HEALTH_INFLIGHT):
            srv._health_sem.release()


class HttpSemanticsTests(unittest.TestCase):
    """SRV-T33: HEAD writes no body on the 200/400/404 branches, and the
    `market` enum is enforced at the routing boundary (P1-1)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = BoundedThreadPoolServer(('127.0.0.1', 0), RSSHandler,
                                          max_workers=2)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _req(self, method, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        conn.request(method, path)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        conn.close()
        return status, body

    def test_head_writes_no_body(self):
        for path, expected in (('/', 200),
                               ('/market/margin?market=bogus', 400),
                               ('/nope', 404)):
            status, body = self._req('HEAD', path)
            self.assertEqual(status, expected, path)
            self.assertEqual(body, b'', path)

    def test_invalid_market_is_400_without_reaching_the_handler(self):
        status, body = self._req('GET', '/market/margin?market=1%3Ffoo%3Dbar')
        self.assertEqual(status, 400)
        self.assertIn('Invalid ?market=', json.loads(body)['error'])

    def test_market_enum_passes_through_to_handler(self):
        seen = []
        with patch.object(srv, 'handle_margin',
                          side_effect=lambda m: seen.append(m) or {}):
            self.assertEqual(self._req('GET', '/market/margin?market=3')[0], 200)
            self.assertEqual(self._req('GET', '/market/margin')[0], 200)
        self.assertEqual(seen, ['3', '99'])          # default stays '99'

    def test_healthz_guard_failure_is_503_and_counted(self):
        """S2-5: `_guard` returns {'error': ...} (no 'status') — that must be a
        503, not a healthy 200; the P2 accounting must include it."""
        before = srv.metrics.snapshot()['http_503_total']
        with patch.object(srv, 'build_health_payload',
                          side_effect=RuntimeError('boom')):
            status, body = self._req('GET', '/healthz')
        after = srv.metrics.snapshot()['http_503_total']
        self.assertEqual(status, 503)
        self.assertIn('error', json.loads(body))
        self.assertEqual(after, before + 1)

    def test_healthz_ok_is_200(self):
        status, body = self._req('GET', '/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'ok')

    def test_cdp_unavailable_panel_is_200_with_error_body(self):
        """N1: a wholly unavailable CDP panel degrades with HTTP 200 + an error
        body (the old contract, kept for existing consumers) — not a 503, and
        it must not move the real-503 counter."""
        before = srv.metrics.snapshot()['http_503_total']
        with patch.dict(srv._PANEL_HANDLERS,
                        {'/finance/market':
                         lambda: {'error': 'Chrome CDP not available'}}):
            status, body = self._req('GET', '/finance/market')
        self.assertEqual(status, 200)
        self.assertIn('error', json.loads(body))
        self.assertEqual(srv.metrics.snapshot()['http_503_total'], before)

    def test_panel_with_data_is_200(self):
        with patch.dict(srv._PANEL_HANDLERS,
                        {'/finance/market': lambda: {'basic_info': {'x': 1}}}):
            status, body = self._req('GET', '/finance/market')
        self.assertEqual(status, 200)

    def test_hotplate_all_partitions_failing_is_200_with_error_body(self):
        def boom(url, headers=None, ttl=None, encoding=None):
            raise RuntimeError('upstream down')
        with patch.object(srv, 'fetch_json', side_effect=boom):
            status, body = self._req('GET', '/cls/hotplate')
        self.assertEqual(status, 200)
        self.assertIn('error', json.loads(body))

    def test_margin_degraded_is_200_with_error_body(self):
        with patch.object(srv, 'handle_margin',
                          return_value={'latest': {'rzye': 0}, 'recent': [],
                                        '_error': 'upstream_timeout'}):
            status, body = self._req('GET', '/market/margin')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['_error'], 'upstream_timeout')

    def test_guard_captured_error_body_is_200(self):
        """N1: the fourth degrade face — a data endpoint whose handler *raises*
        — also answers HTTP 200 with the guard's ``{'error': ...}`` body, and
        must not move the real-503 counter."""
        def boom():
            raise RuntimeError('boom')
        before = srv.metrics.snapshot()['http_503_total']
        with patch.dict(srv._PANEL_HANDLERS, {'/finance/market': boom}):
            status, body = self._req('GET', '/finance/market')
        self.assertEqual(status, 200)
        self.assertIn('error', json.loads(body))
        self.assertEqual(srv.metrics.snapshot()['http_503_total'], before)

    def test_opml_is_private_and_varies_on_host(self):
        """S2-3: with no PUBLIC_BASE_URL the OPML embeds a request-derived URL,
        so it must not be public-cacheable without Vary."""
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            conn = http.client.HTTPConnection('127.0.0.1', self.port)
            conn.request('GET', '/opml.xml')
            resp = conn.getresponse()
            resp.read()
            cc = resp.getheader('Cache-Control') or ''
            vary = resp.getheader('Vary') or ''
            conn.close()
        self.assertIn('private', cc)
        self.assertNotIn('public', cc)
        self.assertIn('Host', vary)

    def test_forged_host_never_reaches_the_opml_body(self):
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            conn = http.client.HTTPConnection('127.0.0.1', self.port)
            conn.request('GET', '/opml.xml',
                         headers={'Host': 'evil.test/../x'})
            resp = conn.getresponse()
            body = resp.read().decode('utf-8')
            conn.close()
        self.assertNotIn('evil.test', body)


class BoundedServerTests(unittest.TestCase):
    def test_main_port_default_inflight(self):
        s = BoundedThreadPoolServer(('127.0.0.1', 0), RSSHandler, max_workers=2)
        try:
            self.assertEqual(s._max_inflight, config.MAX_INFLIGHT)
        finally:
            s.server_close()

    def test_stream_port_explicit_inflight(self):
        s = BoundedThreadPoolServer(('127.0.0.1', 0), RSSHandler,
                                    max_workers=2, max_inflight=110)
        try:
            self.assertEqual(s._max_inflight, 110)
        finally:
            s.server_close()

    def test_stream_factory_passes_explicit_inflight(self):
        # P1-4 closed loop: the factory itself must pass 110 (+10 over the
        # 100-conn register), not just a hand-built server instance.
        with patch.object(stream, 'STREAM_PORT', 0):
            s = stream.make_stream_server(max_workers=4)
        try:
            self.assertEqual(s._max_inflight, config.MAX_STREAM_CONNS + 10)
            self.assertEqual(s._max_inflight, 110)
        finally:
            s.server_close()

    def test_listen_backlog_covers_admission_caps(self):      # P6C-03
        # socketserver's default backlog (5) is what caused the SYN-retransmit
        # tail; the accept queue must cover both port admission caps.
        self.assertEqual(BoundedThreadPoolServer.request_queue_size,
                         config.LISTEN_BACKLOG)
        self.assertGreaterEqual(config.LISTEN_BACKLOG, config.MAX_INFLIGHT)
        self.assertGreaterEqual(config.LISTEN_BACKLOG,
                                config.MAX_STREAM_CONNS)

    def test_stream_factory_inherits_listen_backlog(self):    # P6C-03
        # The stream path must not silently fall back to the default of 5.
        with patch.object(stream, 'STREAM_PORT', 0):
            s = stream.make_stream_server(max_workers=4)
        try:
            self.assertEqual(s.request_queue_size, config.LISTEN_BACKLOG)
            self.assertGreaterEqual(s.request_queue_size,
                                    config.MAX_STREAM_CONNS)
        finally:
            s.server_close()


class StockBatchIngressTests(unittest.TestCase):
    """P1-6: `/stock/*` folds `?code=` through `config.canonical_code` on the way
    in, so one stock is one identity for the batch budget and for every
    pool/cache/ledger key downstream — while the response stays keyed by the
    spelling the client actually sent (the existing response contract)."""

    @staticmethod
    def _handler():
        """A bare RSSHandler with the two senders captured instead of written."""
        h = RSSHandler.__new__(RSSHandler)
        sent = {}
        h._send_text = lambda status, ctype, body, **kw: sent.update(
            {'status': status, 'body': json.loads(body)})
        h._send_error = lambda msg, **kw: sent.update(
            {'status': 400, 'body': {'error': msg}})
        return h, sent

    def _dispatch(self, path, query, handler):
        h, sent = self._handler()
        h._handle_stock_batch(urlparse(f'{path}?code={query}'), handler, path=path)
        return sent

    def test_handler_gets_the_canonical_code_response_keeps_the_spelling(self):
        seen = []

        def fake(codes, dropped=0):
            seen.append((list(codes), dropped))
            return build_batch_response(codes, {c: {'name': 'x'} for c in codes},
                                        dropped=dropped)

        sent = self._dispatch('/stock/data', '600519.SH', fake)
        self.assertEqual(seen, [(['sh600519'], 0)])          # canonical ingress
        self.assertEqual(sent['status'], 200)
        self.assertEqual(sent['body'], {'600519.SH': {'name': 'x'}})

    def test_spellings_of_one_stock_are_one_batch_identity(self):
        seen = []

        def fake(codes, dropped=0):
            seen.append(list(codes))
            return build_batch_response(codes, {}, dropped=dropped)

        sent = self._dispatch('/stock/data', 'SH600519,600519.SH,sh600519', fake)
        self.assertEqual(seen, [['sh600519']])               # one upstream identity
        self.assertEqual(list(sent['body']), ['SH600519'])   # first spelling wins

    def test_re_spellings_do_not_consume_the_batch_budget(self):
        """The fold happens *before* the BR-SRV-14 accounting: 50 distinct
        stocks plus a re-spelled duplicate is still 50 slots (no false
        `_truncated` on a legal request)."""
        codes = [f'sh{i:06d}' for i in range(50)]
        seen = []

        def fake(got, dropped=0):
            seen.append((len(got), dropped))
            return build_batch_response(got, {}, dropped=dropped)

        sent = self._dispatch('/stock/data', ','.join(codes + ['SH000001']), fake)
        self.assertEqual(seen, [(50, 0)])
        self.assertNotIn('_truncated', sent['body'])
        self.assertEqual(len(sent['body']), 50)

    def test_truncation_counts_distinct_stocks_and_stays_aligned(self):
        codes = [f'sh{i:06d}' for i in range(55)]
        seen = []

        def fake(got, dropped=0):
            seen.append((len(got), dropped))
            return build_batch_response(got, {}, dropped=dropped)

        sent = self._dispatch('/stock/data', ','.join(codes), fake)
        self.assertEqual(seen, [(50, 5)])
        self.assertTrue(sent['body']['_truncated'])
        self.assertEqual(sent['body']['_dropped_count'], 5)
        self.assertEqual(len(sent['body']), 52)              # 50 rows + 2 keys

    def test_guard_degrade_body_is_keyed_by_the_requested_spelling(self):
        """The handler raised ⇒ `_guard` assembles the all-null body off
        `requested`; the canonical→requested fold must stay a no-op there."""
        def boom(codes, dropped=0):
            raise RuntimeError('boom')

        sent = self._dispatch('/stock/data', '600519.SH', boom)
        self.assertEqual(sent['status'], 200)
        self.assertEqual(sent['body'],
                         {'600519.SH': None,
                          '_errors': {'600519.SH': 'upstream_error'}})

    def test_invalid_code_is_a_per_code_null_not_a_400(self):
        """A bad *value* stays a per-code `null` (SA-T13): 400 is for a missing /
        empty `?code=`, never for the code's spelling."""
        sent = self._dispatch('/stock/data', 'nope',
                              lambda codes, dropped=0: build_batch_response(codes, {}))
        self.assertEqual(sent['status'], 200)
        self.assertEqual(sent['body'], {'nope': None})

    def test_missing_or_empty_code_is_a_400(self):
        sent = self._dispatch('/stock/data', '', lambda codes, dropped=0: {})
        self.assertEqual(sent['status'], 400)
        self.assertIn('Missing ?code=', sent['body']['error'])
        sent = self._dispatch('/stock/data', ',', lambda codes, dropped=0: {})
        self.assertEqual(sent['status'], 400)
        self.assertIn('No valid stock codes provided.', sent['body']['error'])

    def test_dotted_and_prefixed_spellings_share_one_cache_key(self):
        """P1-6 end-to-end: `?code=600519.SH` then `?code=sh600519` ⇒ ONE
        upstream fetch and ONE terminal-cache entry, each response keyed by the
        spelling its own request used."""
        store = ({}, OrderedDict(), {}, threading.Lock())
        saved_store = stock_api._DOMAIN_STORES['quote']
        stock_api._DOMAIN_STORES['quote'] = store
        calls = []

        def fake_fetch(code, deadline=None, ttl=None):
            calls.append(code)
            return {'SecuCode': code, 'name': 'x'}

        try:
            with patch.object(stock_api, 'fetch_cls_basic_info',
                              side_effect=fake_fetch), \
                 patch.object(stock_api, '_fail_ledger_get', return_value=None):
                first = self._dispatch('/stock/basic_info', '600519.SH',
                                       stock_api.handle_cls_basic_infos)
                second = self._dispatch('/stock/basic_info', 'sh600519',
                                        stock_api.handle_cls_basic_infos)
        finally:
            stock_api._DOMAIN_STORES['quote'] = saved_store

        self.assertEqual(calls, ['sh600519'])                # one canonical fetch
        self.assertEqual(list(store[1]), ['sh600519'])       # one cache key
        self.assertEqual(list(first['body']), ['600519.SH'])
        self.assertEqual(list(second['body']), ['sh600519'])
        self.assertEqual(first['body']['600519.SH']['name'], 'x')
        self.assertEqual(first['body']['600519.SH'],
                         second['body']['sh600519'])


class GzipResponseTests(unittest.TestCase):
    """_send_text gzip：Accept-Encoding 协商 + 阈值 + Vary 合并。"""

    def _fake_handler(self, accept_encoding):
        import io
        from unittest.mock import Mock
        from china_finance_rss.server import RSSHandler
        h = RSSHandler.__new__(RSSHandler)   # 绕过 __init__（不起真实 socket）
        h.headers = {'Accept-Encoding': accept_encoding}
        h.send_response = Mock()
        h.send_header = Mock()
        h.end_headers = Mock()
        h.wfile = io.BytesIO()
        h._cache_age = lambda: 60
        return h

    def _captured(self, h):
        ctype = clen = cenc = vary = None
        for args in h.send_header.call_args_list:
            name, val = args[0]
            if name == 'Content-Type': ctype = val
            elif name == 'Content-Length': clen = int(val)
            elif name == 'Content-Encoding': cenc = val
            elif name == 'Vary': vary = val
        return ctype, clen, cenc, vary

    def test_large_body_with_accept_gzip_is_compressed(self):
        import gzip
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('gzip, deflate')
        h._send_text(200, 'application/json', body)
        ctype, clen, cenc, vary = self._captured(h)
        self.assertEqual(cenc, 'gzip')
        self.assertLess(clen, len(body.encode()))
        self.assertEqual(ctype, 'application/json')
        self.assertIn('Accept-Encoding', vary or '')
        raw = h.wfile.getvalue()
        self.assertEqual(gzip.decompress(raw).decode(), body)

    def test_compress_level_1_used(self):
        """默认 compresslevel=1 (速度优先) 产生的 gzip 可正常解压。"""
        import gzip as gz_mod
        body = '{"x": "' + 'b' * 3000 + '"}'
        h = self._fake_handler('gzip')
        h._send_text(200, 'application/json', body)
        raw = h.wfile.getvalue()
        self.assertTrue(raw[:2] == b'\x1f\x8b', '应产生 gzip 头')
        self.assertEqual(gz_mod.decompress(raw).decode(), body)

    def test_no_accept_encoding_stays_raw(self):
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('')
        h._send_text(200, 'application/json', body)
        _, clen, cenc, _ = self._captured(h)
        self.assertIsNone(cenc)
        self.assertEqual(clen, len(body.encode()))
        self.assertEqual(h.wfile.getvalue().decode(), body)

    def test_small_body_never_compressed(self):
        body = '{"ok": 1}'
        h = self._fake_handler('gzip')
        h._send_text(200, 'application/json', body)
        _, clen, cenc, _ = self._captured(h)
        self.assertIsNone(cenc, '低于阈值的响应不应压缩')
        self.assertEqual(clen, len(body.encode()))

    def test_vary_merged_for_host_dependent_feed(self):
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('gzip')
        h._send_text(200, 'application/rss+xml', body, varies_on_host=True)
        _, _, cenc, vary = self._captured(h)
        self.assertEqual(cenc, 'gzip')
        for part in ('Host', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'Accept-Encoding'):
            self.assertIn(part, vary, f'Vary 应含 {part}')

    def test_head_request_content_length_matches_compressed(self):
        # write_body=False 时 Content-Length 应等于压缩后的 GET 长度
        import gzip
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('gzip')
        h._send_text(200, 'application/json', body, write_body=False)
        _, clen, cenc, _ = self._captured(h)
        self.assertEqual(cenc, 'gzip')
        from china_finance_rss import config as _cfg
        self.assertEqual(clen, len(gzip.compress(body.encode(), _cfg.GZIP_COMPRESSLEVEL)))
        self.assertEqual(h.wfile.getvalue(), b'', 'HEAD 不应写 body')

    def test_q0_gzip_is_refused(self):
        """RFC 9110: gzip;q=0 明确拒绝 ⇒ 不得压缩。"""
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('gzip;q=0')
        h._send_text(200, 'application/json', body)
        _, clen, cenc, _ = self._captured(h)
        self.assertIsNone(cenc, 'gzip;q=0 应回退原文')
        self.assertEqual(clen, len(body.encode()))
        self.assertEqual(h.wfile.getvalue().decode(), body)

    def test_uppercase_gzip_token_is_accepted(self):
        """content-coding token 大小写不敏感：GZIP 应压缩。"""
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('GZIP')
        h._send_text(200, 'application/json', body)
        _, _, cenc, _ = self._captured(h)
        self.assertEqual(cenc, 'gzip')

    def test_wildcard_accepts_gzip(self):
        """``*`` 表示接受任意编码 ⇒ 压缩。"""
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('*')
        h._send_text(200, 'application/json', body)
        _, _, cenc, _ = self._captured(h)
        self.assertEqual(cenc, 'gzip')

    def test_wildcard_q0_is_refused(self):
        """``*;q=0`` 拒绝一切编码 ⇒ 不压缩。"""
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('*;q=0')
        h._send_text(200, 'application/json', body)
        _, clen, cenc, _ = self._captured(h)
        self.assertIsNone(cenc)
        self.assertEqual(clen, len(body.encode()))

    def test_identity_is_not_gzip(self):
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('identity')
        h._send_text(200, 'application/json', body)
        _, _, cenc, _ = self._captured(h)
        self.assertIsNone(cenc)

    def test_vary_accept_encoding_sent_for_uncacheable_gzip(self):
        """cache=False 路径（/、/healthz、_send_error）被 gzip 时仍须发 Vary。"""
        body = '{"x": "' + 'a' * 5000 + '"}'
        h = self._fake_handler('gzip')
        h._send_text(200, 'text/html; charset=utf-8', body, cache=False)
        _, _, cenc, vary = self._captured(h)
        self.assertEqual(cenc, 'gzip')
        self.assertIn('Accept-Encoding', vary or '',
                      'gzip 响应即使不可缓存也须 Vary: Accept-Encoding')


class _StepClock:
    """Deterministic clock for SRV-T52b: every fallback draw advances 1s.

    An explicit ``timeval`` is formatted verbatim (no counter advance), so
    ``_send_text``'s Last-Modified is unaffected by the patch.
    """

    def __init__(self, start=1_700_000_000):
        self.start = start
        self._n = 0

    def next_epoch(self):
        value = self.start + self._n
        self._n += 1
        return value

    def time(self):
        return self.next_epoch()

    def formatdate(self, timeval=None, localtime=False, usegmt=True):
        if timeval is None:
            timeval = self.next_epoch()
        return formatdate(timeval, localtime=localtime, usegmt=usegmt)


class _FixedClock:
    """Controllable epoch clock for SRV-T63: ``now`` is advanced explicitly so a
    missing fingerprint inheritance is guaranteed to move past a whole TTL."""

    def __init__(self, start):
        self.now = start

    def time(self):
        return self.now


class RssConditionalGetTests(unittest.TestCase):
    """SRV-T46..T62: RSS conditional requests (ETag / Last-Modified / 304).

    A real HTTP server (the HttpSemanticsTests pattern) with the feed route's
    handler patched, so no upstream is contacted and the 200/304 composition,
    the ETag canonical projection and condition-header priority are the objects
    under test.
    """

    PATH = '/cls/telegraph'
    ITEM = {'title': 't1', 'link': 'http://x/1', 'description': 'd1',
            'pubDate': 'Thu, 01 Jan 2026 00:00:00 GMT', 'guid': 'g1'}

    @classmethod
    def setUpClass(cls):
        cls.srv = BoundedThreadPoolServer(('127.0.0.1', 0), RSSHandler,
                                          max_workers=2)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        cache_mod.feed_cache.clear()
        cache_mod._feed_fetch_locks.clear()     # F8: isolate the lock table
        cache_mod._feed_fetch_refs.clear()
        self.addCleanup(cache_mod.feed_cache.clear)
        self.addCleanup(cache_mod._feed_fetch_locks.clear)
        self.addCleanup(cache_mod._feed_fetch_refs.clear)

    # ---- helpers --------------------------------------------------------

    def _fake_handler(self, items=None, title='CLS'):
        entries = [dict(self.ITEM)] if items is None else items

        def handler(feed_url=None):
            return utils_mod.generate_rss(
                title, 'https://www.cls.cn/telegraph', 'D', entries,
                feed_url=feed_url, ttl=1)
        return handler

    def _patch_handler(self, handler):
        return patch.dict(srv.ROUTES[self.PATH], {'handler': handler})

    def _req(self, method='GET', path=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        try:
            conn.request(method, path or self.PATH, headers=headers or {})
            resp = conn.getresponse()
            body = resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, body
        finally:
            conn.close()

    def _assert_pubdate_differs_but_etag_same(self, x1, x2):
        p1 = [e.text for e in ET.fromstring(x1).findall(
            './channel/item/pubDate')]
        p2 = [e.text for e in ET.fromstring(x2).findall(
            './channel/item/pubDate')]
        self.assertNotEqual(p1, p2)             # the fallback clock advanced
        self.assertEqual(srv._feed_etag(x1), srv._feed_etag(x2))
        # Red/green direction: with the C1 projection disabled the two feeds
        # MUST hash differently — this is exactly what a "pubDate back in the
        # hash region" regression would trip.
        with patch.object(srv, '_PUBDATE_RE', re.compile(r'(?!)')):
            self.assertNotEqual(srv._feed_etag(x1), srv._feed_etag(x2))

    def test_t46_first_200_has_etag_and_last_modified(self):
        calls = {'put': 0}
        real_put = cache_mod.feed_cache_put

        def counting_put(path, xml, ttl, fingerprint=None):
            calls['put'] += 1
            return real_put(path, xml, ttl, fingerprint=fingerprint)

        with self._patch_handler(self._fake_handler()), \
             patch.object(srv, 'feed_cache_put', side_effect=counting_put):
            status, hdrs, body = self._req()
        self.assertEqual(status, 200)
        self.assertRegex(hdrs['etag'], r'^W/"[0-9a-f]{64}"$')
        lm = parsedate_to_datetime(hdrs['last-modified'])
        self.assertIsNotNone(lm)
        self.assertIsNotNone(lm.tzinfo)
        self.assertEqual(len(ET.fromstring(body).findall('./channel/item')), 1)
        self.assertEqual(calls['put'], 1)

    def test_t47_same_etag_replay_304_and_idempotent(self):
        calls = {'put': 0}
        real_put = cache_mod.feed_cache_put

        def counting_put(path, xml, ttl, fingerprint=None):
            calls['put'] += 1
            return real_put(path, xml, ttl, fingerprint=fingerprint)

        with self._patch_handler(self._fake_handler()), \
             patch.object(srv, 'feed_cache_put', side_effect=counting_put):
            status0, h0, _ = self._req()
            etag = h0['etag']
            first = self._req(headers={'If-None-Match': etag})
            second = self._req(headers={'If-None-Match': etag})
        self.assertEqual(status0, 200)
        for status, hdrs, body in (first, second):
            self.assertEqual(status, 304)
            self.assertEqual(body, b'')
            self.assertNotIn('content-encoding', hdrs)
            self.assertNotIn('content-length', hdrs)
            self.assertNotIn('content-type', hdrs)
            self.assertEqual(hdrs['etag'], etag)
            self.assertIn('cache-control', hdrs)
            self.assertIn('vary', hdrs)
            self.assertEqual(hdrs['last-modified'], h0['last-modified'])
        self.assertEqual(calls['put'], 1)

    def test_t48_inm_star_304_and_nonmatching_200(self):
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            st_star, _, body_star = self._req(headers={'If-None-Match': '*'})
            st_none, h_none, body_none = self._req(
                headers={'If-None-Match': '"nope"'})
        self.assertEqual(st_star, 304)
        self.assertEqual(body_star, b'')
        self.assertEqual(st_none, 200)
        self.assertEqual(
            len(ET.fromstring(body_none).findall('./channel/item')), 1)
        self.assertEqual(h_none['etag'], h0['etag'])

    def test_t49_multi_value_list_and_nonmatching_list_200(self):
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            opaque = h0['etag'][len('W/'):]
            st_hit, _, body_hit = self._req(headers={
                'If-None-Match': f'"a", W/"b", {opaque}'})
            st_miss, _, body_miss = self._req(
                headers={'If-None-Match': '"a","b"'})
        self.assertEqual(st_hit, 304)
        self.assertEqual(body_hit, b'')
        self.assertEqual(st_miss, 200)
        self.assertEqual(
            len(ET.fromstring(body_miss).findall('./channel/item')), 1)

    def test_t50_weak_strong_and_lowercase_w(self):
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            etag = h0['etag']
            opaque = etag[len('W/'):]
            st_strong = self._req(headers={'If-None-Match': opaque})[0]
            st_weak = self._req(headers={'If-None-Match': etag})[0]
            st_lower, _, body_lower = self._req(
                headers={'If-None-Match': 'w/' + opaque})
        self.assertTrue(etag.startswith('W/'))
        self.assertEqual(st_strong, 304)      # weak comparison, strong label
        self.assertEqual(st_weak, 304)
        self.assertEqual(st_lower, 200)       # literal W/ is case-sensitive
        self.assertTrue(body_lower)

    def test_t51_ims_future_past_and_equal_boundary(self):
        future = formatdate(time.time() + 3600, usegmt=True)
        past = formatdate(time.time() - 3600, usegmt=True)
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            st_future, _, b_future = self._req(
                headers={'If-Modified-Since': future})
            st_past, _, b_past = self._req(
                headers={'If-Modified-Since': past})
            st_equal, _, b_equal = self._req(
                headers={'If-Modified-Since': h0['last-modified']})
        self.assertEqual(st_future, 304)
        self.assertEqual(b_future, b'')
        self.assertEqual(st_past, 200)
        self.assertEqual(
            len(ET.fromstring(b_past).findall('./channel/item')), 1)
        self.assertEqual(st_equal, 304)          # client echo, same second
        self.assertEqual(b_equal, b'')

    def test_t52_channel_content_unchanged_across_ttl_same_etag(self):
        items = [dict(self.ITEM)]
        clock = _StepClock()
        with patch.object(utils_mod, 'formatdate', clock.formatdate):
            x1 = utils_mod.generate_rss('T', 'L', 'D', items,
                                        feed_url='u', ttl=1)
            x2 = utils_mod.generate_rss('T', 'L', 'D', items,
                                        feed_url='u', ttl=1)
            x3 = utils_mod.generate_rss('T', 'L', 'D', items,
                                        feed_url='u', ttl=3)
        self.assertNotEqual(x1, x2)             # lastBuildDate differs
        self.assertEqual(srv._feed_etag(x1), srv._feed_etag(x2))
        self.assertEqual(srv._feed_etag(x1), srv._feed_etag(x3))  # ttl out
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            cache_mod.feed_cache.clear()        # force a TTL-expiry re-gen
            st, _, body = self._req(headers={'If-None-Match': h0['etag']})
        self.assertEqual(st, 304)
        self.assertEqual(body, b'')

    def test_t52b_pure_function_only_pubdate_differs_same_etag(self):
        base = utils_mod.generate_rss(
            'T', 'L', 'D',
            [{'title': 't1', 'link': 'l1', 'description': 'd1',
              'pubDate': 'PD_A', 'guid': 'g1'},
             {'title': 't2', 'link': 'l2', 'description': 'd2',
              'pubDate': 'PD_B', 'guid': 'g2'}],
            feed_url='http://feeds.example.com/cls/telegraph', ttl=1)
        x1 = base.replace('PD_A', 'Thu, 01 Jan 2026 00:00:00 GMT') \
                 .replace('PD_B', 'Fri, 02 Jan 2026 00:00:00 GMT')
        x2 = base.replace('PD_A', 'Sat, 03 Jan 2026 11:22:33 GMT') \
                 .replace('PD_B', 'Sun, 04 Jan 2026 22:33:44 GMT')
        # only the two <pubDate> values differ; every other byte is identical
        self.assertNotEqual(x1, x2)
        self.assertEqual(srv._feed_etag(x1), srv._feed_etag(x2))
        # Removing the pubDate projection makes the two diverge — proof this
        # assertion really catches a "pubDate back in the hash" regression.
        with patch.object(srv, '_PUBDATE_RE', re.compile(r'(?!)')):
            self.assertNotEqual(srv._feed_etag(x1), srv._feed_etag(x2))

    def test_t52b_handler_eastmoney_missing_showtime_clocked(self):
        payload = ('var ajaxResult={"LivesList":[{"title":"T1",'
                   '"newsid":"1","digest":"D1"}]}')
        clock = _StepClock()
        with patch.object(srv, 'fetch_json', return_value=payload), \
             patch.object(srv, 'formatdate', clock.formatdate):
            x1 = srv.handle_eastmoney_kuaixun(feed_url='http://x/f')
            x2 = srv.handle_eastmoney_kuaixun(feed_url='http://x/f')
        self._assert_pubdate_differs_but_etag_same(x1, x2)

    def test_t52b_handler_ths_invalid_ctime_clocked(self):
        payload = json.dumps({'data': {'list': [
            {'title': 'T1', 'seq': '1', 'digest': 'D1',
             'ctime': 'not-a-number'}]}})
        clock = _StepClock()
        with patch.object(srv, 'fetch_json', return_value=payload), \
             patch.object(srv, 'time', clock):
            x1 = srv.handle_ths_kuaixun(feed_url='http://x/f')
            x2 = srv.handle_ths_kuaixun(feed_url='http://x/f')
        self._assert_pubdate_differs_but_etag_same(x1, x2)

    def test_t52b_handler_jin10_missing_time_clocked(self):
        payload = json.dumps({'data': [
            {'id': '1', 'data': {'title': 'T1', 'content': 'C1'}}]})
        clock = _StepClock()
        with patch.object(srv, 'fetch_json', return_value=payload), \
             patch.object(srv, 'get_jin10_public_headers', return_value={}), \
             patch.object(utils_mod, 'formatdate', clock.formatdate):
            x1 = srv.handle_jin10_flash(feed_url='http://x/f')
            x2 = srv.handle_jin10_flash(feed_url='http://x/f')
        self._assert_pubdate_differs_but_etag_same(x1, x2)

    def test_t52b_end_to_end_cross_ttl_304(self):
        payload = ('var ajaxResult={"LivesList":[{"title":"T1",'
                   '"newsid":"1","digest":"D1"}]}')
        clock = _StepClock()
        path = '/eastmoney/kuaixun'
        with patch.object(srv, 'fetch_json', return_value=payload), \
             patch.object(srv, 'formatdate', clock.formatdate):
            st1, h1, _ = self._req(path=path)
            cache_mod.feed_cache.clear()        # simulate TTL expiry
            st2, _, body = self._req(path=path,
                                     headers={'If-None-Match': h1['etag']})
        self.assertEqual(st1, 200)
        self.assertEqual(st2, 304)
        self.assertEqual(body, b'')

    def test_t53_content_change_changes_etag_and_200(self):
        xa = utils_mod.generate_rss('T', 'L', 'D', [dict(self.ITEM)],
                                    feed_url='u', ttl=1)
        xb = utils_mod.generate_rss('T', 'L', 'D',
                                    [dict(self.ITEM, title='CHANGED')],
                                    feed_url='u', ttl=1)
        self.assertNotEqual(srv._feed_etag(xa), srv._feed_etag(xb))
        holder = {'items': [dict(self.ITEM)]}

        def handler(feed_url=None):
            return utils_mod.generate_rss('T', 'L', 'D', holder['items'],
                                          feed_url=feed_url, ttl=1)

        with self._patch_handler(handler):
            _, h_std, _ = self._req()
            cache_mod.feed_cache.clear()
            _, h_alt, _ = self._req(headers={'Host': 'other.example.com'})
            self.assertNotEqual(h_std['etag'], h_alt['etag'])   # atom:link
            cache_mod.feed_cache.clear()
            holder['items'] = [dict(self.ITEM, title='NEW')]
            st, h1, body = self._req(
                headers={'If-None-Match': h_std['etag']})
        self.assertEqual(st, 200)
        self.assertIn(b'NEW', body)
        self.assertNotEqual(h1['etag'], h_std['etag'])

    def test_t54_head_304_and_head_200(self):
        future = formatdate(time.time() + 3600, usegmt=True)
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            st_inm, h_inm, b_inm = self._req(
                'HEAD', headers={'If-None-Match': h0['etag']})
            st_ims, h_ims, b_ims = self._req(
                'HEAD', headers={'If-Modified-Since': future})
            st_none, h_none, b_none = self._req('HEAD')
            _, h_get, _ = self._req(headers={'If-None-Match': h0['etag']})
        self.assertEqual((st_inm, st_ims, st_none), (304, 304, 200))
        for hdrs, body in ((h_inm, b_inm), (h_ims, b_ims)):
            self.assertEqual(body, b'')
            self.assertEqual(hdrs['etag'], h0['etag'])
            self.assertIn('cache-control', hdrs)
            self.assertIn('vary', hdrs)
        self.assertEqual(h_inm['etag'], h_get['etag'])
        self.assertEqual(h_inm['cache-control'], h_get['cache-control'])
        self.assertEqual(h_inm['vary'], h_get['vary'])
        self.assertEqual(b_none, b'')
        self.assertIn('content-length', h_none)

    def test_t55_public_base_url_unset_304_private_vary_host(self):
        # F2 rewrite: the old case was pseudo-green — it still answered 304 only
        # because the *path* key had cached a representation from before
        # PUBLIC_BASE_URL was toggled.  Now the key carries the Host when
        # PUBLIC_BASE_URL is unset, so author the stale entry explicitly
        # (no reliance on TTL timing) and pin the 304 header shape.
        #
        # P2-2: the injected entry is genuinely consumed, not decorative.  Its
        # fingerprint matches the refetched body, so `feed_cache_put` inherits
        # its `last_modified=1.0`; the 304 must echo exactly that inherited
        # value.  A broken inheritance restamps "now" ⇒ the assertion reddens.
        inherited_lm = formatdate(1.0, localtime=False, usegmt=True)

        def _inject(base_url):
            xml = self._fake_handler()(feed_url=base_url + self.PATH)
            key = srv._feed_cache_key(self.PATH, base_url)
            cache_mod.feed_cache[key] = {
                'xml': xml, 'time': 1.0, 'last_modified': 1.0,
                'fingerprint': srv._feed_fingerprint(xml),
                'last_access': 1.0, 'expires_at': time.time() - 1}  # stale
            return xml

        with self._patch_handler(self._fake_handler()):
            with patch.object(srv, 'PUBLIC_BASE_URL', ''):
                base = f'http://127.0.0.1:{self.port}'
                xml = _inject(base)
                st_priv, h_priv, _ = self._req(
                    headers={'If-None-Match': srv._feed_etag(xml)})
                self.assertEqual(h_priv.get('last-modified'), inherited_lm)
            cache_mod.feed_cache.clear()
            with patch.object(srv, 'PUBLIC_BASE_URL',
                              'https://feeds.example.com'):
                base = 'https://feeds.example.com'
                xml = _inject(base)
                st_pub, h_pub, _ = self._req(
                    headers={'If-None-Match': srv._feed_etag(xml)})
                self.assertEqual(h_pub.get('last-modified'), inherited_lm)
        self.assertEqual(st_priv, 304)
        self.assertIn('private', h_priv['cache-control'])
        for part in ('Host', 'X-Forwarded-Host',
                     'X-Forwarded-Proto', 'Accept-Encoding'):
            self.assertIn(part, h_priv['vary'])
        self.assertEqual(st_pub, 304)
        self.assertIn('public', h_pub['cache-control'])
        self.assertNotIn('Host', h_pub['vary'])
        self.assertIn('Accept-Encoding', h_pub['vary'])

    def test_t56_invalid_date_header_is_200_and_priority(self):
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            for bad in ('not-a-date', '99', ''):
                st, _, body = self._req(headers={'If-Modified-Since': bad})
                self.assertEqual(st, 200, repr(bad))
                self.assertTrue(body, repr(bad))
            st_hit = self._req(headers={'If-None-Match': h0['etag'],
                                        'If-Modified-Since': 'bad'})[0]
            st_miss, _, body_miss = self._req(
                headers={'If-None-Match': '"nope"',
                         'If-Modified-Since': 'bad'})
        self.assertEqual(st_hit, 304)
        self.assertEqual(st_miss, 200)
        self.assertTrue(body_miss)

    def test_t56b_inm_miss_with_matching_ims_is_200(self):
        future = formatdate(time.time() + 3600, usegmt=True)
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            st_ims, _, _ = self._req(headers={'If-Modified-Since': future})
            st, _, body = self._req(headers={'If-None-Match': '"nope"',
                                             'If-Modified-Since': future})
        self.assertEqual(st_ims, 304)            # IMS alone would have hit
        self.assertEqual(st, 200)                # INM mismatch fully ignores it
        self.assertTrue(body)
        self.assertEqual(
            len(ET.fromstring(body).findall('./channel/item')), 1)

    def test_t57_gzip_304_no_content_encoding_and_etag_independent(self):
        big = [dict(self.ITEM, title=f't{i}', guid=f'g{i}',
                    description='x' * 120) for i in range(40)]
        fixed = 'Thu, 01 Jan 2026 00:00:00 GMT'
        self.assertTrue(srv._accepts_gzip('gzip'))
        with self._patch_handler(self._fake_handler(big)), \
             patch.object(utils_mod, 'formatdate', return_value=fixed):
            st_id, h_id, body_id = self._req()
            self.assertGreaterEqual(len(body_id), config.GZIP_MIN_BYTES)
            self.assertNotIn('content-encoding', h_id)
            etag = h_id['etag']
            cache_mod.feed_cache.clear()
            st_gz, h_gz, body_gz = self._req(
                headers={'Accept-Encoding': 'gzip'})
            st_304, h_304, body_304 = self._req(
                headers={'Accept-Encoding': 'gzip',
                         'If-None-Match': etag})
        self.assertEqual((st_id, st_gz), (200, 200))
        self.assertEqual(h_gz['etag'], etag)     # encoding-independent label
        self.assertEqual(gzip.decompress(body_gz), body_id)
        self.assertEqual(st_304, 304)
        self.assertEqual(body_304, b'')
        self.assertNotIn('content-encoding', h_304)

    def test_t58_ttl_output_position_boundaries_and_guard(self):
        xml = utils_mod.generate_rss('T', 'L', 'D', [], feed_url='u', ttl=1)
        self.assertIn('<ttl>1</ttl>', xml)
        self.assertLess(xml.index('</lastBuildDate>'),
                        xml.index('<ttl>1</ttl>'))
        self.assertLess(xml.index('<ttl>1</ttl>'), xml.index('<atom:link'))
        self.assertNotIn('<ttl>', utils_mod.generate_rss(
            'T', 'L', 'D', [], feed_url='u'))
        for bad in (0, -1, -5):
            self.assertNotIn('<ttl', utils_mod.generate_rss(
                'T', 'L', 'D', [], feed_url='u', ttl=bad))
        expected = {0: 1, -1: 1, 59: 1, 60: 1, 61: 2, 180: 3, 181: 4}
        for raw, minutes in expected.items():
            with patch.object(srv, 'cache_policy', return_value={'ttl': raw}):
                self.assertEqual(srv._feed_ttl_minutes(), minutes, raw)

    def test_t59_degraded_feed_no_false_304_and_ims_disabled(self):
        def boom(feed_url=None):
            raise FetchError('upstream_error', url='x')

        future = formatdate(time.time() + 3600, usegmt=True)
        with self._patch_handler(self._fake_handler()):
            _, h_ok, _ = self._req()
            ok_etag = h_ok['etag']
            cache_mod.feed_cache.clear()
            with self._patch_handler(boom):
                st, h_err, _ = self._req(
                    headers={'If-None-Match': ok_etag})
                err_etag = h_err['etag']
                st_replay, _, replay_body = self._req(
                    headers={'If-None-Match': err_etag})
                st_ims, h_ims, body_ims = self._req(
                    headers={'If-Modified-Since': future})
        self.assertEqual(st, 200)                # distinct representation
        self.assertNotEqual(err_etag, ok_etag)
        self.assertNotIn('last-modified', h_err)
        self.assertEqual(st_replay, 304)         # same error repr replays 304
        self.assertEqual(replay_body, b'')
        self.assertEqual(st_ims, 200)
        self.assertNotIn('last-modified', h_ims)
        self.assertTrue(body_ims)

    def test_t61_scope_negative_static_and_json_never_304(self):
        future = formatdate(time.time() + 3600, usegmt=True)
        cond = {'If-None-Match': '"whatever"', 'If-Modified-Since': future}
        with patch.object(srv, 'PUBLIC_BASE_URL', ''), \
             patch.object(srv, 'handle_margin', return_value={}), \
             patch.object(srv, 'build_health_payload',
                          return_value={'status': 'ok'}):
            for path in ('/opml.xml', '/', '/market/margin?market=99',
                         '/healthz'):
                base_status, _, base_body = self._req(path=path)
                st, hdrs, body = self._req(path=path, headers=cond)
                self.assertEqual(base_status, 200, path)
                self.assertEqual(st, 200, path)          # never a 304
                self.assertNotIn('etag', hdrs, path)     # BR-SRV-36/44
                if path in ('/opml.xml', '/'):
                    self.assertEqual(base_body, body, path)

    def test_t62_200_and_304_headers_diff_verbatim(self):
        for base_url in ('', 'https://feeds.example.com'):
            cache_mod.feed_cache.clear()
            with self._patch_handler(self._fake_handler()), \
                 patch.object(srv, 'PUBLIC_BASE_URL', base_url):
                st200, h200, body200 = self._req()
                st304, h304, body304 = self._req(
                    headers={'If-None-Match': h200['etag']})
            self.assertEqual(st200, 200, base_url)
            self.assertEqual(st304, 304, base_url)
            for name in ('etag', 'last-modified', 'cache-control', 'vary'):
                self.assertEqual(h200[name], h304[name], (base_url, name))
            self.assertEqual(body304, b'', base_url)
            for absent in ('content-type', 'content-length',
                           'content-encoding'):
                self.assertNotIn(absent, h304, (base_url, absent))
            self.assertTrue(body200, base_url)

    # ---- SRV-T63..T70 (v1.9 / F1..F6) -----------------------------------

    def test_t63_ims_cross_ttl_still_304(self):
        """F1 decisive evidence: a TTL regeneration of the same canonical
        content must not advance Last-Modified, so an IMS-only client keeps
        getting 304.  A missing fingerprint inheritance makes the rewrite time
        (clock.now, advanced a whole TTL) the new Last-Modified ⇒ 200 (red)."""
        path = self.PATH
        base = 'https://feeds.example.com'
        clock = _FixedClock(time.time())
        with patch.object(srv, 'PUBLIC_BASE_URL', base), \
             self._patch_handler(self._fake_handler()), \
             patch.object(cache_mod.time, 'time', clock.time):
            st1, h1, _ = self._req()
            self.assertEqual(st1, 200)
            key = srv._feed_cache_key(path, base)
            lm1 = cache_mod.feed_cache[key]['last_modified']
            cache_mod.feed_cache[key]['expires_at'] = clock.now - 1  # expire in place
            clock.now += 3600                       # cross a whole TTL
            with patch.object(utils_mod, 'formatdate', _StepClock().formatdate):
                st2, h2, body2 = self._req(
                    headers={'If-Modified-Since': h1['last-modified']})
            self.assertEqual(st2, 304)
            self.assertEqual(body2, b'')
            self.assertEqual(h2['last-modified'], h1['last-modified'])
            self.assertEqual(cache_mod.feed_cache[key]['last_modified'], lm1)
            self.assertLess(lm1, clock.now)         # the rewrite clock did advance

    def test_t64_fingerprint_inherit_and_change_two_ways(self):
        """F1: derived-metadata-only changes inherit (no LM advance); real
        content changes advance both ETag and LM and defeat the old INM."""
        x1 = utils_mod.generate_rss('T', 'L', 'D', [dict(self.ITEM)],
                                    feed_url='u', ttl=1)
        x2 = utils_mod.generate_rss(
            'T', 'L', 'D',
            [dict(self.ITEM, pubDate='Fri, 02 Jan 2026 00:00:00 GMT')],
            feed_url='u', ttl=3)
        self.assertNotEqual(x1, x2)                 # bytes differ …
        self.assertEqual(srv._feed_fingerprint(x1), srv._feed_fingerprint(x2))
        self.assertEqual(srv._feed_etag(x1), srv._feed_etag(x2))   # … fingerprint does not
        cache_mod.feed_cache.clear()
        e1 = cache_mod.feed_cache_put('/k', x1, 30,
                                      fingerprint=srv._feed_fingerprint(x1))
        cache_mod.feed_cache['/k']['expires_at'] = time.time() - 1
        time.sleep(0.01)
        e2 = cache_mod.feed_cache_put('/k', x2, 30,
                                      fingerprint=srv._feed_fingerprint(x2))
        self.assertEqual(e2['last_modified'], e1['last_modified'])  # inherited
        time.sleep(0.01)
        x3 = utils_mod.generate_rss('T', 'L', 'D',
                                    [dict(self.ITEM, title='CHANGED')],
                                    feed_url='u', ttl=1)
        self.assertNotEqual(srv._feed_etag(x1), srv._feed_etag(x3))
        e3 = cache_mod.feed_cache_put('/k', x3, 30,
                                      fingerprint=srv._feed_fingerprint(x3))
        self.assertGreater(e3['last_modified'], e1['last_modified'])  # advanced
        # End-to-end: an old INM against changed content is a 200 full body.
        with self._patch_handler(self._fake_handler()):
            _, h200, _ = self._req()
        cache_mod.feed_cache.clear()
        holder = {'items': [dict(self.ITEM, title='CHANGED')]}

        def changed(feed_url=None):
            return utils_mod.generate_rss('T', 'L', 'D', holder['items'],
                                          feed_url=feed_url, ttl=1)

        with self._patch_handler(changed):
            st, _, body = self._req(headers={'If-None-Match': h200['etag']})
        self.assertEqual(st, 200)
        self.assertIn(b'CHANGED', body)

    def test_t65_cross_host_key_isolation(self):
        """F2: with PUBLIC_BASE_URL unset the key carries base_url, so one
        forged Host cannot rewrite another host's <atom:link>; with it set the
        key is Host-independent (one entry)."""
        with patch.object(srv, 'PUBLIC_BASE_URL', ''), \
             self._patch_handler(self._fake_handler()):
            st_a, _, body_a = self._req(headers={'Host': 'a.example'})
            st_b, _, body_b = self._req(headers={'Host': 'b.example'})
            self.assertEqual((st_a, st_b), (200, 200))
            self.assertIn(b'http://a.example', body_a)
            self.assertNotIn(b'a.example', body_b)
            self.assertIn(b'http://b.example', body_b)
            key_a = srv._feed_cache_key(self.PATH, 'http://a.example')
            key_b = srv._feed_cache_key(self.PATH, 'http://b.example')
            self.assertNotEqual(key_a, key_b)
            self.assertIn(key_a, cache_mod.feed_cache)
            self.assertIn(key_b, cache_mod.feed_cache)
            self.assertEqual(cache_mod.feed_cache[key_a]['xml'],
                             body_a.decode('utf-8'))   # no Host bleed
        cache_mod.feed_cache.clear()
        with patch.object(srv, 'PUBLIC_BASE_URL', 'https://feeds.example.com'), \
             self._patch_handler(self._fake_handler()):
            self._req(headers={'Host': 'a.example'})
            self._req(headers={'Host': 'b.example'})
            self.assertEqual(list(cache_mod.feed_cache), [self.PATH])

    def test_t66_http_304_total_increments(self):
        srv.metrics.reset()
        try:
            with self._patch_handler(self._fake_handler()):
                st200, h200, _ = self._req()
                self.assertEqual(st200, 200)
                self.assertEqual(srv.metrics.snapshot()['http_304_total'], 0)
                st304, _, _ = self._req(
                    headers={'If-None-Match': h200['etag']})
                self.assertEqual(st304, 304)
                self.assertEqual(srv.metrics.snapshot()['http_304_total'], 1)
        finally:
            srv.metrics.reset()

    def test_t67_304_header_set_whitelist(self):
        with self._patch_handler(self._fake_handler()):
            _, h200, _ = self._req()
            conn = http.client.HTTPConnection('127.0.0.1', self.port)
            try:
                conn.request('GET', self.PATH,
                             headers={'If-None-Match': h200['etag']})
                resp = conn.getresponse()
                status = resp.status
                body = resp.read()
                names = {k.lower() for k, _ in resp.getheaders()}
            finally:
                conn.close()
        self.assertEqual(status, 304)
        self.assertEqual(body, b'')
        self.assertEqual(names,
                         {'etag', 'last-modified', 'cache-control', 'vary',
                          'server', 'date'})
        for absent in ('content-length', 'content-type', 'content-encoding'):
            self.assertNotIn(absent, names)

    def test_t68_inm_extreme_inputs_are_200_and_do_not_raise(self):
        with self._patch_handler(self._fake_handler()):
            _, h0, _ = self._req()
            opaque = h0['etag'][len('W/'):]
            for value in ('', 'x' * 9000, 'W/', 'w/' + opaque, ', ,',
                          '"a b"', 'W/"unquoted'):
                st, _, body = self._req(headers={'If-None-Match': value})
                self.assertEqual(st, 200, repr(value))
                self.assertTrue(body, repr(value))
                self.assertEqual(
                    len(ET.fromstring(body).findall('./channel/item')), 1)

    def test_t69_feed_ttl_minutes_matches_max_age_authority(self):
        h = RSSHandler.__new__(RSSHandler)
        real_ttl = cache_policy('feed')['ttl']
        for path in srv.ROUTES:
            self.assertEqual(srv._CACHE_AGE_DOMAINS[path], 'feed', path)
            h.path = path
            self.assertEqual(h._cache_age(), real_ttl, path)
        self.assertEqual(srv._feed_ttl_minutes(), -(-real_ttl // 60))
        for raw, minutes in ((30, 1), (180, 3)):
            with patch.object(srv, 'cache_policy', return_value={'ttl': raw}):
                h.path = self.PATH
                self.assertEqual(h._cache_age(), raw)
                self.assertEqual(srv._feed_ttl_minutes(), minutes)
                self.assertEqual(srv._feed_ttl_minutes(), -(-raw // 60))

        # P2-3: today feed and news_url coincide (same L3 / factor 1.0), so the
        # checks above cannot tell the two authorities apart.  Force a controlled
        # divergence: both the <ttl> and the Cache-Control max-age must follow
        # `feed` (7 → 1 minute), never `news_url` (999 → 17 minutes).
        def _divergent(domain, now=None):
            return {'ttl': 7} if domain == 'feed' else {'ttl': 999}

        with patch.object(srv, 'cache_policy', side_effect=_divergent):
            h.path = self.PATH
            self.assertEqual(h._cache_age(), 7)               # feed, not news_url
            self.assertNotEqual(h._cache_age(), 999)
            self.assertEqual(srv._feed_ttl_minutes(), 1)      # ceil(7/60)
            self.assertNotEqual(srv._feed_ttl_minutes(), 17)  # ceil(999/60)

    def test_t70_put_return_used_and_no_second_lookup(self):
        """F5: the miss path consumes `feed_cache_put`'s return value — exactly
        two `feed_cache_get_entry` calls (① first + ③ double-check), never a
        third after put; the response still carries Last-Modified."""
        h = RSSHandler.__new__(RSSHandler)
        h.headers = {}
        captured = {}
        h._send_text = lambda *a, **kw: captured.update(kw)
        cache_mod.feed_cache.clear()
        get_calls = {'n': 0}
        put_returns = []
        real_get = cache_mod.feed_cache_get_entry
        real_put = cache_mod.feed_cache_put

        def counting_get(key):
            get_calls['n'] += 1
            return real_get(key)

        def counting_put(key, xml, ttl, fingerprint=None):
            entry = real_put(key, xml, ttl, fingerprint=fingerprint)
            put_returns.append(entry)
            return entry

        with self._patch_handler(self._fake_handler()), \
             patch.object(srv, 'feed_cache_get_entry',
                          side_effect=counting_get), \
             patch.object(srv, 'feed_cache_put', side_effect=counting_put):
            h._serve_feed(self.PATH, 'http://localhost:8000')
        self.assertEqual(get_calls['n'], 2)          # ① + ③ double-check only
        self.assertEqual(len(put_returns), 1)
        self.assertIsInstance(put_returns[0], dict)
        self.assertEqual(set(put_returns[0]),
                         {'xml', 'time', 'last_modified', 'fingerprint',
                          'last_access', 'expires_at'})
        self.assertIsNotNone(captured.get('last_modified'))
        self.assertRegex(captured.get('etag'), r'^W/"[0-9a-f]{64}"$')

    def test_t71_feed_fetch_lock_table_converges(self):
        """SRV-T71 / F8 / BR-SRV-50: serial requests for N distinct Hosts on the
        same feed path.  Each key is reclaimed once its request finishes, so the
        fetch-lock table size is bounded by the in-flight key count and does not
        track the cumulative Host count."""
        seen_keys = set()
        with self._patch_handler(self._fake_handler()), \
             patch.object(srv, 'PUBLIC_BASE_URL', ''):
            for i in range(50):
                host = f'h{i}.example.com'
                status, _, body = self._req(headers={'Host': host})
                self.assertEqual(status, 200)
                self.assertTrue(body)
                seen_keys.add(
                    srv._feed_cache_key(self.PATH, f'http://{host}'))
                self.assertEqual(
                    len(cache_mod._feed_fetch_locks), 0,
                    f'lock table leaked after request {i} ({host})')
        # 50 distinct keys were exercised, yet nothing remains: not N-bounded.
        self.assertEqual(len(seen_keys), 50)
        self.assertEqual(len(cache_mod._feed_fetch_locks), 0)
        self.assertEqual(len(cache_mod._feed_fetch_refs), 0)

    def test_t72_concurrent_same_key_single_fetch(self):
        """SRV-T72 ① / F8: two concurrent requests for one key fetch exactly
        once — the second thread blocks on the acquired per-key lock, then its
        double-check hits the entry the first thread wrote."""
        h = RSSHandler.__new__(RSSHandler)
        cache_mod.feed_cache.clear()
        calls = {'n': 0}
        entered = threading.Event()
        finish = threading.Event()

        def fetch():
            calls['n'] += 1
            entered.set()
            finish.wait(2.0)
            return '<rss/>'

        results = []

        def worker():
            results.append(h._get_or_fetch_feed('/t71-key', fetch))

        first = threading.Thread(target=worker)
        first.start()
        self.assertTrue(entered.wait(2.0))       # first thread is inside fetch
        second = threading.Thread(target=worker)
        second.start()
        deadline = time.time() + 2.0
        while (cache_mod._feed_fetch_refs.get('/t71-key') != 2
               and time.time() < deadline):
            time.sleep(0.005)                    # wait until the second is waiting
        self.assertEqual(calls['n'], 1)          # never a second fetch
        self.assertEqual(cache_mod._feed_fetch_refs.get('/t71-key'), 2)
        finish.set()
        first.join(2.0)
        second.join(2.0)
        self.assertEqual(calls['n'], 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], '<rss/>')
        self.assertEqual(results[1][0], '<rss/>')
        self.assertNotIn('/t71-key', cache_mod._feed_fetch_locks)
        self.assertNotIn('/t71-key', cache_mod._feed_fetch_refs)

    def test_t72_exception_path_reclaims_key(self):
        """SRV-T72 ② / F8: a raising fetch degrades to a valid feed (HTTP 200)
        and still releases the per-key reference in `finally` — the key is
        popped from both tables instead of leaking."""
        def boom(feed_url=None):
            raise RuntimeError('boom')

        with self._patch_handler(boom), \
             patch.object(srv, 'PUBLIC_BASE_URL', ''):
            status, _, body = self._req(headers={'Host': 'boom.example.com'})
            key = srv._feed_cache_key(self.PATH, 'http://boom.example.com')
        self.assertEqual(status, 200)            # rss shape degrades, never 500
        self.assertIn(b'<rss', body)
        self.assertNotIn(key, cache_mod._feed_fetch_locks)
        self.assertNotIn(key, cache_mod._feed_fetch_refs)
        self.assertEqual(len(cache_mod._feed_fetch_locks), 0)
        self.assertEqual(len(cache_mod._feed_fetch_refs), 0)

    def test_t73_concurrent_distinct_hosts_bounded_and_in_sync(self):
        """SRV-T73 / F8 / BR-SRV-50: K=8 distinct-Host keys for the same feed
        path in flight at once.

        A blocking fetch stub plus a `threading.Event` makes the overlap
        deterministic (never a `sleep` roulette): each fetch parks until all K
        keys have entered, so the tables can be sampled mid-flight.  Asserts
        ① both tables are bounded by K and stay in sync; ② once every caller
        returns both drain to zero.  A `release` outside `finally`, a pop of
        only one table, or cumulative (never reclaimed) growth all turn this
        red.
        """
        h = RSSHandler.__new__(RSSHandler)
        K = 8
        entered = threading.Event()
        release = threading.Event()
        state = {'entered': 0, 'calls': 0}
        state_lock = threading.Lock()

        def fetch():
            with state_lock:
                state['calls'] += 1
                state['entered'] += 1
                if state['entered'] >= K:
                    entered.set()
            release.wait(15.0)
            return '<rss/>'

        results = []
        errors = []
        with patch.object(srv, 'PUBLIC_BASE_URL', ''):
            keys = [srv._feed_cache_key(self.PATH, f'http://h{i}.example.com')
                    for i in range(K)]
            self.assertEqual(len(set(keys)), K)     # distinct Host ⇒ distinct key

            def worker(key):
                try:
                    results.append(h._get_or_fetch_feed(key, fetch))
                except Exception as exc:            # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
            for t in threads:
                t.start()
            try:
                # 15s, not 5s: under extreme scheduler delay a 5s window can
                # expire *before* all K threads park, releasing them early and
                # producing a spurious red.  The event stays the sync primitive
                # (never a sleep) — only the wait budget is generous.
                self.assertTrue(entered.wait(15.0),
                                'not all K fetches reached the stub in time')
                # ① in flight: bounded by K and both tables stay in sync
                self.assertGreaterEqual(len(cache_mod._feed_fetch_locks), 1)
                self.assertLessEqual(len(cache_mod._feed_fetch_locks), K)
                self.assertEqual(len(cache_mod._feed_fetch_refs),
                                 len(cache_mod._feed_fetch_locks))
                self.assertEqual(len(cache_mod._feed_fetch_refs), K)
            finally:
                release.set()
                for t in threads:
                    t.join(15.0)
            # Every worker must actually be finished: a thread still running
            # after `join(15.0)` is the concrete evidence of "who did not
            # finish", instead of a silently-dropped result.
            for t in threads:
                self.assertFalse(t.is_alive(),
                                 'a worker thread did not finish after join(15s)')

        self.assertEqual(errors, [])
        self.assertEqual(state['calls'], K)         # exactly one fetch per key
        self.assertEqual(len(results), K)
        # ② every caller returned ⇒ both tables fully drained
        self.assertEqual(len(cache_mod._feed_fetch_locks), 0)
        self.assertEqual(len(cache_mod._feed_fetch_refs), 0)


if __name__ == '__main__':
    unittest.main()
