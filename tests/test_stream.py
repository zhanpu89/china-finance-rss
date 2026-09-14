import http.client
import threading
import unittest
from unittest.mock import patch

import config
from server import BoundedThreadPoolServer
from stream import (
    StreamHandler, _groups,
    create_group, get_group, patch_group, destroy_group,
    _valid_fields, _build_frame, _refresh_pool, _broadcast, tick_interval,
)


def setUpModule():
    """Isolate subscription groups between test modules."""
    _groups.clear()


class SubscriptionGroupTests(unittest.TestCase):
    def tearDown(self):
        _groups.clear()

    def test_create_group_valid_codes_and_fields(self):
        sid, err = create_group(['sh600519', 'sz000001', 'sh600519'], ['quote', 'fundflow'])
        self.assertIsNone(err)
        g = get_group(sid)
        self.assertIsNotNone(g)
        # dedupe within a group
        self.assertEqual(g.codes, {'sh600519', 'sz000001'})
        self.assertEqual(g.fields, ['quote', 'fundflow'])

    def test_create_group_rejects_invalid_code(self):
        sid, err = create_group(['sh600519', 'notacode'], None)
        self.assertIsNone(sid)
        self.assertIn('invalid stock code', err)

    def test_create_group_requires_codes(self):
        sid, err = create_group([], None)
        self.assertIsNone(sid)
        self.assertEqual(err, 'codes required')

    def test_create_group_enforces_per_group_limit(self):
        codes = [f'sh{i:06d}' for i in range(config.MAX_CODES_PER_SUB + 1)]
        sid, err = create_group(codes, None)
        self.assertIsNone(sid)
        self.assertIn('too many codes', err)

    def test_create_group_enforces_deduped_pool_limit(self):
        import stream as stream_mod
        with patch.object(stream_mod, 'MAX_DEDUP_CODES', 3):
            _, err = create_group(['sh600519', 'sz000001', 'sh600000'], None)
            self.assertIsNone(err)
            sid, err = create_group(['sz000002'], None)
            self.assertIsNone(sid)
            self.assertIn('pool would exceed', err)

    def test_patch_group_add_remove(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        ok, err = patch_group(sid, add=['sz000001'], remove=['sh600519'])
        self.assertTrue(ok)
        self.assertIsNone(err)
        g = get_group(sid)
        self.assertEqual(g.codes, {'sz000001'})

    def test_patch_group_rejects_invalid_code(self):
        sid, _ = create_group(['sh600519'], None)
        ok, err = patch_group(sid, add=['bad'], remove=[])
        self.assertFalse(ok)
        self.assertIn('invalid stock code', err)

    def test_patch_unknown_group(self):
        ok, err = patch_group('nope', add=['sh600519'], remove=[])
        self.assertFalse(ok)
        self.assertEqual(err, 'subscription not found')

    def test_destroy_group(self):
        sid, _ = create_group(['sh600519'], None)
        self.assertTrue(destroy_group(sid))
        self.assertFalse(destroy_group(sid))
        self.assertIsNone(get_group(sid))


class FieldAndFrameTests(unittest.TestCase):
    def test_valid_fields_defaults_to_all(self):
        self.assertEqual(_valid_fields(None), ['quote', 'fundflow', 'timeline'])
        self.assertEqual(_valid_fields([]), ['quote', 'fundflow', 'timeline'])

    def test_valid_fields_filters_unknown(self):
        self.assertEqual(_valid_fields(['quote', 'nonsense']), ['quote'])

    def test_build_frame_maps_only_group_fields(self):
        g = create_group(['sh600519'], ['quote'])[0]
        from stream import SubscriptionGroup
        # rebuild group directly with a specific field set for clarity
        _groups.clear()
        _groups[g] = SubscriptionGroup(g, {'sh600519'}, ['quote', 'timeline'])
        frame = _build_frame(
            {'sh600519': {'quote': {'name': '贵州茅台'},
                          'fundflow': {'net': 1},
                          'timeline': [{'price': 1700}]}},
            _groups[g])
        import json
        data = json.loads(frame)
        self.assertIn('quote', data['items']['sh600519'])
        self.assertIn('timeline', data['items']['sh600519'])
        self.assertNotIn('fundflow', data['items']['sh600519'])

    def test_build_frame_skips_codes_missing_from_snapshot(self):
        from stream import SubscriptionGroup
        _groups.clear()
        g = SubscriptionGroup('sid_x', {'sh600519'}, ['quote'])
        frame = _build_frame({'sz000001': {'quote': {}}}, g)
        self.assertIsNone(frame)

    def test_tick_interval_follows_l1_tier(self):
        with patch('stream._trading_tiers', return_value={'L1': 8, 'L2': 12}):
            self.assertEqual(tick_interval(), 8)


class HttpIntegrationTests(unittest.TestCase):
    """Real HTTP server on an ephemeral port; one manual push cycle."""

    @classmethod
    def setUpClass(cls):
        _groups.clear()
        cls.srv = BoundedThreadPoolServer(('', 0), StreamHandler, max_workers=4)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        _groups.clear()

    def _http(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Content-Type': 'application/json'} if body else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        payload = resp.read().decode('utf-8')
        conn.close()
        return resp.status, payload

    def test_subscription_crud_over_http(self):
        status, payload = self._http(
            'POST', '/stream/subscriptions', '{"codes":["sh600519"],"fields":["quote"]}')
        self.assertEqual(status, 201)
        import json
        sid = json.loads(payload)['sid']

        status, payload = self._http('GET', f'/stream/subscriptions/{sid}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)['codes'], ['sh600519'])

        status, payload = self._http(
            'PATCH', f'/stream/subscriptions/{sid}', '{"add":["sz000001"]}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)['codes'], ['sh600519', 'sz000001'])

        status, payload = self._http('DELETE', f'/stream/subscriptions/{sid}')
        self.assertEqual(status, 200)
        self.assertIsNone(get_group(sid))

    def test_post_rejects_invalid_body(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        conn.request('POST', '/stream/subscriptions', body='not json',
                     headers={'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()

    def test_sse_stream_receives_quote_frame(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        conn.request('GET', f'/stream/quote/{sid}')
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader('Content-Type'), 'text/event-stream')
        self.assertEqual(resp.getheader('Cache-Control'), 'no-cache')

        with patch.dict('stream._FIELD_HANDLERS',
                        {'quote': lambda codes: {'sh600519': {'name': '贵州茅台'}}}):
            snapshot = _refresh_pool(['sh600519'])
            _broadcast(snapshot)

        event_line = resp.readline().decode('utf-8').strip()
        self.assertEqual(event_line, 'event: quote')
        id_line = resp.readline().decode('utf-8').strip()
        self.assertTrue(id_line.startswith('id: '))
        data_line = resp.readline().decode('utf-8').strip()
        self.assertTrue(data_line.startswith('data: '))
        resp.readline()  # 空行结束该事件
        import json as _json
        payload = _json.loads(data_line[6:])
        self.assertEqual(payload['items']['sh600519']['quote']['name'], '贵州茅台')
        conn.close()

    def test_sse_stream_unknown_group_returns_404(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        conn.request('GET', '/stream/quote/nosuchgroup')
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()


class BatchShardingTests(unittest.TestCase):
    """P1-6 regression: _handle_cached_batch must shard, not truncate.

    stream._refresh_pool hands the whole deduped pool (up to
    MAX_DEDUP_CODES) to the quote handler. If that handler silently
    dropped codes beyond _MAX_BATCH_SIZE, frames would lose stocks.
    This test drives the REAL handler (handle_cls_basic_infos — the
    exact one bound to _FIELD_HANDLERS['quote']) with 60 codes and
    asserts every code comes back.
    """

    def test_60_codes_all_fetched_and_returned_beyond_max_batch(self):
        import stock_api as stock_api_mod

        codes = [f'sh{990000 + i}' for i in range(60)]
        self.assertGreater(len(codes), config._MAX_BATCH_SIZE)

        fake_data = {c: {'name': f'股{c}'} for c in codes}
        with stock_api_mod._basic_info_cache_lock:
            saved = (dict(stock_api_mod._basic_info_cache),
                     dict(stock_api_mod._basic_info_cache_ts),
                     dict(stock_api_mod._basic_info_pool))
        try:
            seen = set()

            def _fake_fetch(code):
                seen.add(code)
                return fake_data.get(code)

            with patch.object(stock_api_mod, 'fetch_cls_basic_info',
                              side_effect=_fake_fetch):
                result = stock_api_mod.handle_cls_basic_infos(codes)

            # (a) full coverage: every code key present — sharded, not truncated
            self.assertEqual(set(result), set(codes))
            self.assertEqual(len(result), len(codes))
            # sharding proof: the fetcher was actually asked for all 60 codes
            # across both chunks, not just the merge surviving
            self.assertEqual(seen, set(codes))
            # (b) every code got (fake) data back
            for c in codes:
                self.assertEqual(result[c], fake_data[c])
        finally:
            with stock_api_mod._basic_info_cache_lock:
                stock_api_mod._basic_info_cache.clear()
                stock_api_mod._basic_info_cache_ts.clear()
                stock_api_mod._basic_info_pool.clear()
                stock_api_mod._basic_info_cache.update(saved[0])
                stock_api_mod._basic_info_cache_ts.update(saved[1])
                stock_api_mod._basic_info_pool.update(saved[2])


def _json(resp):
    import json
    return json.loads(resp.read().decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
