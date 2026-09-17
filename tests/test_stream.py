import http.client
import json
import queue
import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch

from china_finance_rss import cdp_engine as cdp_engine
from china_finance_rss import config as config
from china_finance_rss.server import BoundedThreadPoolServer
from china_finance_rss.stream import (
    StreamHandler, _SSEConn, _Frame, _groups,
    create_group, get_group, patch_group, destroy_group,
    _valid_fields, _build_frame, _refresh_pool, _broadcast, tick_interval,
    _deduped_codes, _active_codes, _sweep_idle_groups,
    _frame_acquire, _frame_release, _drain_conn_queue, _pop_oldest_frame,
    _reserve_for, _release_conn, _projected_frame_bytes_unlocked,
    refresh_capacity, _fetches_per_code, _tick_sleep_seconds,
    _subscribed_fields, _subscribed_fields_unlocked, _active_targets,
    _resolve_refresh_fields,
)
import china_finance_rss.stream as stream_mod


def setUpModule():
    """Isolate subscription groups between test modules."""
    _groups.clear()


def _reset_frame_accounting():
    """Zero out distinct-frame billing (tests enqueue raw _Frame objects)."""
    stream_mod._queue_bytes = 0
    stream_mod._group_bytes.clear()
    stream_mod._live_frames = 0
    stream_mod._frame_peak_bytes = 0


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
        # BR-STR-1: fields is an immutable tuple (was list)
        self.assertEqual(g.fields, ('quote', 'fundflow'))

    def test_create_group_rejects_invalid_code(self):
        sid, err = create_group(['sh600519', 'notacode'], None)
        self.assertIsNone(sid)
        self.assertIn('invalid stock code', err)

    def test_create_group_normalizes_case_whitespace_and_dedupes(self):
        """S2-4b: SH600519 / sh600519 / trailing newline → one canonical code."""
        sid, err = create_group(['SH600519', 'sh600519', '  sz000001\n'],
                                ['quote'])
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sh600519', 'sz000001'})

    def test_dotted_spelling_is_the_same_stock_as_the_prefixed_one(self):
        """P1-6: `600519.SH` used to be stored as a *third* identity next to
        `sh600519` (the local regex only lower-cased), so one stock minted two
        pool entries and two upstream fetches.  `config.canonical_code` is the
        single authority and folding happens before dedup."""
        sid, err = create_group(['600519.SH', 'SH600519', 'sh600519'], ['quote'])
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sh600519'})
        self.assertEqual(_deduped_codes(), {'sh600519'})

    def test_dotted_spelling_is_stored_canonically(self):
        sid, err = create_group(['000001.SZ', '430047.BJ'], ['quote'])
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sz000001', 'bj430047'})

    def test_trailing_newline_folds_onto_the_same_code(self):
        """The ``$``-anchored regex accepts a trailing newline; the authority
        strips first, so it becomes the same code instead of a second one."""
        sid, err = create_group(['sh600519\n', 'sh600519'], None)
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sh600519'})

    def test_invalid_spellings_are_rejected(self):
        """Invalid code (``canonical_code`` → ``None``) ⇒ 400, no group."""
        for bad in ('600519.XX', 'sh60051', '600519.SH.SH', 'sh 600519',
                    'sh600519.SZ', ''):
            sid, err = create_group(['sh600519', bad], None)
            self.assertIsNone(sid, bad)
            self.assertIn('invalid stock code', err, bad)

    def test_stream_has_no_local_code_validator(self):
        """Anti-regression (P1-6): identity folding lives in config only — a
        second regex/local normaliser here would drift again."""
        import inspect
        src = inspect.getsource(stream_mod)
        self.assertNotIn('VALID_STOCK_CODE', src)
        self.assertNotIn('_normalize_code', src)

    def test_create_group_rejects_unknown_fields(self):
        """S2-4: explicit unknown field ⇒ error, never silently all-3."""
        sid, err = create_group(['sh600519'], ['nonsense'])
        self.assertIsNone(sid)
        self.assertIn('unknown field', err)

    def test_create_group_without_fields_defaults_to_all(self):
        sid, err = create_group(['sh600519'], None)
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).fields,
                         ('quote', 'fundflow', 'timeline'))

    def test_create_group_rejects_non_string_code(self):
        sid, err = create_group([600519], None)
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
        import china_finance_rss.stream as stream_mod
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

    def test_patch_reads_group_under_the_same_lock(self):
        """S2-4d: patch no longer uses the unlocked get_group (destroy race)."""
        sid, _ = create_group(['sh600519'], ['quote'])
        with patch.object(stream_mod, 'get_group',
                          side_effect=AssertionError('unlocked read')):
            ok, err = patch_group(sid, add=['sz000001'], remove=[])
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sh600519', 'sz000001'})

    def test_patch_normalizes_codes(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        ok, err = patch_group(sid, add=['SZ000001'], remove=['SH600519'])
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sz000001'})

    def test_patch_matches_a_dotted_spelling_to_the_stored_code(self):
        """P1-6: `remove=['600519.SH']` must hit the stored `sh600519`."""
        sid, _ = create_group(['sh600519'], ['quote'])
        ok, err = patch_group(sid, add=['000001.SZ'], remove=['600519.SH'])
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(get_group(sid).codes, {'sz000001'})

    def test_patch_rejects_invalid_dotted_spelling(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        ok, err = patch_group(sid, add=['600519.XX'], remove=[])
        self.assertFalse(ok)
        self.assertIn('invalid stock code', err)
        self.assertEqual(get_group(sid).codes, {'sh600519'})

    def test_destroy_group(self):
        sid, _ = create_group(['sh600519'], None)
        self.assertTrue(destroy_group(sid))
        self.assertFalse(destroy_group(sid))
        self.assertIsNone(get_group(sid))


class FieldAndFrameTests(unittest.TestCase):
    def test_valid_fields_defaults_to_all(self):
        self.assertEqual(_valid_fields(None), ['quote', 'fundflow', 'timeline'])
        self.assertEqual(_valid_fields([]), ['quote', 'fundflow', 'timeline'])

    def test_valid_fields_accepts_known_subset(self):
        self.assertEqual(_valid_fields(['quote', 'fundflow']),
                         ['quote', 'fundflow'])

    def test_valid_fields_rejects_unknown_fail_closed(self):
        """S2-4: an explicit unknown field is an error, never widened to all 3."""
        with self.assertRaises(ValueError):
            _valid_fields(['quote', 'nonsense'])
        with self.assertRaises(ValueError):
            _valid_fields(['nonsense'])

    def test_build_frame_maps_only_group_fields(self):
        g = create_group(['sh600519'], ['quote'])[0]
        from china_finance_rss.stream import SubscriptionGroup
        # rebuild group directly with a specific field set for clarity
        _groups.clear()
        _groups[g] = SubscriptionGroup(g, {'sh600519'}, ['quote', 'timeline'])
        grp = _groups[g]
        # signature change: _build_frame(snapshot, codes, fields)
        frame = _build_frame(
            {'sh600519': {'quote': {'name': '贵州茅台'},
                          'fundflow': {'net': 1},
                          'timeline': [{'price': 1700}]}},
            grp.codes, grp.fields)
        data = json.loads(frame)
        self.assertIn('quote', data['items']['sh600519'])
        self.assertIn('timeline', data['items']['sh600519'])
        self.assertNotIn('fundflow', data['items']['sh600519'])

    def test_build_frame_covers_every_subscribed_code(self):
        """S2-1: a true full snapshot — absent codes appear with null fields and
        are listed in `missing`, never silently omitted (the old frame dropped
        them entirely, so a C2 tick looked complete while covering only the
        sharded slice)."""
        from china_finance_rss.stream import SubscriptionGroup
        _groups.clear()
        g = SubscriptionGroup('sid_x', {'sh600519', 'sz000001'}, ['quote'])
        frame = _build_frame({'sh600519': {'quote': {'name': 'x'}}},
                             g.codes, g.fields)
        data = json.loads(frame)
        self.assertEqual(set(data['items']), {'sh600519', 'sz000001'})
        self.assertIsNone(data['items']['sz000001']['quote'])   # explicit no-data
        self.assertEqual(data['codes_total'], 2)
        self.assertEqual(data['fields'], ['quote'])
        self.assertEqual(data['missing'], ['sz000001'])
        self.assertEqual(data['missing_count'], 1)

    def test_build_frame_returns_none_only_without_codes(self):
        self.assertIsNone(_build_frame({}, frozenset(), ('quote',)))

    def test_tick_interval_follows_l1_tier_when_no_subscription(self):
        with patch('china_finance_rss.stream._trading_tiers', return_value={'L0': 4, 'L1': 8, 'L2': 12}):
            self.assertEqual(tick_interval(), 8)          # no fields ⇒ L1 baseline
            self.assertEqual(tick_interval([]), 8)

    def test_tick_interval_is_the_fastest_subscribed_domain(self):
        """任务 1b: a quote subscription pushes at L0 (4s); fundflow/timeline
        stay on L1 (8s); a mixed set takes the minimum."""
        with patch('china_finance_rss.stream._trading_tiers',
                   return_value={'L0': 4, 'L1': 8, 'L2': 12}):
            self.assertEqual(tick_interval(['quote']), 4)
            self.assertEqual(tick_interval(['fundflow']), 8)
            self.assertEqual(tick_interval(['timeline']), 8)
            self.assertEqual(tick_interval(['fundflow', 'timeline']), 8)
            self.assertEqual(tick_interval(['quote', 'fundflow']), 4)
            self.assertEqual(tick_interval(['quote', 'fundflow', 'timeline']), 4)
            # unknown fields don't crash and don't speed the cadence up
            self.assertEqual(tick_interval(['nope']), 8)


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

    def test_post_rejects_unknown_fields(self):
        """S2-4: fields=["nonsense"] is a 400, not a silent 3-domain widening."""
        status, payload = self._http(
            'POST', '/stream/subscriptions',
            '{"codes":["sh600519"],"fields":["nonsense"]}')
        self.assertEqual(status, 400)
        self.assertIn('unknown field', json.loads(payload)['error'])

    def test_post_without_fields_defaults_to_all(self):
        status, payload = self._http(
            'POST', '/stream/subscriptions', '{"codes":["sh600519"]}')
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(payload)['fields'],
                         ['quote', 'fundflow', 'timeline'])

    def test_post_rejects_non_list_codes(self):
        """P1-2: `{"codes":123}` must be a 400, not a TypeError that escapes the
        handler and resets the connection."""
        status, payload = self._http(
            'POST', '/stream/subscriptions', '{"codes":123}')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(payload)['error'], 'codes must be a list')

    def test_post_rejects_non_object_body(self):
        status, payload = self._http('POST', '/stream/subscriptions', '[1,2]')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(payload)['error'],
                         'JSON body must be an object')

    def test_patch_rejects_non_list_add_and_remove(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        status, payload = self._http(
            'PATCH', f'/stream/subscriptions/{sid}', '{"add":true}')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(payload)['error'], 'add must be a list')
        status, payload = self._http(
            'PATCH', f'/stream/subscriptions/{sid}', '{"remove":123}')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(payload)['error'], 'remove must be a list')
        # no partial mutation leaked from either rejected request
        self.assertEqual(get_group(sid).codes, {'sh600519'})

    def test_create_reports_refresh_capacity_when_oversubscribed(self):
        """P1-4: a legal 200-code × 3-field subscription must carry a capacity
        signal in the 201 response (coverage_codes=106 ⇒ lag=2 ticks, with quote
        priced as basic + depth)."""
        codes = [f'sh{600000 + i:06d}' for i in range(config.MAX_CODES_PER_SUB)]
        with patch.object(stream_mod, 'tick_interval', return_value=8):
            status, payload = self._http(
                'POST', '/stream/subscriptions',
                json.dumps({'codes': codes,
                            'fields': ['quote', 'fundflow', 'timeline']}))
        self.assertEqual(status, 201)
        data = json.loads(payload)
        self.assertEqual(data['refresh_capacity_codes'], 106)
        self.assertEqual(data['refresh_lag_ticks'], -(-200 // 106))
        self.assertIn('capacity_warning', data)

    def test_create_reports_capacity_without_warning_when_it_fits(self):
        with patch.object(stream_mod, 'tick_interval', return_value=8):
            status, payload = self._http(
                'POST', '/stream/subscriptions',
                '{"codes":["sh600519"],"fields":["quote"]}')
        self.assertEqual(status, 201)
        data = json.loads(payload)
        self.assertEqual(data['refresh_capacity_codes'], 213)   # basic + depth
        self.assertNotIn('capacity_warning', data)

    def test_sse_stream_receives_quote_frame(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        try:
            conn.request('GET', f'/stream/quote/{sid}')
            resp = conn.getresponse()
            try:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.getheader('Content-Type'), 'text/event-stream')
                self.assertEqual(resp.getheader('Cache-Control'), 'no-cache')

                with patch.dict('china_finance_rss.stream._FIELD_HANDLERS',
                                {'quote': lambda codes, deadline=None:
                                 {'sh600519': {'name': '贵州茅台'}}}):
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
            finally:
                # The server advertises `Connection: close`, so will_close=True and
                # HTTPConnection.getresponse() calls close() *before* binding the
                # response to __response — the response (and the socket's makefile
                # ref, _io_refs) is orphaned.  conn.close() alone is therefore a
                # no-op and the raw socket fd leaks until GC (ResourceWarning).
                resp.close()
        finally:
            conn.close()

    def test_sse_stream_unknown_group_returns_404(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        conn.request('GET', '/stream/quote/nosuchgroup')
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()


class StreamHandlerRobustnessTests(unittest.TestCase):
    """P2: management handlers tolerate a destroy racing the mutation."""

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    def test_patch_response_is_404_when_group_vanished(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        handler = StreamHandler.__new__(StreamHandler)
        handler.path = f'/stream/subscriptions/{sid}'
        handler._read_json_body = lambda: {'add': ['sz000001']}
        sent = []
        handler._send_json = lambda status, obj: sent.append((status, obj))
        with patch.object(stream_mod, 'get_group', return_value=None):
            handler.do_PATCH()               # must not raise AttributeError
        self.assertEqual(sent, [(404, {'error': 'subscription not found'})])


class Stream503AccountingTests(unittest.TestCase):
    """P2: the stream conn-limit 503 feeds the global http_503_total."""

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    def test_conn_limit_503_is_counted(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        handler = StreamHandler.__new__(StreamHandler)
        sent = []
        handler._send_json = lambda status, obj: sent.append((status, obj))
        before = stream_mod.metrics.snapshot()['http_503_total']
        with patch.object(stream_mod, '_register_conn', return_value=False):
            handler._serve_sse(sid)
        after = stream_mod.metrics.snapshot()['http_503_total']
        self.assertEqual(sent,
                         [(503, {'error': 'too many stream connections'})])
        self.assertEqual(after, before + 1)


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
        import china_finance_rss.stock_api as stock_api_mod

        codes = [f'sh{990000 + i}' for i in range(60)]
        self.assertGreater(len(codes), config._MAX_BATCH_SIZE)

        fake_data = {c: {'name': f'股{c}'} for c in codes}
        with stock_api_mod._basic_info_cache_lock:
            saved = (dict(stock_api_mod._basic_info_cache),
                     dict(stock_api_mod._basic_info_cache_ts),
                     dict(stock_api_mod._basic_info_pool))
        try:
            seen = set()

            def _fake_fetch(code, deadline=None, ttl=None):
                # Must mirror the production fetcher signature: this double is
                # wrapped in a MagicMock (patch.object side_effect), so a
                # signature mismatch raises inside the mock call frames and
                # _call_fetcher correctly re-raises it as a body error (P2-④).
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


class SSEQueueDropTests(unittest.TestCase):
    """P2-1 / BR-STR-10: on a full bounded queue _broadcast drops the OLDEST
    frame and keeps the NEWEST ("L1 tick drops frames — next tick
    overwrites"): a lagging client recovers onto the latest quote."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    def test_broadcast_on_full_queue_drops_oldest_keeps_newest(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        g = get_group(sid)
        conn = _SSEConn()
        with g.conns_lock:
            g.conns.add(conn)
        for i in range(8):  # maxsize=8 => now full, oldest = frame-0
            f = _Frame(f'frame-{i}', sid)
            conn.q.put_nowait(f)
            _frame_acquire(f)

        _broadcast({'sh600519': {'quote': {'name': '最新价'}}})

        items = list(conn.q.queue)
        self.assertEqual(len(items), 8)            # still bounded at maxsize
        payloads = [f.payload for f in items if isinstance(f, _Frame)]
        self.assertNotIn('frame-0', payloads)      # OLDEST dropped
        self.assertIn('frame-7', payloads)         # second-newest preserved
        newest = [f for f in items
                  if isinstance(f, _Frame) and not f.payload.startswith('frame-')]
        self.assertEqual(len(newest), 1)           # exactly the new frame
        self.assertEqual(
            json.loads(newest[0].payload)['items']['sh600519']['quote']['name'],
            '最新价')


class FrameDedupTests(unittest.TestCase):
    """BUG-冷启动-01: an unchanged snapshot is not re-sent.

    The tick grid pins round *starts*; frames leave at the round *end*, so a
    3.5 s cold round followed by a 0.1 s warm round put two frames 0.6 s apart
    even though the second was a byte-identical cache hit (`ts` aside).  The
    duplicate is now dropped at the send layer, so a sub-tick gap only survives
    a real data change.  A brand-new connection is exempt: it has received
    nothing yet, so it is force-fed the current frame instead of waiting.
    """

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    @staticmethod
    def _add_conn(sid):
        g = get_group(sid)
        conn = _SSEConn()
        with g.conns_lock:
            g.conns.add(conn)
        return conn

    @staticmethod
    def _payloads(conn):
        return [json.loads(f.payload) for f in list(conn.q.queue)
                if isinstance(f, _Frame)]

    @staticmethod
    def _content(payload):
        """Frame content without the build-time `ts` (the dedup basis)."""
        return {k: v for k, v in payload.items() if k != 'ts'}

    def test_unchanged_snapshot_is_not_sent_twice(self):
        """① identical snapshot ⇒ no second frame; `last_push_ts` untouched."""
        sid, _ = create_group(['sh600519'], ['quote'])
        conn = self._add_conn(sid)
        snap = {'sh600519': {'quote': {'name': 'x'}}}
        _broadcast(snap)
        g = get_group(sid)
        g.last_push_ts = 0.0                    # prove dedup skips the metric
        _broadcast(snap)                        # same content in the same tick
        self.assertEqual(len(self._payloads(conn)), 1)
        self.assertEqual(g.last_push_ts, 0.0)   # only a real send refreshes it

    def test_changed_snapshot_is_sent(self):
        """② content change ⇒ a new frame goes out normally."""
        sid, _ = create_group(['sh600519'], ['quote'])
        conn = self._add_conn(sid)
        _broadcast({'sh600519': {'quote': {'name': 'x'}}})
        _broadcast({'sh600519': {'quote': {'name': 'y'}}})
        payloads = self._payloads(conn)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(
            payloads[1]['items']['sh600519']['quote']['name'], 'y')

    def test_new_connection_gets_first_frame_even_when_unchanged(self):
        """③ a connection that never received a frame is not left waiting."""
        sid, _ = create_group(['sh600519'], ['quote'])
        first = self._add_conn(sid)
        snap = {'sh600519': {'quote': {'name': 'x'}}}
        _broadcast(snap)
        late = self._add_conn(sid)              # registered after the frame
        _broadcast(snap)                        # content unchanged
        self.assertEqual(len(self._payloads(first)), 1)   # not re-sent
        self.assertEqual(len(self._payloads(late)), 1)    # never starved

    def test_no_two_consecutive_frames_are_identical(self):
        """④ after dedup no stream ever carries two identical frames in a row."""
        sid, _ = create_group(['sh600519'], ['quote'])
        conn = self._add_conn(sid)
        a = {'sh600519': {'quote': {'name': 'x'}}}
        b = {'sh600519': {'quote': {'name': 'y'}}}
        for snap in (a, a, b, b, a):
            _broadcast(snap)
        frames = [self._content(p) for p in self._payloads(conn)]
        self.assertEqual(len(frames), 3)        # a, b, a — duplicates dropped
        for prev, nxt in zip(frames, frames[1:]):
            self.assertNotEqual(prev, nxt)      # BUG-冷启动-01 guarantee


class ReadJsonBodyGuardTests(unittest.TestCase):
    """P2-5: _read_json_body rejects bad Content-Length before reading body."""

    def test_bad_content_length_returns_none_without_reading_body(self):
        handler = StreamHandler.__new__(StreamHandler)
        for bad_cl in ('abc', '1.5', '-5', '70000'):  # non-num / negative / >65536
            handler.headers = {'Content-Length': bad_cl}
            body = Mock()
            handler.rfile = body
            self.assertIsNone(handler._read_json_body(), f'CL={bad_cl!r}')
            body.read.assert_not_called()


class MaybeReconnectThrottleTests(unittest.TestCase):
    """P2-5: _maybe_reconnect skips full Chrome restart inside the throttle
    window (_CHROME_RESTART_THROTTLE * 2 = 30s) — only reconnect, never a
    real full_chrome_restart. Everything heavy is patched."""

    def test_second_trigger_within_throttle_skips_restart(self):
        page = cdp_engine.CDPPage.__new__(cdp_engine.CDPPage)
        page.name = 'test-page'
        page.cdp_host = '127.0.0.1'
        page.cdp_port = 9222
        saved_counter = cdp_engine.CDPPage._nav_restart_counter
        try:
            # one nav short of the threshold => this trigger crosses it
            cdp_engine.CDPPage._nav_restart_counter = (
                cdp_engine.CDPPage._MAX_PAGE_NAV_BEFORE_RECONNECT - 1)
            with patch.object(cdp_engine, '_last_chrome_restart', time.time()), \
                 patch.object(cdp_engine, '_CHROME_RESTART_THROTTLE', 15), \
                 patch.object(cdp_engine, 'full_chrome_restart',
                              return_value=True) as restart, \
                 patch.object(page, '_reconnect', return_value=True):
                result = page._maybe_reconnect()
            self.assertFalse(result)
            restart.assert_not_called()
            # threshold was crossed: counter reset even though restart skipped
            self.assertEqual(cdp_engine.CDPPage._nav_restart_counter, 0)
        finally:
            cdp_engine.CDPPage._nav_restart_counter = saved_counter


def _json(resp):
    import json
    return json.loads(resp.read().decode('utf-8'))


class ZombieGroupTests(unittest.TestCase):
    """压测发现：POST 风暴僵尸组全量广播烧 CPU — 修复回归测试。"""

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    def test_active_codes_excludes_connectionless_groups(self):
        sid, _ = create_group(['sh600519', 'sz000001'], None)
        # 组已创建但无连接 → 不应贡献活动刷新池（僵尸组烧 CPU 回归）
        self.assertEqual(_active_codes(), set())
        # 池上限账本仍含全部组（内存防无界）
        self.assertEqual(_deduped_codes(), {'sh600519', 'sz000001'})
        # 挂上连接后贡献活动池
        g = get_group(sid)
        conn = _SSEConn()
        with g.conns_lock:
            g.conns.add(conn)
        self.assertEqual(_active_codes(), {'sh600519', 'sz000001'})

    def test_broadcast_skips_zombie_group_frame_build(self):
        sid, _ = create_group(['sh600519'], None)  # 无连接组
        snapshot = {'sh600519': {'quote': {'price': 1.0}}}
        with patch('china_finance_rss.stream._build_frame', wraps=stream_mod._build_frame) as m:
            _broadcast(snapshot)
            # 僵尸组不应 build frame
            m.assert_not_called()

    def test_broadcast_serves_live_group_only(self):
        sid, _ = create_group(['sh600519'], None)
        g = get_group(sid)
        conn = _SSEConn()
        with g.conns_lock:
            g.conns.add(conn)
        snapshot = {'sh600519': {'quote': {'price': 1.0}}}
        with patch('china_finance_rss.stream._build_frame') as m:
            m.return_value = 'data: {"x":1}'      # str per _Frame.payload contract
            _broadcast(snapshot)
            m.assert_called_once()
        _groups.clear()

    def test_sweep_idle_groups_reaps_zombie(self):
        sid, _ = create_group(['sh600519'], None)
        g = get_group(sid)
        # 伪造：最后推送很久以前（无连接）
        g.last_push_ts = time.time() - 10000
        g.created_ts = time.time() - 10000
        self.assertEqual(len(_groups), 1)
        _sweep_idle_groups()
        self.assertEqual(len(_groups), 0, '僵尸组应被清扫')

    def test_sweep_keeps_live_or_recent_group(self):
        sid, _ = create_group(['sh600519'], None)
        # 有连接 → 不扫
        conn = _SSEConn()
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(conn)
        _sweep_idle_groups()
        self.assertEqual(len(_groups), 1, '活动组不应被扫')

    def test_sweep_skips_recent_connectionless(self):
        sid, _ = create_group(['sh600519'], None)  # 刚创建、无连接但 last_push_ts 近
        _sweep_idle_groups()
        self.assertEqual(len(_groups), 1, '新组未到 TTL 不应清扫')


    def test_sweep_reconnect_between_collect_and_destroy_keeps_group(self):
        """P2-2 定向：sweep 销毁前锁内重查空集 — 已重连的组不被误杀（TOCTOU 防线）。

        确定性覆盖：组已超龄（满足收集条件）且重连已完成时，sweep 看到
        conns 非空 → 保留组、sid 不 404。
        """
        sid, _ = create_group(['sh600519'], None)
        g = get_group(sid)
        g.created_ts = time.time() - 10000
        g.last_push_ts = time.time() - 10000
        conn = _SSEConn()
        with g.conns_lock:
            g.conns.add(conn)  # 客户端重连完成
        _sweep_idle_groups()
        self.assertIsNotNone(get_group(sid), '重连组不应被 sweep 误杀')
        self.assertEqual(len(_groups), 1)

    def test_sweep_reconnect_race_stress_no_kill(self):
        """P2-2 压力注入：sweep 与连接注册并发 200 轮 — 无崩溃/死锁/误杀。"""
        sid, _ = create_group(['sh600519'], None)
        g = get_group(sid)
        g.created_ts = time.time() - 10000
        g.last_push_ts = time.time() - 10000
        stop = threading.Event()
        registered = [0]

        def reconnector():
            while not stop.is_set():
                conn = _SSEConn()
                with g.conns_lock:
                    g.conns.add(conn)
                    registered[0] += 1
                time.sleep(0.0005)
                with g.conns_lock:
                    g.conns.discard(conn)

        t = threading.Thread(target=reconnector, daemon=True)
        t.start()
        try:
            for _ in range(200):
                _sweep_idle_groups()
        finally:
            stop.set()
            t.join()
        self.assertGreater(registered[0], 0, '压力注入应产生连接注册')
        self.assertIn(len(_groups), (0, 1))

class FrozenGroupStateTests(unittest.TestCase):
    """BR-STR-1/4: group state is immutable and replaced wholesale on patch."""

    def tearDown(self):
        _groups.clear()

    def test_codes_frozenset_fields_tuple(self):
        sid, err = create_group(['sh600519', 'sz000001'], ['quote', 'fundflow'])
        self.assertIsNone(err)
        g = get_group(sid)
        self.assertIsInstance(g.codes, frozenset)
        self.assertIsInstance(g.fields, tuple)
        self.assertEqual(g.fields, ('quote', 'fundflow'))
        with self.assertRaises(AttributeError):
            g.codes.add('sz000002')

    def test_patch_replaces_codes_object(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        g = get_group(sid)
        before = g.codes
        ok, err = patch_group(sid, add=['sz000001'], remove=['sh600519'])
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNot(g.codes, before)          # whole replacement
        self.assertEqual(g.codes, frozenset({'sz000001'}))


class FrameAccountingTests(unittest.TestCase):
    """BR-STR-5..14: distinct-frame billing and drain symmetry."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    @staticmethod
    def _conn_for(sid, n=1):
        g = get_group(sid)
        conns = []
        for _ in range(n):
            c = _SSEConn()
            with g.conns_lock:
                g.conns.add(c)
            conns.append(c)
        return g, conns

    def test_distinct_frame_billed_once_for_many_conns(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        _, conns = self._conn_for(sid, 3)

        _broadcast({'sh600519': {'quote': {'name': 'x'}}})

        held = [f for c in conns for f in list(c.q.queue)
                if isinstance(f, _Frame)]
        self.assertEqual(len(held), 3)
        self.assertEqual(len({id(f) for f in held}), 1)   # same distinct frame
        frame = held[0]
        self.assertEqual(frame.refs, 3)
        self.assertEqual(stream_mod._queue_bytes, frame.size)   # billed once
        self.assertEqual(stream_mod._live_frames, 1)
        self.assertEqual(stream_mod._group_bytes[sid], frame.size)

    def test_drain_releases_back_to_zero(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        _, conns = self._conn_for(sid, 2)
        _broadcast({'sh600519': {'quote': {'name': 'x'}}})
        self.assertGreater(stream_mod._queue_bytes, 0)

        for c in conns:
            _drain_conn_queue(c)

        self.assertEqual(stream_mod._queue_bytes, 0)
        self.assertEqual(stream_mod._live_frames, 0)
        self.assertNotIn(sid, stream_mod._group_bytes)
        # idempotent: a second drain releases nothing
        self.assertEqual(_drain_conn_queue(conns[0]), 0)

    def test_none_sentinel_is_not_billed(self):
        conn = _SSEConn()
        conn.q.put_nowait(None)
        before = stream_mod._queue_bytes
        self.assertEqual(_drain_conn_queue(conn), 0)
        self.assertEqual(stream_mod._queue_bytes, before)

        conn2 = _SSEConn()
        conn2.q.put_nowait(None)
        self.assertIsNone(_pop_oldest_frame(conn2))     # consumed, not billed
        self.assertEqual(conn2.q.qsize(), 0)


class ReserveSkipTests(unittest.TestCase):
    """P2-6 / BR-STR-15: a group with no droppable _Frame joins the round's
    skip set and keeps its byte ledger intact."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    def test_group_with_only_sentinel_keeps_ledger(self):
        sid1, _ = create_group(['sh600519'], ['quote'])
        sid2, _ = create_group(['sz000001'], ['quote'])
        g1, g2 = get_group(sid1), get_group(sid2)
        c1, c2 = _SSEConn(), _SSEConn()
        with g1.conns_lock:
            g1.conns.add(c1)
        with g2.conns_lock:
            g2.conns.add(c2)

        # G1 retains 2 billed frames but its queue head is a None sentinel.
        c1.q.put_nowait(None)
        f1a, f1b = _Frame('a' * 100, sid1), _Frame('b' * 100, sid1)
        for f in (f1a, f1b):
            c1.q.put_nowait(f)
            _frame_acquire(f)
        # G2 retains 1 droppable frame.
        f2 = _Frame('c' * 100, sid2)
        c2.q.put_nowait(f2)
        _frame_acquire(f2)

        self.assertEqual(stream_mod._queue_bytes, 300)
        with patch.object(stream_mod, 'STREAM_QUEUE_BYTES_BUDGET', 300):
            dropped = _reserve_for(50)

        self.assertEqual(dropped, 1)                        # only G2's frame
        self.assertEqual(stream_mod._group_bytes.get(sid1), 200)   # ledger intact
        self.assertEqual(stream_mod._queue_bytes + 50 <= 300, True)
        self.assertEqual(f2.refs, 0)                        # released
        # sentinel consumed => G1 head is now a real frame
        self.assertIsInstance(c1.q.queue[0], _Frame)


class ShardingTests(unittest.TestCase):
    """BR-STR-16..22: whole-pool refresh vs sharded round-robin + cache fill.

    Thresholds come from the r5 warm-path recalibration plus the quote=2
    (basic + depth) steady-state cost: per-code cost = 4 upstream calls
    (quote 2 + fundflow 1 + timeline 1), per-worker-call 0.3 s at
    BATCH_MAX_WORKERS=20 ⇒ tick=8 gives coverage=426 fetch-calls ⇒
    coverage_codes=106 codes.
    These tests drive `_refresh_pool` with no live group, i.e. the all-fields
    fallback (`_resolve_refresh_fields(None)`); a quote-only subscription gets
    coverage_codes=213 instead — see SubscribedFieldRefreshTests.
    """

    # coverage=426, coverage_codes=426//4=106 (tick=8, BATCH_MAX_WORKERS=20,
    # _PER_FETCH_EST=0.3)
    COVERAGE_CODES = 106

    def setUp(self):
        _groups.clear()
        import china_finance_rss.stock_api as stock_api_mod
        with stock_api_mod._prefetch_cursor_lock:
            stock_api_mod._prefetch_cursor.pop('stream_refresh', None)

    def tearDown(self):
        _groups.clear()

    def test_c1_whole_pool_no_sharding(self):
        codes = [f'sh{600000 + i:06d}' for i in range(3)]
        calls = {'slice': 0, 'cached': 0, 'handlers': []}

        def fake_slice(*a, **k):
            calls['slice'] += 1
            return ([], 0)

        def fake_cached(domain, cs, now=None):
            calls['cached'] += 1
            return {}

        def mk_handler(name):
            def _h(cs, deadline=None):
                calls['handlers'].append((name, list(cs)))
                return {c: {'v': 1} for c in cs}
            return _h

        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {f: mk_handler(f) for f in ('quote', 'fundflow', 'timeline')}), \
             patch.object(stream_mod, '_prefetch_slice', side_effect=fake_slice), \
             patch.object(stream_mod, 'cached_batch', side_effect=fake_cached), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            snap = _refresh_pool(codes)

        self.assertEqual(calls['slice'], 0)          # C1 => no slicing
        self.assertEqual(calls['cached'], 0)         # C1 => no cache read
        self.assertEqual(set(snap), set(codes))
        for _name, cs in calls['handlers']:
            self.assertEqual(set(cs), set(codes))    # whole pool handed in

    def test_c1_boundary_is_the_calibrated_threshold(self):
        """C1 holds up to coverage_codes codes; one code more shards (P6C-06).

        Regression: the cold-path calibration `3n <= 23` (per-fetch 2.2 s) kept
        the whole refresh ≤ 0.8 × tick but only for ≤7 codes — it could not meet
        the 50-code target.  The r5 warm-path model `4n <= 426` at
        0.3 s/call and 20 workers keeps the whole refresh ≤ 0.8 × tick and puts
        106 codes on the C1 branch.
        """
        handlers = {f: (lambda cs, deadline=None: {c: {'v': 1} for c in cs})
                    for f in ('quote', 'fundflow', 'timeline')}
        seen = {'slice_sizes': [], 'cached': 0}

        def fake_slice(pool, lock, key, size):
            seen['slice_sizes'].append(size)
            keys = sorted(pool)
            return keys[:size], size

        def fake_cached(domain, cs, now=None):
            seen['cached'] += 1
            return {c: {'v': 2} for c in cs}

        def drive(n):
            seen['slice_sizes'].clear()
            seen['cached'] = 0
            codes = [f'sh{600000 + i:06d}' for i in range(n)]
            with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
                 patch.object(stream_mod, '_prefetch_slice', side_effect=fake_slice), \
                 patch.object(stream_mod, '_prefetch_advance'), \
                 patch.object(stream_mod, 'cached_batch', side_effect=fake_cached), \
                 patch.object(stream_mod, 'tick_interval', return_value=8):
                snap = _refresh_pool(codes)
            return snap

        n = self.COVERAGE_CODES
        drive(n)                                     # exactly at the threshold
        self.assertEqual(seen['slice_sizes'], [])    # C1: no slicing
        self.assertEqual(seen['cached'], 0)          # C1: no cache read

        drive(n + 1)                                 # one past it
        self.assertEqual(seen['slice_sizes'], [n])   # C2: one slice of threshold size
        self.assertEqual(seen['cached'], 3)          # one cached_batch per field
        self.assertEqual(len(drive(n + 1)), n + 1)   # warm codes never degrade

    def test_c2_missing_codes_are_marked_not_silently_omitted(self):
        """T4 (S2-1): drive C2 against the REAL terminal-cache TTL semantics.

        The old test used a cache that never expires and asserted
        ``len(snap) == 300`` — that masked the silent-missing-code path: with an
        expired cache only the shard is fresh, and the other 293 subscribed codes
        used to vanish from the frame with no marker.  Here every terminal-cache
        entry is seeded and then driven with a ``now`` past its TTL, so the real
        ``stock_api.cached_batch`` expires them; the frame must still cover every
        code and name the missing ones.
        """
        import china_finance_rss.stock_api as stock_api_mod

        codes = [f'sh{600000 + i:06d}' for i in range(300)]
        fields = ('quote', 'fundflow', 'timeline')
        seen = {'slice_size': []}

        def fake_slice(pool, lock, key, size):
            keys = sorted(pool)
            return keys[:size], size

        def mk_handler(name):
            def _h(cs, deadline=None):
                seen['slice_size'].append(len(cs))
                return {c: {'live': 1} for c in cs}
            return _h

        written = time.time()
        future = written + 10 ** 7                   # ≫ every domain TTL
        saved = {}
        for domain in fields:
            _pool, cache, cache_ts, lock = stock_api_mod._DOMAIN_STORES[domain]
            with lock:
                saved[domain] = (dict(cache), dict(cache_ts))
                for c in codes:
                    cache[c] = {'seeded': True}
                    cache_ts[c] = written
        try:
            with patch.dict(stream_mod._FIELD_HANDLERS,
                            {f: mk_handler(f) for f in fields}), \
                 patch.object(stream_mod, '_prefetch_slice', side_effect=fake_slice), \
                 patch.object(stream_mod, '_prefetch_advance'), \
                 patch.object(stream_mod, 'tick_interval', return_value=8):
                # real cached_batch, injected future clock ⇒ all entries expired
                snap = _refresh_pool(codes, now=future)
        finally:
            for domain, (cache_snapshot, ts_snapshot) in saved.items():
                _pool, cache, cache_ts, lock = \
                    stock_api_mod._DOMAIN_STORES[domain]
                with lock:
                    cache.clear()
                    cache.update(cache_snapshot)
                    cache_ts.clear()
                    cache_ts.update(ts_snapshot)

        # coverage=426 ⇒ |slice|=106; the expired rest contributes nothing
        self.assertEqual(max(seen['slice_size']), self.COVERAGE_CODES)
        self.assertEqual(len(snap), self.COVERAGE_CODES)     # was 300 = 假绿
        self.assertEqual(stream_mod.metrics.snapshot()['stream_refresh_lag_ticks'],
                         -(-300 // self.COVERAGE_CODES))   # ceil(300/106) == 3

        # …but the frame still covers the whole subscription and marks the rest
        frame = _build_frame(snap, frozenset(codes), fields)
        data = json.loads(frame)
        self.assertEqual(data['codes_total'], 300)
        self.assertEqual(set(data['items']), set(codes))     # full coverage
        self.assertEqual(data['missing_count'], 300 - self.COVERAGE_CODES)
        self.assertEqual(set(data['missing']), set(codes) - set(snap))
        for code in data['missing']:                          # explicit no-data
            self.assertTrue(all(v is None
                                for v in data['items'][code].values()))


class RefreshCapacityCalibrationTests(unittest.TestCase):
    """BUG-P6C-01/06 + r5: the capacity model must price the *real* upstream
    cost (0.3 s per worker-call on the pool-warmed path, one call/code/domain
    in steady state) so one tick's work fits the 0.8×tick budget at any group
    size — spill-over is sharded, never硬刷.  The 8 s hard target (50 codes ×
    1 or 3 domains) must land in C1."""

    def test_coverage_uses_field_aware_call_counts(self):
        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {'quote': lambda cs: {}, 'fundflow': lambda cs: {},
                         'timeline': lambda cs: {}}, clear=True):
            self.assertEqual(_fetches_per_code(), 4)   # quote 2 + 1 + 1
        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {'quote': lambda cs: {}}, clear=True):
            self.assertEqual(_fetches_per_code(), 2)   # basic + depth
        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {'custom': lambda cs: {}}, clear=True):
            self.assertEqual(_fetches_per_code(), 1)   # unknown field ⇒ 1 call
        # explicit field set (the BUG-P6C-06 selector) prices per domain
        self.assertEqual(_fetches_per_code(['quote', 'fundflow']), 3)
        self.assertEqual(_fetches_per_code([]), 4)     # empty ⇒ all fields

    def test_calibrated_coverage_numbers(self):
        coverage, coverage_codes = refresh_capacity(8)
        self.assertEqual(coverage, 426)         # int(0.8 × 8 × 20 / 0.3)
        self.assertEqual(coverage_codes, 106)   # 426 // 4 (quote 2 + 1 + 1)
        coverage, coverage_codes = refresh_capacity(120)   # off-hours L1
        self.assertEqual(coverage, 6400)        # int(0.8 × 120 × 20 / 0.3)
        self.assertEqual(coverage_codes, 1600)  # 6400 // 4

    def test_three_domain_50_codes_is_c1_regression_guard(self):
        """★ BUG-SSE-DEPTH-01 guard: the hard target — 3 domains × 50 codes —
        must stay in C1 (whole-pool refresh within ONE tick), so the cold first
        full frame is ≤ 8s.

        Asserted against the live constants (`BATCH_MAX_WORKERS` /
        `_PER_FETCH_EST` / `_FIELD_FETCH_CALLS`), so any future retune that
        pushes coverage_codes below 50 fails here rather than in production as a
        silent 2-tick C2 shard (the exact regression that cost 12.33s).
        """
        tick = 4                                   # L0 in-session (quote-driven)
        fields = ['quote', 'fundflow', 'timeline']
        fetches = _fetches_per_code(fields)
        self.assertEqual(fetches, 4)               # basic+depth, fundflow, timeline
        coverage, coverage_codes = refresh_capacity(tick, fields)
        self.assertGreaterEqual(coverage_codes, 50)      # ← the guard
        self.assertLessEqual(50 * fetches, coverage)     # 200 ≤ 213 ⇒ C1
        modelled = 50 * fetches * stream_mod._PER_FETCH_EST \
            / stream_mod.BATCH_MAX_WORKERS
        self.assertLessEqual(modelled, stream_mod._TICK_BUDGET_FRACTION * tick)

    def test_quote_tick_is_l0_and_covers_50_codes_whole(self):
        """Task 1 + 2: a live quote subscription pushes on the L0 cadence (4s),
        and 50 quote codes (basic + depth = 2 calls/code) still land in C1 so
        the whole watchlist refreshes inside one 0.8 × 4 s budget."""
        with patch('china_finance_rss.stream._trading_tiers',
                   return_value={'L0': 4, 'L1': 8, 'L2': 12}):
            tick = tick_interval(['quote'])
        self.assertEqual(tick, 4)
        coverage, coverage_codes = refresh_capacity(tick, ['quote'])
        self.assertEqual(coverage, 213)         # int(0.8 × 4 × 20 / 0.3)
        self.assertEqual(coverage_codes, 106)   # 213 // 2
        self.assertGreaterEqual(coverage_codes, 50)          # ≥ 50 hard target
        modelled = 50 * 2 * stream_mod._PER_FETCH_EST / stream_mod.BATCH_MAX_WORKERS
        self.assertLessEqual(modelled, stream_mod._TICK_BUDGET_FRACTION * tick)

    def test_three_domain_50_codes_still_within_8s(self):
        """任务 2 的既有硬指标：quote+depth+fundflow+timeline 50 码刷新周期 ≤8s。

        BUG-SSE-DEPTH-01: with BATCH_MAX_WORKERS=20 the 3-domain cost
        4 × 50 = 200 fits one C1 whole-pool refresh inside the 0.8 × 4 s
        budget (coverage=213 ⇒ coverage_codes=53), so the refresh period is
        one tick (4 s), not the old 2-tick (8 s) C2 shard."""
        with patch('china_finance_rss.stream._trading_tiers',
                   return_value={'L0': 4, 'L1': 8, 'L2': 12}):
            tick = tick_interval(['quote', 'fundflow', 'timeline'])
        self.assertEqual(tick, 4)               # min(L0=4, L1=8, L1=8)
        coverage, coverage_codes = refresh_capacity(tick, ['quote', 'fundflow', 'timeline'])
        self.assertEqual(coverage, 213)
        self.assertEqual(coverage_codes, 53)    # 213 // 4
        # C1 (guard test above): 4 × 50 = 200 ≤ 213 ⇒ whole pool in one tick,
        # so the refresh period meets the ≤ 8s hard target.
        fetches = _fetches_per_code(['quote', 'fundflow', 'timeline'])
        self.assertGreaterEqual(coverage_codes, 50)
        self.assertLessEqual(50 * fetches, coverage)
        self.assertLessEqual(tick, 8)                   # one C1 tick ≤ 8s
        # and the 8s cadence (fundflow/timeline only) stays whole-pool
        cov8, cc8 = refresh_capacity(8, ['fundflow', 'timeline'])
        self.assertGreaterEqual(cc8, 50)

    def test_single_domain_subscription_covers_the_target_load(self):
        """50 codes × quote: whole-pool refresh inside 0.8 × 4 s (L0)."""
        tick = 4
        coverage, coverage_codes = refresh_capacity(tick, ['quote'])
        self.assertEqual(coverage, 213)
        self.assertEqual(coverage_codes, 106)   # basic + depth ⇒ 2 calls/code
        self.assertGreaterEqual(coverage_codes, 50)
        modelled = 50 * 2 * stream_mod._PER_FETCH_EST / stream_mod.BATCH_MAX_WORKERS
        self.assertLessEqual(modelled, stream_mod._TICK_BUDGET_FRACTION * tick)

    def test_single_tick_work_fits_the_budget(self):
        """Both the model and the warm-path measurement fit 0.8 × tick, and the
        50-code × 3-field target lands in C1 (whole-pool refresh)."""
        tick = 8
        coverage, coverage_codes = refresh_capacity(tick)
        budget = stream_mod._TICK_BUDGET_FRACTION * tick
        fetches = _fetches_per_code()
        self.assertLessEqual(fetches * coverage_codes, coverage)
        modelled = fetches * coverage_codes * stream_mod._PER_FETCH_EST \
            / stream_mod.BATCH_MAX_WORKERS
        self.assertLessEqual(modelled, budget)
        # measured (r5 warm path): 139 ms per call, 3 fields/code, 20-wide
        measured_per_call = 0.139
        measured = fetches * coverage_codes * measured_per_call \
            / stream_mod.BATCH_MAX_WORKERS
        self.assertLessEqual(measured, budget)
        # the hard target: 50 codes × 3 fields must fit one C1 refresh
        self.assertGreaterEqual(coverage_codes, 50)


class SubscribedFieldRefreshTests(unittest.TestCase):
    """BUG-P6C-06 fix 1: only the live subscription union is refreshed.

    The old `_refresh_pool` iterated every `_FIELD_HANDLERS` entry, so a
    quote-only group paid for fundflow + timeline too (3× upstream cost).
    """

    def setUp(self):
        _groups.clear()
        import china_finance_rss.stock_api as stock_api_mod
        with stock_api_mod._prefetch_cursor_lock:
            stock_api_mod._prefetch_cursor.pop('stream_refresh', None)

    def tearDown(self):
        _groups.clear()

    @staticmethod
    def _attach(sid):
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())
        return g

    def test_union_is_ordered_by_field_handlers(self):
        sid1, _ = create_group(['sh600519'], ['timeline'])
        sid2, _ = create_group(['sz000001'], ['quote', 'fundflow'])
        self._attach(sid1)
        self._attach(sid2)
        self.assertEqual(_subscribed_fields(),
                         ['quote', 'fundflow', 'timeline'])
        with stream_mod._groups_lock:
            self.assertEqual(_subscribed_fields_unlocked(),
                             ['quote', 'fundflow', 'timeline'])

    def test_empty_until_a_group_goes_live(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        # created but connectionless (zombie) ⇒ no upstream demand
        self.assertEqual(_subscribed_fields(), [])
        self.assertEqual(_active_targets(), (set(), []))
        self._attach(sid)
        self.assertEqual(_subscribed_fields(), ['quote'])
        self.assertEqual(_active_targets(), ({'sh600519'}, ['quote']))

    def test_refresh_pool_only_calls_subscribed_handlers(self):
        sid, _ = create_group(['sh600519'], ['timeline'])
        self._attach(sid)
        called = []

        def mk(name):
            def _h(cs, deadline=None):
                called.append(name)
                return {c: {'v': name} for c in cs}
            return _h

        handlers = {f: mk(f) for f in ('quote', 'fundflow', 'timeline')}
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            snap = _refresh_pool(['sh600519'])

        self.assertEqual(called, ['timeline'])       # not all three domains
        self.assertEqual(set(snap['sh600519']), {'timeline'})

    def test_explicit_fields_param_wins(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        self._attach(sid)
        called = []

        def mk(name):
            def _h(cs, deadline=None):
                called.append(name)
                return {c: {'v': name} for c in cs}
            return _h

        handlers = {f: mk(f) for f in ('quote', 'fundflow', 'timeline')}
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            snap = _refresh_pool(['sh600519'], None, ['fundflow'])

        self.assertEqual(called, ['fundflow'])
        self.assertEqual(set(snap['sh600519']), {'fundflow'})

    def test_resolve_falls_back_to_all_fields_without_subscription(self):
        self.assertEqual(_resolve_refresh_fields(None),
                         ['quote', 'fundflow', 'timeline'])
        self.assertEqual(_resolve_refresh_fields(['timeline']), ['timeline'])
        # unknown names are dropped; ordering is always _FIELD_HANDLERS order
        self.assertEqual(_resolve_refresh_fields(['timeline', 'nope']),
                         ['timeline'])

    def test_capacity_follows_the_subscribed_fields(self):
        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {f: (lambda cs: {})
                         for f in ('quote', 'fundflow', 'timeline')}, clear=True):
            self.assertEqual(refresh_capacity(8, ['quote']), (426, 213))
            self.assertEqual(refresh_capacity(8, ['quote', 'fundflow']),
                             (426, 142))
            self.assertEqual(refresh_capacity(8), (426, 106))  # all 3 fields


class QuoteDepthFrameTests(unittest.TestCase):
    """任务 2c: a `quote` subscription's SSE frame carries the five-level book.

    `depth` is not a separate stream field — it is embedded in the quote
    payload by the handler, so a quote-only group needs no extra subscription
    and the frame gains one additive `depth` key (or none when the upstream has
    no book, never a fabricated all-zero one).
    """

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    @staticmethod
    def _attach(sid):
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())
        return g

    def test_quote_frame_carries_depth_when_the_handler_provides_it(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        self._attach(sid)
        book = {'b_px_1': 1.0, 's_px_1': 2.0}

        def _handler(cs, deadline=None):
            return {c: {'last_px': 1.0, 'depth': book} for c in cs}

        with patch.dict(stream_mod._FIELD_HANDLERS, {'quote': _handler}), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            snap = _refresh_pool(['sh600519'])
        self.assertEqual(snap['sh600519']['quote']['depth'], book)

        frame = json.loads(_build_frame(snap, frozenset(['sh600519']), ('quote',)))
        self.assertEqual(frame['items']['sh600519']['quote']['depth'], book)

    def test_quote_field_prices_two_upstream_calls(self):
        """basic + depth ⇒ the capacity model charges 2 calls/code."""
        self.assertEqual(stream_mod._FIELD_FETCH_CALLS['quote'], 2)
        self.assertEqual(_fetches_per_code(['quote']), 2)

    def test_missing_depth_is_not_padded_with_fake_bands(self):
        """A code with no book keeps the key absent (handler returns no depth);
        the frame's quote row is the real payload, never 0-filled bands."""
        sid, _ = create_group(['bj430047'], ['quote'])
        self._attach(sid)

        def _handler(cs, deadline=None):
            return {c: {'last_px': 1.0} for c in cs}     # no 'depth'

        with patch.dict(stream_mod._FIELD_HANDLERS, {'quote': _handler}), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            snap = _refresh_pool(['bj430047'])
        self.assertEqual(snap['bj430047']['quote'], {'last_px': 1.0})
        self.assertNotIn('depth', snap['bj430047']['quote'])


class TickFollowsSubscriptionTests(unittest.TestCase):
    """任务 1b: the scheduler's cadence follows the live subscription's fastest
    domain, and `push_loop` computes it once per round (`_push_once(t0, tick=…)`).
    """

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    @staticmethod
    def _attach(sid):
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())
        return g

    def test_tick_reflects_live_fields_then_returns_to_baseline(self):
        with patch('china_finance_rss.stream._trading_tiers',
                   return_value={'L0': 4, 'L1': 8, 'L2': 12}):
            self.assertEqual(tick_interval(_subscribed_fields()), 8)  # none live
            sid, _ = create_group(['sh600519'], ['quote'])
            self.assertEqual(tick_interval(_subscribed_fields()), 8)  # zombie
            self._attach(sid)
            self.assertEqual(tick_interval(_subscribed_fields()), 4)  # L0
            destroy_group(sid)
            self.assertEqual(tick_interval(_subscribed_fields()), 8)  # baseline

    def test_passes_the_round_tick_down_to_refresh(self):
        """`_push_once` must reuse the passed tick instead of recomputing it, so
        the C1/C2 threshold and the cadence can never disagree."""
        sid, _ = create_group(['sh600519'], ['quote'])
        self._attach(sid)
        seen = {}

        def _spy(codes, now=None, fields=None, tick=None, deadline=None):
            seen['tick'] = tick
            return {}

        with patch.object(stream_mod, '_refresh_pool', side_effect=_spy), \
             patch.object(stream_mod, 'cached_batch', return_value={}):
            stream_mod._push_once(t0=time.time(), tick=4)
        self.assertEqual(seen['tick'], 4)


class RefreshLagGaugeTests(unittest.TestCase):
    """BUG-P6C-08: `stream_refresh_lag_ticks` = real backlog in ticks; 0 when
    nothing lags (empty pool / whole-pool refresh).

    The empty-pool reset MUST be reached through the real scheduled iteration
    body (`_push_once`), never by calling `_refresh_pool([])` directly: that
    bypasses the `if codes:` guard, which is exactly how the previous
    "fake-green" test hid a gauge that stranded in production (tester r4 §5.3).
    """

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    @staticmethod
    def _handlers():
        return {f: (lambda cs, deadline=None: {c: {'v': 1} for c in cs})
                for f in ('quote', 'fundflow', 'timeline')}

    @staticmethod
    def _attach(sid):
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())
        return g

    def _lag(self):
        return stream_mod.metrics.snapshot()['stream_refresh_lag_ticks']

    def test_lag_resets_on_the_scheduled_path_after_the_pool_empties(self):
        """Tester repro (r4 §5.1): C2 backlog (lag=2) ⇒ pool empties ⇒ the very
        next scheduled round publishes 0.

        Drives `_push_once` — the exact body `push_loop` runs each round — so
        the `if codes:` guard is exercised for real (the old test called
        `_refresh_pool([])`, bypassing it and staying green while the deployed
        gauge never reset).
        """
        # 200 codes × 3 fields: 4 × 200 = 800 > coverage=426 ⇒ C2
        # (a quote-only group can no longer shard: 213 > MAX_CODES_PER_SUB=200)
        codes = [f'sh{600000 + i:06d}'
                 for i in range(config.MAX_CODES_PER_SUB)]
        sid, _ = create_group(codes, ['quote', 'fundflow', 'timeline'])
        self._attach(sid)

        with patch.dict(stream_mod._FIELD_HANDLERS, self._handlers()), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            stream_mod._push_once(t0=time.time())
            self.assertEqual(self._lag(), 2)        # ceil(200/106): real backlog

            # the pool empties (tester's DELETE of the last subscription)
            self.assertTrue(destroy_group(sid))
            self.assertEqual(_active_targets(), (set(), []))

            stream_mod._push_once(t0=time.time())   # the very next round

        self.assertEqual(self._lag(), 0)            # ★ was stranded at 2

    def test_empty_pool_does_not_grow_degraded_or_slip(self):
        """Item 4: an empty round costs ~0ms, so the overrun counters must not
        grow on the branch that publishes the lag reset."""
        before = stream_mod.metrics.snapshot()
        with patch.object(stream_mod, 'tick_interval', return_value=8):
            stream_mod._push_once(t0=time.time())
        after = stream_mod.metrics.snapshot()
        self.assertEqual(after['stream_tick_degraded_total'],
                         before['stream_tick_degraded_total'])
        self.assertEqual(after['stream_tick_slip_total'],
                         before['stream_tick_slip_total'])

    def test_whole_pool_refresh_is_zero_lag(self):
        codes = [f'sh{600000 + i:06d}' for i in range(3)]
        with patch.dict(stream_mod._FIELD_HANDLERS, self._handlers()), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            _refresh_pool(codes)
        self.assertEqual(self._lag(), 0)

    def test_sharded_refresh_reports_ceil_backlog(self):
        codes = [f'sh{600000 + i:06d}' for i in range(300)]   # > 106 ⇒ C2
        with patch.dict(stream_mod._FIELD_HANDLERS, self._handlers()), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            _refresh_pool(codes)
        self.assertEqual(self._lag(), -(-300 // 106))    # ceil(300/106) == 3


class _LoopStop(BaseException):
    """Sentinel that escapes `push_loop`'s `except Exception` (test only)."""


class PushLoopWiringTests(unittest.TestCase):
    """BUG-P6C-08: the regression above is only meaningful if `push_loop`
    actually runs `_push_once`.  Guards against the wiring being refactored
    away while the unit test keeps passing."""

    def test_push_loop_runs_the_single_iteration_body(self):
        calls = []

        def body(t0, tick=None):
            calls.append((t0, tick))
            raise _LoopStop()

        with patch.object(stream_mod, '_push_once', side_effect=body), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            with self.assertRaises(_LoopStop):
                stream_mod.push_loop()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 4)                 # tick passed down once

    def test_error_path_stays_on_the_grid_with_backoff(self):
        """T6 (P2): the exception branch must not degrade into a ~1 s spin
        (8× upstream pressure).  Consecutive failures back off 1, 2, 4, … ticks,
        so every sleep is at least one whole tick."""
        calls = []
        sleeps = []

        def body(t0, tick=None):
            calls.append(t0)
            if len(calls) <= 3:
                raise RuntimeError('boom')
            raise _LoopStop()

        with patch.object(stream_mod, '_push_once', side_effect=body), \
             patch.object(stream_mod, 'tick_interval', return_value=8), \
             patch.object(stream_mod.time, 'sleep',
                          side_effect=lambda s: sleeps.append(s)):
            with self.assertRaises(_LoopStop):
                stream_mod.push_loop()

        self.assertEqual(len(calls), 4)
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(all(s > 7 for s in sleeps), sleeps)    # never ~1 s
        self.assertTrue(sleeps[0] < sleeps[1] < sleeps[2])     # backoff grows
        self.assertLessEqual(sleeps[2], 32)                    # capped (8 ticks)


class _FakeSSEConn:
    """Minimal `_SSEConn` double whose queue yields the exit sentinel at once."""

    def __init__(self):
        self.q = _SentinelQueue()
        self.closed = False


class _SentinelQueue:
    def get(self, timeout=None):
        return None                    # `_serve_sse` sees the sentinel ⇒ breaks

    def get_nowait(self):
        raise queue.Empty

    def qsize(self):
        return 0

    def full(self):
        return False


class IdleWakeTests(unittest.TestCase):
    """SSE cold-start: an idle push loop is woken immediately by a new
    subscription / connection, and waking can never put two round *starts*
    back-to-back (active rounds keep the hard tick-grid sleep; a woken
    empty-demand round emits no frame at all — BUG-冷启动-01)."""

    def setUp(self):
        _groups.clear()
        stream_mod._idle_sleeping = False
        stream_mod._wake_pending = False
        stream_mod._last_round_idle = False
        stream_mod._wake_event.clear()

    def tearDown(self):
        _groups.clear()
        stream_mod._idle_sleeping = False
        stream_mod._wake_pending = False
        stream_mod._last_round_idle = False
        stream_mod._wake_event.clear()

    def _drive_one_sleep(self, idle, waits, sleeps):
        """Run one real `push_loop` round, aborting inside the sleep it picks."""
        def body(t0, tick=None):
            stream_mod._last_round_idle = idle
            return 8.0

        def wait_spy(_timeout):
            waits.append(_timeout)
            raise _LoopStop()

        def sleep_spy(seconds):
            sleeps.append(seconds)
            raise _LoopStop()

        with patch.object(stream_mod, '_push_once', side_effect=body), \
             patch.object(stream_mod, 'tick_interval', return_value=8), \
             patch.object(stream_mod, '_wake_event') as ev, \
             patch.object(stream_mod.time, 'sleep', side_effect=sleep_spy):
            ev.wait.side_effect = wait_spy
            with self.assertRaises(_LoopStop):
                stream_mod.push_loop()

    def test_idle_round_uses_an_interruptible_wait(self):
        waits, sleeps = [], []
        self._drive_one_sleep(idle=True, waits=waits, sleeps=sleeps)
        self.assertEqual(waits, [8.0])          # event.wait(timeout=delay)
        self.assertEqual(sleeps, [])            # never a hard sleep when idle

    def test_active_round_uses_a_hard_sleep_never_interruptible(self):
        """No-burst: a round with live demand keeps the hard grid sleep, so a
        wake request can never shorten the round-start spacing below one tick."""
        waits, sleeps = [], []
        self._drive_one_sleep(idle=False, waits=waits, sleeps=sleeps)
        self.assertEqual(sleeps, [8.0])         # hard grid sleep
        self.assertEqual(waits, [])             # no wake window at all

    def test_wake_request_is_remembered_when_not_idle_sleeping(self):
        """Lost-wakeup guard: a wake arriving while not idle-sleeping is kept
        for the next idle wait, but must not interrupt anything now."""
        with patch.object(stream_mod, '_wake_event') as ev:
            stream_mod._wake_push_loop()
        ev.set.assert_not_called()
        self.assertTrue(stream_mod._wake_pending)

    def test_create_group_wakes_an_idle_loop(self):
        stream_mod._idle_sleeping = True
        sid, err = create_group(['sh600519'], ['quote'])
        self.assertIsNone(err)
        self.assertTrue(stream_mod._wake_event.is_set())
        destroy_group(sid)

    def test_new_connection_wakes_an_idle_loop(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        handler = StreamHandler.__new__(StreamHandler)
        handler.send_response = lambda *a, **k: None
        handler.send_header = lambda *a, **k: None
        handler.end_headers = lambda *a, **k: None
        handler.connection = Mock()
        handler.close_connection = False
        stream_mod._idle_sleeping = True
        with patch.object(stream_mod, '_SSEConn', _FakeSSEConn), \
             patch.object(stream_mod, '_wake_push_loop') as wake:
            handler._serve_sse(sid)
        wake.assert_called_once()

    def test_a_new_subscription_refreshes_without_waiting_the_grid(self):
        """The first round sleeps 8s; a subscription created during that wait
        must start the next round in far less than the grid."""
        starts = []
        first_round = threading.Event()

        def body(t0, tick=None):
            starts.append(time.monotonic())
            stream_mod._last_round_idle = True  # no live conns in this test
            if len(starts) == 1:
                first_round.set()
                return 8.0                      # the whole L1 grid
            raise _LoopStop()

        def run():
            try:
                with patch.object(stream_mod, '_push_once', side_effect=body), \
                     patch.object(stream_mod, 'tick_interval', return_value=8):
                    stream_mod.push_loop()
            except _LoopStop:
                pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        try:
            self.assertTrue(first_round.wait(2.0))
            time.sleep(0.05)                    # first round enters its idle wait
            sid, err = create_group(['sh600519'], ['quote'])
            self.assertIsNone(err)
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive())      # round 2 ran instead of sleeping 8s
            self.assertGreaterEqual(len(starts), 2)
            self.assertLess(starts[1] - starts[0], 1.0)   # ≪ the 8s grid
        finally:
            stream_mod._wake_event.set()        # release any wait before teardown


class ColdFirstRefreshTests(unittest.TestCase):
    """Optional item: the process's FIRST refresh-bearing round is exempt from
    degraded/slip (a one-off cold path, not a degradation), while every later
    overrun is still counted and empty rounds do not consume the exemption."""

    def setUp(self):
        _groups.clear()
        stream_mod._first_refresh_done = False
        stream_mod._last_round_idle = False
        stream_mod._idle_sleeping = False
        stream_mod._wake_pending = False
        stream_mod._wake_event.clear()

    def tearDown(self):
        _groups.clear()
        stream_mod._first_refresh_done = False
        stream_mod._last_round_idle = False
        stream_mod._idle_sleeping = False
        stream_mod._wake_pending = False
        stream_mod._wake_event.clear()

    @staticmethod
    def _slow(codes, now=None, fields=None, tick=None, deadline=None):
        time.sleep(0.05)
        return {}

    @staticmethod
    def _counts():
        snap = stream_mod.metrics.snapshot()
        return (snap['stream_tick_degraded_total'],
                snap['stream_tick_slip_total'])

    def test_first_refresh_over_budget_is_exempt_but_the_next_is_counted(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())
        with patch.object(stream_mod, '_refresh_pool', side_effect=self._slow), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, 'tick_interval', return_value=0.02):
            before = self._counts()
            stream_mod._push_once(t0=time.time(), tick=0.02)   # cold first
            after_first = self._counts()
            stream_mod._push_once(t0=time.time(), tick=0.02)   # warm next
            after_second = self._counts()
        self.assertEqual(after_first, before)                   # exempt
        self.assertEqual(after_second[0], after_first[0] + 1)   # degraded counted
        self.assertEqual(after_second[1], after_first[1] + 1)   # slip counted

    def test_empty_rounds_do_not_consume_the_exemption(self):
        with patch.object(stream_mod, 'tick_interval', return_value=0.02):
            stream_mod._push_once(t0=time.time(), tick=0.02)    # no live demand
        self.assertFalse(stream_mod._first_refresh_done)


class TickThrottleTests(unittest.TestCase):
    """BUG-P6C-01 root cause 4 + BUG-P6C-06: round starts are pinned to the
    integer grid ``t0 + k×tick``.  The old `0.25×tick` floor re-ran 2 s after
    an over-tick round (the "2 s back-to-back duplicate frame") behind a
    12–17 s stall; on the grid the *round-start* spacing is never shorter than
    one tick.

    ★ BUG-冷启动-01: the ``starts`` lists below are round **starts**, so the
    assertions are the true invariant (round start → round start ≥ 1 tick).
    Frames are emitted at the round **end**, so their arrival spacing is
    ``tick − dur_k + dur_{k+1}`` and can dip below a tick in a cold→warm
    transition; that is not asserted here.  The old test text claimed an
    inter-*frame* floor of one tick, which the measured 0.535–0.623 s cold
    first gap (tick=4) falsified."""

    def test_within_budget_sleeps_to_the_next_grid_point(self):
        # duration 3 s ≤ 0.8×8 ⇒ sleep to t0 + tick (BR-STR-27): 5 s
        self.assertEqual(_tick_sleep_seconds(0.0, 8, 3.0), 5.0)

    def test_over_budget_within_the_tick_still_lands_on_the_grid(self):
        # duration 7 s > 0.8×8: still the t0 + tick grid point ⇒ 1 s
        self.assertEqual(_tick_sleep_seconds(0.0, 8, 7.0), 1.0)

    def test_overrunning_tick_slips_a_whole_tick(self):
        # duration 9 s > tick ⇒ slip to t0 + 2×tick; never a 2 s re-run
        self.assertEqual(_tick_sleep_seconds(0.0, 8, 9.0), 7.0)

    def test_exact_tick_overrun_never_re_runs_immediately(self):
        # duration exactly one tick ⇒ next grid point (k = 2), not k = 1
        self.assertEqual(_tick_sleep_seconds(0.0, 8, 8.0), 8.0)

    def test_off_hours_tick_scales_with_the_interval(self):
        self.assertEqual(_tick_sleep_seconds(0.0, 120, 5.0), 115.0)
        self.assertEqual(_tick_sleep_seconds(0.0, 120, 130.0), 110.0)

    def test_delay_always_reaches_the_next_grid_point(self):
        tick = 8
        for elapsed in (0.0, 0.5, 3.0, 6.4, 7.99, 8.0, 8.5, 15.99, 16.0, 40.0):
            delay = _tick_sleep_seconds(0.0, tick, elapsed)
            next_start = elapsed + delay
            self.assertGreater(delay, 0.0, f'elapsed={elapsed}')   # never burst
            self.assertAlmostEqual(next_start / tick,
                                   round(next_start / tick), places=6,
                                   msg=f'elapsed={elapsed} off the tick grid')

    def test_simulated_target_load_stays_on_the_8s_grid(self):
        """<20-code steady state: round starts land on the 8 s grid.

        NB: `starts` records round **starts** (not frame arrivals) — the real
        BUG-冷启动-01 invariant.  Frame arrival spacing is derived later from
        these starts + the refresh durations and is not bounded by this test.
        """
        tick = 8
        starts, t = [], 0.0
        for duration in (5.5, 5.4, 5.6, 0.2, 5.5, 5.5):    # refresh cost jitter
            starts.append(t)
            t += duration + _tick_sleep_seconds(t, tick, t + duration)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(tick * 0.8 <= g <= tick * 1.2 for g in gaps), gaps)

    def test_simulated_overrun_is_bounded_never_bursty(self):
        """200-code degradation: round-start gaps may double, never < tick.

        `starts` are round starts, so `g >= tick` is the grid invariant —
        **not** a promise about frame arrival spacing (a frame leaves at the
        round end, so a cold→warm duration swing can still put two *frames*
        less than a tick apart; `_broadcast` dedup drops the unchanged ones).
        """
        tick = 8
        starts, t = [], 0.0
        for duration in (9.0, 15.0, 7.0, 12.0, 9.5):
            starts.append(t)
            t += duration + _tick_sleep_seconds(t, tick, t + duration)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        # the true invariant: every round START lands on the integer grid…
        self.assertTrue(all(abs(s / tick - round(s / tick)) < 1e-9
                            for s in starts), starts)
        self.assertTrue(all(g >= tick for g in gaps), gaps)      # ⇒ starts ≥ 1 tick
        self.assertTrue(all(g <= 2 * tick for g in gaps), gaps)  # bounded slip


class UnderscoreKeyTests(unittest.TestCase):
    """BR-STR-22 / AR-7 (updated by S2-1): the handler's reserved `_`-prefixed
    keys never become stock items — they are surfaced as frame metadata."""

    def tearDown(self):
        _groups.clear()

    def test_errors_key_becomes_frame_metadata_never_a_code(self):
        def fake_handler(cs, deadline=None):
            return {'sh600519': {'name': 'x'},
                    '_errors': {'sh600519': 'upstream_timeout'}}

        with patch.dict(stream_mod._FIELD_HANDLERS, {'quote': fake_handler},
                        clear=True):
            snap = _refresh_pool(['sh600519'])

        # kept for the frame (was dropped) — but still not a code key
        self.assertEqual(snap['_errors'], {'sh600519': 'upstream_timeout'})
        self.assertEqual(set(snap) - {'_errors'}, {'sh600519'})
        frame = _build_frame(snap, frozenset({'sh600519'}), ('quote',))
        data = json.loads(frame)
        self.assertEqual(set(data['items']), {'sh600519'})
        self.assertEqual(data['errors'], {'sh600519': 'upstream_timeout'})
        self.assertEqual(data['missing'], [])        # has data ⇒ not missing

    def test_missing_upstream_failure_is_distinguishable_from_no_data(self):
        """The client can tell upstream failure (in `errors`) from a code that
        simply has no cached data yet (in `missing`, absent from `errors`)."""
        def fake_handler(cs, deadline=None):
            return {'sh600519': None,
                    '_errors': {'sh600519': 'upstream_error'}}

        with patch.dict(stream_mod._FIELD_HANDLERS, {'quote': fake_handler},
                        clear=True):
            snap = _refresh_pool(['sh600519', 'sz000001'])

        frame = _build_frame(snap, frozenset({'sh600519', 'sz000001'}), ('quote',))
        data = json.loads(frame)
        self.assertEqual(data['missing'], ['sh600519', 'sz000001'])
        self.assertEqual(data['errors'], {'sh600519': 'upstream_error'})
        self.assertNotIn('sz000001', data['errors'])   # no data, no failure


class MaxGroupsTests(unittest.TestCase):
    """STREAM-T20 / BR-STR-29: exceeding MAX_GROUPS is a 400 failure mode."""

    def tearDown(self):
        _groups.clear()

    def test_max_groups_returns_error(self):
        with patch.object(stream_mod, 'MAX_GROUPS', 2):
            self.assertIsNone(create_group(['sh600519'], None)[1])
            self.assertIsNone(create_group(['sz000001'], None)[1])
            sid, err = create_group(['sz000002'], None)
            self.assertIsNone(sid)
            self.assertEqual(err, 'too many groups (max 2)')


class DestroyVsRegisterTests(unittest.TestCase):
    """P2-7: a group destroyed between get_group() and g.conns.add() must not
    leave the connection attached / counted."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()
        with stream_mod._conn_count_lock:
            stream_mod._conn_count = 0

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()
        with stream_mod._conn_count_lock:
            stream_mod._conn_count = 0

    def test_destroy_between_register_and_attach(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        real_get = stream_mod.get_group
        captured = {}

        def get_then_destroy(s):
            g = real_get(s)
            captured['g'] = g
            destroy_group(s)          # destroy before conns.add
            return g

        handler = StreamHandler.__new__(StreamHandler)
        sent = []
        handler._send_json = lambda status, obj: sent.append((status, obj))

        with patch.object(stream_mod, 'get_group', side_effect=get_then_destroy):
            handler._serve_sse(sid)   # must not block

        self.assertEqual(sent, [(404, {'error': 'subscription not found'})])
        self.assertEqual(captured['g'].conns, set())
        with stream_mod._conn_count_lock:
            self.assertEqual(stream_mod._conn_count, 0)


class ReadJsonBodyBudgetTests(unittest.TestCase):
    """BR-STR-32 / STREAM-T22: 5s read budget, restored in finally; invalid
    Content-Length never touches the socket."""

    def _handler(self, cl, connection):
        h = StreamHandler.__new__(StreamHandler)
        h.headers = {'Content-Length': cl}
        h.timeout = 30
        h.connection = connection
        h.rfile = Mock()
        return h

    def test_read_budget_set_and_restored(self):
        conn = Mock()
        conn.gettimeout.return_value = 30
        h = self._handler('2', conn)
        h.rfile.read.return_value = b'{}'
        self.assertEqual(h._read_json_body(), {})
        conn.settimeout.assert_any_call(config.MGMT_BODY_TIMEOUT)
        conn.settimeout.assert_any_call(30)

    def test_read_timeout_returns_none_and_restores(self):
        conn = Mock()
        conn.gettimeout.return_value = 30
        h = self._handler('2', conn)
        h.rfile.read.side_effect = socket.timeout()
        self.assertIsNone(h._read_json_body())
        conn.settimeout.assert_called_with(30)

    def test_invalid_cl_does_not_touch_connection(self):
        conn = Mock()
        h = self._handler('70000', conn)
        self.assertIsNone(h._read_json_body())
        h.rfile.read.assert_not_called()
        conn.settimeout.assert_not_called()


class _RacingQueue(queue.Queue):
    """Test double for the put/acquire window (P1-1).

    A real SSE handler blocked in ``q.get()`` is woken by ``put_nowait``'s
    ``not_full.notify()`` and can consume → ``_frame_release`` on another core
    before the producer runs its next statement. This queue reproduces that
    interleaving *inside* ``put_nowait``: the item is enqueued and then
    immediately consumed and released, i.e. before ``put_nowait`` returns.
    """

    def put_nowait(self, item):
        super().put_nowait(item)
        got = super().get_nowait()
        if isinstance(got, _Frame):
            _frame_release(got)


def _ledger_is_consistent():
    """P1-1 acceptance: `_queue_bytes == Σ_{refs>0} size` (the group ledger is
    that same sum partitioned by sid, so equality is the white-box proxy)."""
    return (stream_mod._queue_bytes == sum(stream_mod._group_bytes.values())
            and stream_mod._queue_bytes >= 0
            and stream_mod._live_frames >= 0)


class FrameBillingRaceTests(unittest.TestCase):
    """P1-1: billing must happen BEFORE the frame becomes visible to consumers.

    With the old put-then-acquire order a consumer landing in the window
    released at refs==0 (idempotent short-circuit) and the following acquire
    stranded a ghost frame — a permanent, self-unhealing drift of _queue_bytes /
    _group_bytes / _live_frames that made _reserve_for evict other groups' real
    frames (stream.md §4.2 "refs == number of queues holding the frame").
    """

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    @staticmethod
    def _racing_conns(sid, n):
        g = get_group(sid)
        conns = []
        for _ in range(n):
            c = _SSEConn()
            c.q = _RacingQueue(maxsize=8)
            with g.conns_lock:
                g.conns.add(c)
            conns.append(c)
        return conns

    def test_consumer_in_put_window_leaves_no_ghost_frame(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        conns = self._racing_conns(sid, 1)

        _broadcast({'sh600519': {'quote': {'name': 'x'}}})

        self.assertEqual(stream_mod._queue_bytes, 0)
        self.assertEqual(stream_mod._live_frames, 0)
        self.assertIsNone(stream_mod._group_bytes.get(sid))
        self.assertEqual(conns[0].q.qsize(), 0)      # consumed inside the put
        self.assertTrue(_ledger_is_consistent())

    def test_repeated_ticks_do_not_drift_monotonically(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        conns = self._racing_conns(sid, 6)

        for _ in range(20):
            _broadcast({'sh600519': {'quote': {'name': 'x'}}})

        self.assertEqual(stream_mod._queue_bytes, 0)   # no accumulation
        self.assertEqual(stream_mod._live_frames, 0)
        self.assertNotIn(sid, stream_mod._group_bytes)
        self.assertTrue(all(c.q.qsize() == 0 for c in conns))
        self.assertTrue(_ledger_is_consistent())

    def test_retained_frames_are_still_billed(self):
        """Guard: the fix must not stop billing frames that ARE retained."""
        sid, _ = create_group(['sh600519'], ['quote'])
        g = get_group(sid)
        conns = []
        for _ in range(3):
            c = _SSEConn()                            # plain (non-racing) queue
            with g.conns_lock:
                g.conns.add(c)
            conns.append(c)

        _broadcast({'sh600519': {'quote': {'name': 'x'}}})

        held = [f for c in conns for f in list(c.q.queue) if isinstance(f, _Frame)]
        self.assertEqual(len(held), 3)
        self.assertEqual(len({id(f) for f in held}), 1)     # one distinct frame
        self.assertEqual(held[0].refs, 3)                   # refs == holders
        self.assertEqual(stream_mod._queue_bytes, held[0].size)
        self.assertEqual(stream_mod._live_frames, 1)
        self.assertTrue(_ledger_is_consistent())


class FrameBudgetConsistencyTests(unittest.TestCase):
    """P1-4 + S2-2: the queue byte budget and the legal subscription set are
    mutually consistent — a single group's 8-deep window fits, and the
    cross-group steady-state working set **plus one full frame** fits, so a
    legal boundary configuration can never force `_broadcast` to evict a real
    frame every tick (AC-E5)."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    @staticmethod
    def _f_max():
        return config.stream_frame_bytes(config.MAX_CODES_PER_SUB,
                                         config.STREAM_FIELDS_PER_FRAME)

    def test_budget_covers_single_group_8_deep_window(self):
        self.assertLessEqual(8 * self._f_max(),
                             config.STREAM_QUEUE_BYTES_BUDGET)

    def test_frame_model_is_the_single_source(self):
        self.assertEqual(config.STREAM_FIELDS_PER_FRAME, 3)
        self.assertEqual(config.stream_frame_bytes(2, 3),
                         2 * 3 * config.STREAM_FRAME_BYTES_PER_FIELD)

    def test_admission_cap_leaves_single_frame_margin(self):
        """T5 (S2-2): the old cap admitted 9 full groups whose working set
        (124 MiB) left only ~9 MB of slack < F_max (13.8 MB) ⇒ every tick
        evicted one real frame per group.  Admission must instead keep one full
        frame of headroom."""
        f_max = self._f_max()
        budget = config.STREAM_QUEUE_BYTES_BUDGET
        self.assertGreaterEqual(budget // f_max, 3)
        codes = [f'sh{i:06d}' for i in range(config.MAX_CODES_PER_SUB)]

        admitted = 0
        while True:
            sid, err = create_group(codes, None)
            if err is not None:
                self.assertIn('frame budget', err)
                break
            self.assertIsNotNone(sid)
            admitted += 1
        with stream_mod._groups_lock:
            working = _projected_frame_bytes_unlocked()
            largest = stream_mod._max_group_frame_bytes_unlocked()

        # ★ the invariant the old cap violated: working set + one full frame fits
        self.assertLessEqual(working + largest, budget)
        # …which costs exactly one slot versus the old `budget // F_max`
        self.assertEqual(admitted, budget // f_max - 1)

    def test_broadcast_at_the_admission_boundary_drops_nothing(self):
        """T5 (S2-2): drive the real `_broadcast` at the boundary with consumers
        caught up and assert zero frame drops.

        The sizes are scaled down (patched byte model + budget) so the *actual*
        frames are comparable to the model and `_reserve_for` is genuinely
        exercised.  At the old cap one more group would be admitted and the
        tick's frames would overflow the budget ⇒ drops."""
        per_field = 400
        n_codes = 4
        fields = ('quote', 'fundflow', 'timeline')
        f_group = n_codes * len(fields) * per_field          # 4800
        budget = 5 * f_group                                 # 24000
        codes = [f'sh{i:06d}' for i in range(n_codes)]
        snapshot = {c: {f: {'v': 'x' * per_field} for f in fields}
                    for c in codes}

        with patch.object(config, 'STREAM_FRAME_BYTES_PER_FIELD', per_field), \
             patch.object(stream_mod, 'STREAM_QUEUE_BYTES_BUDGET', budget):
            sids = []
            while True:
                sid, err = create_group(codes, None)
                if err:
                    break
                sids.append(sid)
            self.assertEqual(len(sids), budget // f_group - 1)   # 4 (old: 5)

            for sid in sids:                       # one live conn per group
                g = get_group(sid)
                c = _SSEConn()
                with g.conns_lock:
                    g.conns.add(c)

            before = stream_mod.metrics.snapshot()['stream_frame_dropped_total']
            for _ in range(2):                     # two steady-state ticks
                for sid in sids:
                    _drain_conn_queue(next(iter(get_group(sid).conns)))
                _broadcast(snapshot)
            after = stream_mod.metrics.snapshot()['stream_frame_dropped_total']

            self.assertEqual(after, before)        # ★ 0 drops
            self.assertLessEqual(stream_mod._queue_bytes, budget)
            for sid in sids:
                _drain_conn_queue(next(iter(get_group(sid).conns)))

    def test_patch_group_honours_frame_budget_with_margin(self):
        f_max = self._f_max()
        codes = [f'sh{i:06d}' for i in range(config.MAX_CODES_PER_SUB)]
        # S2-2: a single max group already needs 2×F_max under the margin rule.
        budget = 2 * f_max + 512 * 1024
        with patch.object(stream_mod, 'STREAM_QUEUE_BYTES_BUDGET', budget):
            self.assertIsNone(create_group(codes, None)[1])
            sid, err = create_group(['sz000001'], None)         # tiny
            self.assertIsNone(err)
            ok, err = patch_group(sid, add=codes[:config.MAX_CODES_PER_SUB - 1],
                                  remove=[])
            self.assertFalse(ok)
            self.assertIn('frame budget', err)
            self.assertEqual(len(get_group(sid).codes), 1)      # unchanged


class CursorRotationTests(unittest.TestCase):
    """STREAM-T14: the REAL round-robin primitives (not patched out) advance the
    cursor across ticks — slices never repeat, they cover the whole pool within
    ceil(n/|slice|) ticks, and they wrap exactly after a full cycle."""

    N = 200
    STEP = 106           # coverage_codes for tick=8: int(0.8*8*20/0.3)//4

    def setUp(self):
        _groups.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)
        self.codes = [f'sh{600000 + i:06d}' for i in range(self.N)]

    def tearDown(self):
        _groups.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    def test_ticks_advance_cover_and_wrap(self):
        real_slice = stream_mod._prefetch_slice    # the real primitive
        captured = []

        def spy(pool, lock, key, size):
            out = real_slice(pool, lock, key, size)
            captured.append(tuple(out[0]))
            return out

        handlers = {f: (lambda cs, deadline=None: {c: {'v': 1} for c in cs})
                    for f in ('quote', 'fundflow', 'timeline')}
        cycle = self.N // _gcd(self.STEP, self.N)   # 200/gcd(106,200) = 100
        ticks = cycle + 1                           # full cycle, plus 1 to wrap
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, 'tick_interval', return_value=8), \
             patch.object(stream_mod, '_prefetch_slice', side_effect=spy):
            for _ in range(ticks):
                _refresh_pool(self.codes)

        self.assertEqual(len(captured), ticks)
        self.assertTrue(all(len(sl) == self.STEP for sl in captured))
        for i, sl in enumerate(captured[:cycle]):
            self.assertEqual(sl, self._rotated((i * self.STEP) % self.N))
        # a full cycle wraps exactly: the next tick repeats the 1st slice
        self.assertEqual(captured[cycle], captured[0])
        # ceil(200/106) = 2 ticks hand out every code at least once
        covered = set()
        for sl in captured[:_n_ceil(self.N, self.STEP)]:
            covered.update(sl)
        self.assertEqual(covered, set(self.codes))
        # round-robin, not a stuck cursor
        for a, b in zip(captured, captured[1:]):
            self.assertNotEqual(a, b)

    def _rotated(self, start):
        n = self.N
        return tuple(self.codes[(start + i) % n] for i in range(self.STEP))


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _n_ceil(a, b):
    """ceil(a/b) — mirror of stream._refresh_pool's lag arithmetic."""
    return -(-a // b)


def _stock_api():
    import china_finance_rss.stock_api as stock_api_mod
    return stock_api_mod


class RefreshDeadlineTests(unittest.TestCase):
    """P1-1: all field phases share ONE tick deadline.  Previously each handler
    fell back to `_BATCH_BUDGET_REST` (15 s), so three serial phases could block
    the push thread for 45 s and black out every SSE connection."""

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    def test_all_fields_share_one_bounded_deadline(self):
        seen = []

        def mk(name):
            def _h(cs, deadline=None):
                seen.append((name, deadline))
                return {c: {'v': 1} for c in cs}
            return _h

        before = time.time()
        with patch.dict(stream_mod._FIELD_HANDLERS,
                        {f: mk(f) for f in ('quote', 'fundflow', 'timeline')}), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            _refresh_pool(['sh600519'])
        after = time.time()

        self.assertEqual(len(seen), 3)
        deadlines = {d for _n, d in seen}
        self.assertEqual(len(deadlines), 1)          # one shared budget
        deadline = deadlines.pop()
        self.assertIsNotNone(deadline)
        self.assertGreaterEqual(deadline, before)
        self.assertLessEqual(deadline, after + 0.8 * 8)
        # …and it is the tick fraction, not the 15 s REST fallback
        self.assertLess(deadline - before, 15.0)

    def test_over_budget_skips_remaining_fields_and_marks_errors(self):
        called = []

        def slow(cs, deadline=None):
            called.append('quote')
            time.sleep(0.35)                     # overrun the injected budget
            return {c: {'v': 1} for c in cs}

        def mk(name):
            def _h(cs, deadline=None):
                called.append(name)
                return {c: {'v': 1} for c in cs}
            return _h

        handlers = {'quote': slow, 'fundflow': mk('fundflow'),
                    'timeline': mk('timeline')}
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            snap = _refresh_pool(['sh600519'], deadline=time.time() + 0.25)

        self.assertEqual(called, ['quote'])          # remaining phases skipped
        self.assertIn('quote', snap['sh600519'])     # the phase that ran is kept
        self.assertEqual(snap['_errors']['sh600519'], 'tick_budget_exceeded')


class LastKnownCarryForwardTests(unittest.TestCase):
    """P1-4: C2 frames carry the last known value for un-refreshed codes (marked
    `stale`) instead of pure null, so a large subscription stays usable."""

    def setUp(self):
        _groups.clear()
        with stream_mod._last_known_lock:
            stream_mod._last_known.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    def tearDown(self):
        _groups.clear()
        with stream_mod._last_known_lock:
            stream_mod._last_known.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    def test_carry_forward_fills_value_and_marks_stale(self):
        merged, stale = stream_mod._carry_forward(
            {'sh600519': {'quote': {'name': 'x'}}},
            {'sh600519', 'sz000001'}, ('quote',))
        self.assertEqual(stale, set())               # nothing known for sz000001
        self.assertNotIn('sz000001', merged)         # no fabricated value

        merged, stale = stream_mod._carry_forward(
            {'sz000001': {'quote': {'name': 'y'}}},
            {'sh600519', 'sz000001'}, ('quote',))
        self.assertEqual(merged['sh600519']['quote'], {'name': 'x'})
        self.assertEqual(stale, {'sh600519'})        # carried ⇒ stale, not missing

    def test_frame_marks_stale_but_not_missing(self):
        snapshot = {'sh600519': {'quote': {'name': 'x'}},
                    'sz000001': {'quote': {'name': 'y'}},
                    '_stale': {'sz000001'}}
        data = json.loads(_build_frame(
            snapshot, frozenset({'sh600519', 'sz000001'}), ('quote',)))
        self.assertEqual(data['missing'], [])
        self.assertEqual(data['missing_count'], 0)
        self.assertEqual(data['stale'], ['sz000001'])
        self.assertEqual(data['stale_count'], 1)
        self.assertEqual(data['items']['sz000001']['quote'], {'name': 'y'})

    def test_scheduled_tick_carries_last_known_across_c2_ticks(self):
        # 200 codes × 3 fields: 800 > coverage=426 ⇒ C2 rotation (106/tick)
        fields = ('quote', 'fundflow', 'timeline')
        codes = [f'sh{600000 + i:06d}'
                 for i in range(config.MAX_CODES_PER_SUB)]
        sid, _ = create_group(codes, list(fields))
        g = get_group(sid)
        with g.conns_lock:
            g.conns.add(_SSEConn())

        snaps = []
        handlers = {f: (lambda cs, deadline=None:
                        {c: {'v': 1} for c in cs}) for f in fields}
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(stream_mod, 'cached_batch', return_value={}), \
             patch.object(stream_mod, '_broadcast',
                          side_effect=lambda s: snaps.append(dict(s))), \
             patch.object(stream_mod, 'tick_interval', return_value=8):
            stream_mod._push_once(t0=time.time())
            stream_mod._push_once(t0=time.time())

        f1 = json.loads(_build_frame(snaps[0], frozenset(codes), fields))
        f2 = json.loads(_build_frame(snaps[1], frozenset(codes), fields))
        self.assertEqual(f1['missing_count'], 200 - 106)    # coverage_codes=106
        self.assertLess(f2['missing_count'], f1['missing_count'])
        self.assertGreater(f2['stale_count'], 0)
        # a code missing on tick 1 is refreshed on tick 2; one missing on tick 2
        # is the tick-1 value carried forward (never null)
        self.assertEqual(f2['items'][f1['missing'][0]]['quote'], {'v': 1})
        self.assertEqual(f2['items'][f2['stale'][0]]['quote'], {'v': 1})


class SSECloseConnectionTests(unittest.TestCase):
    """P1-3: `_serve_sse` must mark the connection non-keep-alive on every exit
    path so `handle()` cannot re-enter and block ~40 s on rfile.readline()."""

    def setUp(self):
        _groups.clear()

    def tearDown(self):
        _groups.clear()

    def test_exit_sets_close_connection(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        handler = StreamHandler.__new__(StreamHandler)
        handler.path = f'/stream/quote/{sid}'
        handler.connection = Mock()
        handler.wfile = Mock()
        handler.send_response = lambda *a, **k: None
        handler.send_header = lambda *a, **k: None
        handler.end_headers = lambda *a, **k: None
        handler.close_connection = False
        fake = _SSEConn()
        fake.q.put_nowait(None)              # make the loop exit immediately
        with patch.object(stream_mod, '_SSEConn', return_value=fake), \
             patch.object(stream_mod, '_register_conn', return_value=True), \
             patch.object(stream_mod, '_release_conn'):
            handler._serve_sse(sid)
        self.assertTrue(handler.close_connection)
        self.assertTrue(fake.closed)             # conn retired

    def test_log_error_suppresses_timeout_noise(self):
        handler = StreamHandler.__new__(StreamHandler)
        logged = []
        handler.log_message = lambda *a, **k: logged.append(a)
        handler.log_error('Request timed out: %r', object())
        self.assertEqual(logged, [])
        handler.log_error('Other error: %r', object())
        self.assertEqual(len(logged), 1)


class BroadcastGhostReserveTests(unittest.TestCase):
    """P2: a frame that will be enqueued to nobody (all conns closed) must not
    evict another group's real frame via `_reserve_for`."""

    def setUp(self):
        _groups.clear()
        _reset_frame_accounting()

    def tearDown(self):
        _groups.clear()
        _reset_frame_accounting()

    def test_all_closed_conns_skip_build_and_reserve(self):
        sid, _ = create_group(['sh600519'], ['quote'])
        g = get_group(sid)
        conn = _SSEConn()
        conn.closed = True
        with g.conns_lock:
            g.conns.add(conn)
        with patch.object(stream_mod, '_reserve_for') as res, \
             patch.object(stream_mod, '_build_frame',
                          wraps=stream_mod._build_frame) as build:
            _broadcast({'sh600519': {'quote': {'name': 'x'}}})
        res.assert_not_called()
        build.assert_not_called()
        self.assertEqual(conn.q.qsize(), 0)


class RefreshEpochStreamTests(unittest.TestCase):
    """修复 quote 相位耦合: the domain that sets the tick is refreshed每拍.

    At L0 a domain's cache TTL equals the tick (4 s), and a round writes its
    entry δ s *after* the round start, so the next round would find a
    ``tick − δ``-old entry and skip the upstream call — an effective 8 s cadence
    for a nominal 4 s one.  `_refresh_pool` hands the round start to the domain
    that sets the tick as its ``refresh_epoch``; a slower domain (TTL > tick)
    keeps its TTL interleave so its upstream load does not double.
    """

    TIERS = {'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300}

    def setUp(self):
        _groups.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    def tearDown(self):
        _groups.clear()
        with _stock_api()._prefetch_cursor_lock:
            _stock_api()._prefetch_cursor.pop('stream_refresh', None)

    @staticmethod
    def _capture():
        seen = {}

        def mk(name):
            def _h(cs, deadline=None, refresh_epoch=None):
                seen[name] = refresh_epoch
                return {c: {'v': name} for c in cs}
            return _h

        return seen, {f: mk(f) for f in ('quote', 'fundflow', 'timeline')}

    def test_quote_at_l0_gets_the_round_start_as_its_floor(self):
        seen, handlers = self._capture()
        t0 = time.time()
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(config, '_trading_tiers', return_value=self.TIERS), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            _refresh_pool(['sh600519'], t0, ['quote'])
        self.assertEqual(seen['quote'], t0)

    def test_a_domain_with_a_longer_ttl_keeps_its_interleave(self):
        seen, handlers = self._capture()
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(config, '_trading_tiers', return_value=self.TIERS), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            _refresh_pool(['sh600519'], time.time(),
                          ['quote', 'fundflow', 'timeline'])
        self.assertIsNotNone(seen['quote'])     # 4 ≤ 4 ⇒ refreshed every tick
        self.assertIsNone(seen['fundflow'])     # 8 > 4 ⇒ cached on odd ticks
        self.assertIsNone(seen['timeline'])

    def test_direct_call_falls_back_to_wall_clock_for_the_floor(self):
        seen, handlers = self._capture()
        with patch.dict(stream_mod._FIELD_HANDLERS, handlers), \
             patch.object(config, '_trading_tiers', return_value=self.TIERS), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            _refresh_pool(['sh600519'])
        self.assertIsNotNone(seen['quote'])

    def test_legacy_handler_without_the_keyword_is_still_called(self):
        """The floor is an additive hint: a pre-epoch handler is unaffected."""
        called = []

        def legacy(cs, deadline=None):
            called.append(list(cs))
            return {c: {'v': 1} for c in cs}

        with patch.dict(stream_mod._FIELD_HANDLERS, {'quote': legacy},
                        clear=True), \
             patch.object(config, '_trading_tiers', return_value=self.TIERS), \
             patch.object(stream_mod, 'tick_interval', return_value=4):
            snap = _refresh_pool(['sh600519'])
        self.assertEqual(called, [['sh600519']])
        self.assertEqual(snap['sh600519']['quote'], {'v': 1})

    def test_every_production_handler_accepts_the_refresh_floor(self):
        """Guard: the tolerant call must never silently drop the floor in prod."""
        import inspect
        for field, handler in stream_mod._FIELD_HANDLERS.items():
            self.assertIn('refresh_epoch',
                          inspect.signature(handler).parameters,
                          f'{field} handler must accept refresh_epoch')

