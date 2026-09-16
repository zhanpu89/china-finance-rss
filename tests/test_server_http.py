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

import http.client
import json
import threading
import time
import unittest
from collections import OrderedDict
from unittest.mock import patch
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from china_finance_rss import config
from china_finance_rss import server as srv
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
        xml = srv._guard(self._boom, shape='rss',
                         rss_info={'title': 'T', 'link': 'L', 'description': 'D'},
                         feed_url='http://x/f')
        root = ET.fromstring(xml)
        self.assertIsNotNone(root.find('./channel/item'))

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

    def _handler(self):
        return RSSHandler.__new__(RSSHandler)

    def test_double_check_single_fetch_single_thread(self):
        state = {'xml': None}
        calls = {'n': 0}

        def fetch():
            calls['n'] += 1
            return '<rss/>'

        h = self._handler()
        with patch.object(srv, 'feed_cache_get', side_effect=lambda p: state['xml']), \
             patch.object(srv, 'feed_cache_put',
                          side_effect=lambda p, xml, ttl: state.__setitem__('xml', xml)):
            self.assertEqual(h._get_or_fetch_feed('/cls/telegraph', fetch), '<rss/>')
            self.assertEqual(h._get_or_fetch_feed('/cls/telegraph', fetch), '<rss/>')
        self.assertEqual(calls['n'], 1)

    def test_double_check_single_fetch_concurrent(self):
        state = {'xml': None}
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

        with patch.object(srv, 'feed_cache_get', side_effect=lambda p: state['xml']), \
             patch.object(srv, 'feed_cache_put',
                          side_effect=lambda p, xml, ttl: state.__setitem__('xml', xml)):
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
        captured = {}
        h._send_text = lambda *a, **k: captured.update(k)
        with patch.object(srv.RSSHandler, '_get_or_fetch_feed',
                          return_value='<rss/>'), \
             patch.object(srv, 'PUBLIC_BASE_URL', ''):
            h._serve_feed('/cls/telegraph', 'http://feeds.example.com')
        self.assertTrue(captured.get('varies_on_host'))

    def test_serve_feed_is_public_with_configured_base_url(self):
        h = RSSHandler.__new__(RSSHandler)
        captured = {}
        h._send_text = lambda *a, **k: captured.update(k)
        with patch.object(srv.RSSHandler, '_get_or_fetch_feed',
                          return_value='<rss/>'), \
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

if __name__ == '__main__':
    unittest.main()
