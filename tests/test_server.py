import unittest
from email.utils import parsedate_to_datetime
from unittest.mock import patch
from xml.etree import ElementTree as ET

from china_finance_rss.utils import (
    generate_rss,
    generate_error_rss,
    generate_opml,
    parse_china_datetime_to_rfc822,
    cls_sign_params,
    parse_cls_items,
    extract_jin10_public_app_id,
    parse_jin10_items,
    parse_wallstreetcn_items,
)
from china_finance_rss.server import ROUTES, handle_cls_hotplate, handle_cls_plate, build_health_payload
from china_finance_rss.market_api import (
    _transform_margin,
    handle_margin,
)


class FeedGenerationTests(unittest.TestCase):
    def test_generate_rss_includes_atom_self_link_when_feed_url_given(self):
        xml = generate_rss(
            "Example",
            "https://example.com",
            "Example feed",
            [],
            feed_url="https://feeds.example.com/example.xml",
        )

        root = ET.fromstring(xml)
        atom_link = root.find("./channel/{http://www.w3.org/2005/Atom}link")

        self.assertIsNotNone(atom_link)
        self.assertEqual(atom_link.attrib["href"], "https://feeds.example.com/example.xml")
        self.assertEqual(atom_link.attrib["rel"], "self")
        self.assertEqual(atom_link.attrib["type"], "application/rss+xml")

    def test_generate_error_rss_returns_valid_feed_with_diagnostic_item(self):
        xml = generate_error_rss(
            "CLS Telegraph",
            "https://www.cls.cn/telegraph",
            "CLS feed",
            RuntimeError("HTTP 404 from upstream"),
            feed_url="https://feeds.example.com/cls/telegraph",
        )

        root = ET.fromstring(xml)
        item = root.find("./channel/item")

        self.assertIsNotNone(item)
        self.assertIn("temporarily unavailable", item.findtext("title"))
        self.assertIn("HTTP 404 from upstream", item.findtext("description"))
        self.assertEqual(item.find("guid").attrib["isPermaLink"], "false")

    def test_generate_opml_lists_all_builtin_feeds_with_absolute_urls(self):
        xml = generate_opml("https://feeds.example.com", ROUTES)
        root = ET.fromstring(xml)
        urls = {
            outline.attrib["xmlUrl"]
            for outline in root.findall("./body/outline/outline")
        }

        self.assertIn("https://feeds.example.com/cls/telegraph", urls)
        self.assertIn("https://feeds.example.com/eastmoney/kuaixun", urls)
        self.assertIn("https://feeds.example.com/ths/kuaixun", urls)
        self.assertIn("https://feeds.example.com/jin10/flash", urls)
        self.assertIn("https://feeds.example.com/wallstreetcn/live", urls)
        # Hotplate is a JSON endpoint, not an RSS feed — not in OPML
        self.assertNotIn("https://feeds.example.com/cls/hotplate", urls)


class TimeParsingTests(unittest.TestCase):
    def test_parse_china_datetime_to_rfc822_treats_source_time_as_utc_plus_8(self):
        dt = parsedate_to_datetime(
            parse_china_datetime_to_rfc822("2026-06-12 16:00:00")
        )

        self.assertEqual(dt.hour, 8)
        self.assertEqual(dt.utcoffset().total_seconds(), 0)


