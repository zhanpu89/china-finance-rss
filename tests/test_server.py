import unittest
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from utils import (
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
from server import ROUTES, handle_cls_hotplate, build_health_payload
from market_api import (
    _transform_margin, _transform_northbound,
    handle_margin, handle_northbound, handle_northbound_history,
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
    """Tests for market-level APIs (融资融券, 北向资金).

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

    def test_transform_northbound_parses_snapshot(self):
        raw = {
            'h': {'zjlr': 2500000000, 'syed': 30000000000, 'zed': 52000000000,
                  'buy_turnover': 18000000000, 'sell_turnover': 15500000000,
                  'net_turnover': 2500000000, 'state': '开盘', 'up': 500, 'mid': 300, 'down': 200},
            's': {'zjlr': -500000000, 'syed': 48000000000, 'zed': 52000000000,
                  'buy_turnover': 12000000000, 'sell_turnover': 12500000000,
                  'net_turnover': -500000000, 'state': '开盘', 'up': 200, 'mid': 400, 'down': 600},
            'jlr': 2000000000,
            'jmr': 1800000000,
            'market_value': {'data_update_date': '2026-07-14', 'unit': '元'},
        }
        result = _transform_northbound(raw)
        self.assertEqual(result['sh']['net_inflow'], 2500000000)
        self.assertEqual(result['sz']['net_inflow'], -500000000)
        self.assertEqual(result['total_net_inflow'], 2000000000)
        self.assertEqual(result['total_net_buy'], 1800000000)
        self.assertEqual(result['update_date'], '2026-07-14')

    def test_transform_northbound_handles_empty_data(self):
        result = _transform_northbound({})
        self.assertEqual(result['sh']['net_inflow'], 0)
        self.assertEqual(result['sz']['net_inflow'], 0)
        self.assertEqual(result['total_net_inflow'], 0)

    def test_handle_margin_error_returns_degraded(self):
        # Pass an invalid market code → API returns error → degraded response
        result = handle_margin('invalid')
        self.assertIn('_error', result)
        self.assertEqual(result['latest']['rzye'], 0)
        self.assertEqual(result['latest']['rqye'], 0)

    def test_handle_northbound_returns_unified_structure(self):
        result = handle_northbound()
        for key in ('sh', 'sz', 'total_net_inflow', 'total_net_buy'):
            self.assertIn(key, result)
        for loc in ('sh', 'sz'):
            self.assertIn('net_inflow', result[loc])
            self.assertIn('buy_turnover', result[loc])
            self.assertIn('sell_turnover', result[loc])

    def test_handle_northbound_history_returns_dict(self):
        result = handle_northbound_history('day')
        self.assertIsInstance(result, dict)

    def test_healthz_includes_market_endpoints(self):
        payload = build_health_payload("https://feeds.example.com")
        paths = {f['path'] for f in payload['feeds']}
        self.assertIn('/market/margin', paths)
        self.assertIn('/market/northbound', paths)
        self.assertIn('/market/northbound/history', paths)


if __name__ == "__main__":
    unittest.main()