class SourceParserTests(unittest.TestCase):
    def test_cls_sign_params_matches_frontend_sha1_then_md5_signature(self):
        params = {
            "refresh_type": 1,
            "rn": 20,
            "last_time": 0,
            "os": "web",
            "sv": "8.7.9",
            "app": "CailianpressWeb",
        }

        self.assertEqual(
            cls_sign_params(params),
            "e11ef7d616d8f9a2f056e6df1aefc4d4",
        )

    def test_parse_cls_items_maps_roll_data(self):
        payload = {
            "data": {
                "roll_data": [{
                    "id": 123,
                    "ctime": 1781278243,
                    "brief": "LME期铜收涨216美元",
                    "content": "财联社6月13日电，LME期铜收涨216美元。",
                }]
            }
        }

        items = parse_cls_items(payload)

        self.assertEqual(items[0]["title"], "LME期铜收涨216美元")
        self.assertEqual(items[0]["description"], "财联社6月13日电，LME期铜收涨216美元。")
        self.assertEqual(items[0]["link"], "https://www.cls.cn/detail/123")
        self.assertEqual(items[0]["guid"], "cls_123")

    def test_extract_jin10_public_app_id_from_frontend_bundle(self):
        bundle = 'headers:{"x-app-id":"public-web-app-id","x-version":t,handleError:!0}'

        self.assertEqual(extract_jin10_public_app_id(bundle), "public-web-app-id")

    def test_parse_jin10_items_maps_nested_flash_data(self):
        payload = {
            "data": [{
                "id": "20260612233021430800",
                "time": "2026-06-12 23:30:21",
                "data": {
                    "title": "CME补上周末交易",
                    "content": "周末定价权大重估<font class=\"important-text\"></font>",
                    "source_link": "",
                },
            }]
        }

        items = parse_jin10_items(payload)

        self.assertEqual(items[0]["title"], "CME补上周末交易")
        self.assertEqual(items[0]["description"], "周末定价权大重估")
        self.assertEqual(items[0]["link"], "https://flash.jin10.com/detail/20260612233021430800")
        self.assertEqual(items[0]["guid"], "jin10_20260612233021430800")

    def test_handle_cls_hotplate_returns_three_plate_keys(self):
        result = handle_cls_hotplate()
        for key in ('plate_industry', 'plate_concept', 'plate_area'):
            self.assertIn(key, result)
            self.assertIsInstance(result[key], dict)

    def test_handle_cls_hotplate_includes_hot_plates(self):
        result = handle_cls_hotplate()
        self.assertIn('hot_plates', result)
        self.assertIsInstance(result['hot_plates'], list)
        self.assertEqual(len(result['hot_plates']), 6)

    def test_handle_cls_plate_returns_info_stocks_industry(self):
        result = handle_cls_plate('cls80484')
        self.assertEqual(result['code'], 'cls80484')
        self.assertIn('info', result)
        self.assertIsInstance(result['info'], dict)
        self.assertIn('stocks', result)
        self.assertIsInstance(result['stocks'], list)
        self.assertIn('industry', result)
        self.assertIsInstance(result['industry'], list)

    def test_healthz_payload_includes_hotplate_endpoint(self):
        payload = build_health_payload("https://feeds.example.com")
        paths = {f['path'] for f in payload['feeds']}
        self.assertIn('/cls/hotplate', paths)

    def test_parse_wallstreetcn_items_prefers_plain_text_content(self):
        payload = {
            "data": {
                "items": [{
                    "id": 3118981,
                    "title": "意大利银行板块收涨超3%",
                    "content": "<p>德国DAX 30指数初步收涨1.66%。</p>",
                    "content_text": "德国DAX 30指数初步收涨1.66%。",
                    "display_time": 1781278243,
                    "uri": "https://wallstreetcn.com/livenews/3118981",
                }]
            }
        }

        items = parse_wallstreetcn_items(payload)

        self.assertEqual(items[0]["title"], "意大利银行板块收涨超3%")
        self.assertEqual(items[0]["description"], "德国DAX 30指数初步收涨1.66%。")
        self.assertEqual(items[0]["link"], "https://wallstreetcn.com/livenews/3118981")
        self.assertEqual(items[0]["guid"], "wallstreetcn_3118981")


class MarketApiTests(unittest.TestCase):
    """Tests for market-level APIs (融资融券).

    Transform functions are unit-tested; handlers rely on fetch_json caching.
    """

    def test_transform_margin_parses_raw_data(self):
        raw = {
            'date': ['2026-07-13', '2026-07-14'],
            'item': [
                {'rzye': 14800000000, 'rqye': 120000000, 'rzmre': 8000000000,
                 'rzjmr': 500000000, 'rqjmc': -10000000, 'lr': 14920000000, 'zb': 0.45},
                {'rzye': 14900000000, 'rqye': 115000000, 'rzmre': 7500000000,
                 'rzjmr': 400000000, 'rqjmc': -5000000, 'lr': 15015000000, 'zb': 0.46},
            ],
        }
        result = _transform_margin(raw)
        self.assertIsNotNone(result['latest'])
        self.assertEqual(result['latest']['date'], '2026-07-14')
        self.assertAlmostEqual(result['latest']['rzye'], 149.0, places=3)
        self.assertAlmostEqual(result['latest']['lr'], 150.15, places=3)
        self.assertEqual(len(result['recent']), 2)

    def test_transform_margin_handles_missing_data(self):
        self.assertEqual(_transform_margin({}),
                         {'latest': None, 'recent': []})
        self.assertEqual(_transform_margin({'date': [], 'item': []}),
                         {'latest': None, 'recent': []})

    def test_transform_margin_to_100m_converts_correctly(self):
        raw = {
            'date': ['2026-07-14'],
            'item': [{'rzye': 15000000000, 'rqye': None, 'rzmre': '--',
                      'rzjmr': 0, 'rqjmc': -5000000, 'lr': 15000000000, 'zb': 0.42}],
        }
        result = _transform_margin(raw)
        self.assertAlmostEqual(result['latest']['rzye'], 150.0, places=3)
        self.assertEqual(result['latest']['rqye'], 0.0)  # None → 0
        self.assertEqual(result['latest']['rzmre'], 0.0)  # '--' → 0
        self.assertAlmostEqual(result['latest']['rqjmc'], -0.05, places=4)

    def test_handle_margin_invalid_market_degrades_without_network(self):
        # P1-1: `market` is a contract enum ('99','1','2','3'); any other value
        # is rejected before the URL is built — no upstream call, no cache key.
        with patch('china_finance_rss.market_api.fetch_json') as mocked:
            result = handle_margin('invalid')
        mocked.assert_not_called()
        self.assertEqual(result['_error'], 'upstream_error')
        self.assertEqual(result['latest']['rzye'], 0)
        self.assertEqual(result['latest']['rqye'], 0)

    def test_healthz_includes_market_endpoints(self):
        payload = build_health_payload("https://feeds.example.com")
        paths = {f['path'] for f in payload['feeds']}
        self.assertIn('/market/margin', paths)


class CacheMaintenanceTests(unittest.TestCase):
    """Tests for expired-cache reclamation fixes (2c2g memory issue)."""

    def test_sweep_expired_removes_stale_entries(self):
        from china_finance_rss.cache import _sweep_expired
        import time
        cache_dict = {
            'fresh': {'data': 'x', 'time': time.time(),
                      'expires_at': time.time() + 100},
            'stale': {'data': 'y', 'time': time.time() - 1000,
                      'expires_at': time.time() - 500},
            'none': None,
        }
        removed = _sweep_expired(cache_dict)
        self.assertEqual(removed, 1)
        self.assertIn('fresh', cache_dict)
        self.assertNotIn('stale', cache_dict)
        self.assertIn('none', cache_dict)  # None entries are kept (handled on read)

    def test_sector_cache_bounded(self):
        from china_finance_rss.stock_api import _sector_cache, _sector_cache_lock, \
            _sector_cache_put
        from china_finance_rss.config import cache_policy
        import time
        cap = cache_policy('sector')['cache_max']
        with _sector_cache_lock:
            saved = dict(_sector_cache)
        try:
            now = time.time()
            for i in range(cap + 50):
                _sector_cache_put(f'test{i:05d}', '测试', now=now - i)
            with _sector_cache_lock:
                self.assertLessEqual(len(_sector_cache), cap)
        finally:
            with _sector_cache_lock:
                _sector_cache.clear()
                _sector_cache.update(saved)

    def test_sector_cache_ttl_eviction(self):
        from china_finance_rss.stock_api import _sector_cache, _sector_cache_lock, _sweep_sector_cache
        import time
        with _sector_cache_lock:
            saved = dict(_sector_cache)
            try:
                old_ts = time.time() - 8 * 24 * 3600  # older than 7-day TTL
                _sector_cache['ttl_old'] = {'sector': '旧', 'ts': old_ts}
                _sweep_sector_cache()
                self.assertNotIn('ttl_old', _sector_cache)
            finally:
                _sector_cache.clear()
                _sector_cache.update(saved)

    def test_fetch_json_leader_failure_does_not_stampede(self):
        """AR-10 / T-CACHE-2 new semantics: the elected leader's upstream
        failure writes a URL-level negative-cache entry; waiting followers read
        it and raise without touching upstream (no re-election, no stampede)."""
        import time as _time
        import urllib.error
        from collections import OrderedDict
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from unittest import mock
        import china_finance_rss.cache as cache_mod

        class _FakeResponse:
            def __init__(self, body):
                self._body = body
                self.status = 200

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        tracked = ('cache', '_negative', '_fetch_inflight', '_cache_stats',
                   '_last_cache_sweep')
        original = {k: getattr(cache_mod, k) for k in tracked}

        state = {'active': 0, 'max_active': 0, 'calls': 0}

        def flaky_urlopen(req, timeout=None):
            state['active'] += 1
            state['max_active'] = max(state['max_active'], state['active'])
            state['calls'] += 1
            try:
                # Hold the leader long enough that every follower parks on the
                # per-URL Event before the failure is recorded.
                _time.sleep(0.1)
                raise urllib.error.URLError('boom')
            finally:
                state['active'] -= 1

        try:
            cache_mod.cache = OrderedDict()
            cache_mod._negative = {}
            cache_mod._fetch_inflight = {}
            cache_mod._cache_stats = {'hit': 0, 'miss': 0}
            cache_mod._last_cache_sweep = 0.0
            with mock.patch.object(cache_mod, 'urlopen', side_effect=flaky_urlopen):
                outcomes = {'ok': 0, 'err': 0}
                with ThreadPoolExecutor(max_workers=8) as pool:
                    futures = [pool.submit(
                        cache_mod.fetch_json, 'http://example.test/x', None, 60)
                        for _ in range(8)]
                    for f in as_completed(futures):
                        try:
                            f.result()
                            outcomes['ok'] += 1
                        except Exception:
                            outcomes['err'] += 1
            # Leader + 7 followers all fail fast from the shared negative entry.
            self.assertEqual(outcomes['err'], 8)
            self.assertEqual(outcomes['ok'], 0)
            # Single-flight guarantee: never more than 1 upstream request in
            # flight, and the leader's failure is the only upstream call.
            self.assertEqual(state['max_active'], 1)
            self.assertEqual(state['calls'], 1)
            self.assertIn('http://example.test/x', cache_mod._negative)
        finally:
            for k, v in original.items():
                setattr(cache_mod, k, v)

    def test_prefetch_loop_advances_cursor_across_passes(self):
        """T1 / S1-2: fairness must hold through the REAL prefetch loop.

        The previous version hand-fed `_prefetch_advance`, so the production
        counting semantics (`_prefetch_advance(name, visited, len(codes))`) were
        never exercised — exactly the path where codes that were *visited* but
        returned no data failed to advance the cursor, so the head was
        re-fetched every pass and the pool tail was permanently starved.
        """
        import threading
        from collections import OrderedDict
        import time as _time
        from china_finance_rss import stock_api

        class _Stop(BaseException):
            pass

        codes = [f'sh{600000 + i}' for i in range(6)]
        pool = {c: _time.time() for c in codes}
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
            if cycles['n'] > 3:
                raise _Stop()

        with stock_api._prefetch_cursor_lock:
            stock_api._prefetch_cursor.clear()
        try:
            with patch.object(stock_api, 'sleep', side_effect=_sleep), \
                 patch.object(stock_api, 'time', new=lambda: clock['t']), \
                 patch.object(stock_api, '_PREFETCH_PASS_BUDGET', 2.0):
                with self.assertRaises(_Stop):
                    stock_api._prefetch_loop('fundflow', 'fundflow', _fetch, pool,
                                             OrderedDict(), {}, threading.Lock())
        finally:
            with stock_api._prefetch_cursor_lock:
                stock_api._prefetch_cursor.clear()
        self.assertEqual(set(seen), set(codes))   # the pool tail is reached


if __name__ == "__main__":
    unittest.main()
