"""SSE push server + subscription groups for short-line trading clients.

Layered with the REST scan path: clients scan the market via existing
REST endpoints (hotplate/plate/stock), then subscribe to a fixed watchlist
here. Every L1 tick the server refreshes the deduped code pool (mostly
in-memory cache hits, zero extra upstream load) and fans out a full-snapshot
frame to each connection.

Runs on its own port (STREAM_PORT, default 8054) so long-lived SSE
connections never starve the main HTTP worker pool.

Endpoints (port STREAM_PORT):
  POST   /stream/subscriptions         create group  {"codes":[...], "fields":[...]}
  GET    /stream/subscriptions/<sid>   group status
  PATCH  /stream/subscriptions/<sid>   mutate       {"add":[...],"remove":[...]}
  DELETE /stream/subscriptions/<sid>   destroy
  GET    /stream/quote/<sid>           SSE stream (event: quote, every L1 tick)
"""

import json
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import config
from config import (
    STREAM_PORT, VALID_STOCK_CODE,
    MAX_STREAM_CONNS, MAX_CODES_PER_SUB, MAX_DEDUP_CODES,
    STREAM_PING_INTERVAL, _trading_tiers,
)
from stock_api import (
    handle_cls_basic_infos, handle_cls_fundflow, handle_cls_timeline,
)

log = logging.getLogger('stream')

# field -> (handler, enabled-default)
_FIELD_HANDLERS = {
    'quote': handle_cls_basic_infos,
    'fundflow': handle_cls_fundflow,
    'timeline': handle_cls_timeline,
}

_groups = {}            # sid -> SubscriptionGroup
_groups_lock = threading.RLock()   # nested acquisition in CRUD paths
_conn_count = 0
_conn_count_lock = threading.Lock()


class SubscriptionGroup:
    """A named watchlist: codes + subscribed fields + live SSE connections."""

    def __init__(self, sid, codes, fields):
        self.sid = sid
        self.fields = fields
        self.codes = set(codes)
        self.conns = set()          # of _SSEConn
        self.conns_lock = threading.Lock()
        self.last_push_ts = 0.0
        self.created_ts = time.time()

    def payload_bytes(self):
        """Estimate of snapshot size for this group (deduped codes only)."""
        return len(self.codes) * 70 * 1024


def _new_sid():
    while True:
        sid = uuid.uuid4().hex[:12]
        with _groups_lock:
            if sid not in _groups:
                return sid


def _valid_fields(fields):
    """Return the intersection of requested fields with supported ones."""
    if not fields:
        return list(_FIELD_HANDLERS)
    out = []
    for f in fields:
        if f in _FIELD_HANDLERS and f not in out:
            out.append(f)
    return out or list(_FIELD_HANDLERS)


def _deduped_codes_unlocked():
    """Union of codes across all groups. Caller must hold _groups_lock."""
    codes = set()
    for g in _groups.values():
        codes |= g.codes
    return codes


def _deduped_codes():
    """Union of codes across all groups (bounds the refresh set)."""
    with _groups_lock:
        return _deduped_codes_unlocked()


def _refresh_pool(codes):
    """Build {code: {field: data}} for the deduped pool (cache-warm fetches).

    Fetches happen once per tick for the union of all subscriptions, then
    each connection receives only its own subset — CPU scales with the
    deduped pool, bandwidth with the number of connections.
    """
    result = {c: {} for c in codes}
    for field, handler in _FIELD_HANDLERS.items():
        fetched = handler(list(codes))
        if not fetched:
            continue
        for code, data in fetched.items():
            if data is not None and code in result:
                result[code][field] = data
    return result


def _build_frame(snapshot, g):
    """Full-snapshot SSE frame (data: {...}) for one group's codes+fields."""
    items = {}
    for code in g.codes:
        entry = snapshot.get(code)
        if not entry:
            continue
        items[code] = {k: entry[k] for k in g.fields if k in entry}
    if not items:
        return None
    payload = {'ts': int(time.time() * 1000), 'items': items}
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def tick_interval():
    """Push cadence = L1 tier (8s in trading, 120s off-hours)."""
    return _trading_tiers()['L1']


# ── connection / broadcast ─────────────────────────────────────────────────

class _SSEConn:
    """One live SSE client: queue drained by its handler thread."""

    def __init__(self):
        self.q = queue.Queue()
        self.closed = False


def _broadcast(snapshot):
    """Fan out a frame to every connection of every group."""
    now = time.time()
    with _groups_lock:
        groups = list(_groups.values())
    for g in groups:
        frame = _build_frame(snapshot, g)
        if frame is None:
            continue
        with g.conns_lock:
            conns = list(g.conns)
        for conn in conns:
            if conn.closed:
                continue
            try:
                conn.q.put_nowait(frame)
            except queue.Full:
                pass
        g.last_push_ts = now


def push_loop():
    """Background thread: refresh deduped pool every L1 tick, then fan out."""
    while True:
        try:
            tick = tick_interval()
            nxt = time.time() + tick
            codes = _deduped_codes()
            if codes:
                snapshot = _refresh_pool(codes)
                _broadcast(snapshot)
            delay = nxt - time.time()
            if delay > 0:
                time.sleep(delay)
        except Exception as e:
            log.error(f'[stream] push_loop error: {e}')
            time.sleep(1)


# ── group CRUD (used by HTTP handlers and tests) ───────────────────────────

def create_group(codes, fields):
    """Validate and create a subscription group. Returns (sid, error)."""
    if not codes:
        return None, 'codes required'
    if len(codes) > MAX_CODES_PER_SUB:
        return None, f'too many codes (max {MAX_CODES_PER_SUB})'
    seen = set()
    clean = []
    for c in codes:
        if not VALID_STOCK_CODE.match(c):
            return None, f'invalid stock code: {c}'
        if c not in seen:
            seen.add(c)
            clean.append(c)
    with _groups_lock:
        total = len(_deduped_codes_unlocked()) + len(clean)
        if total > MAX_DEDUP_CODES:
            return None, f'pool would exceed {MAX_DEDUP_CODES} codes'
        sid = _new_sid()
        _groups[sid] = SubscriptionGroup(sid, clean, _valid_fields(fields))
    log.info(f'[stream] group {sid} created: {len(clean)} codes, '
             f'fields={_groups[sid].fields}')
    return sid, None


def get_group(sid):
    with _groups_lock:
        return _groups.get(sid)


def patch_group(sid, add, remove):
    """Add/remove codes on a group. Returns (ok, error)."""
    g = get_group(sid)
    if g is None:
        return False, 'subscription not found'
    add = add or []
    remove = remove or []
    for c in add:
        if not VALID_STOCK_CODE.match(c):
            return False, f'invalid stock code: {c}'
    with _groups_lock:
        others = _deduped_codes_unlocked() - g.codes
        projected = len(others | (g.codes | set(add)) - set(remove))
        if projected > MAX_DEDUP_CODES:
            return False, f'pool would exceed {MAX_DEDUP_CODES} codes'
        if len(g.codes) + len(add) - len(set(remove)) > MAX_CODES_PER_SUB:
            return False, f'too many codes (max {MAX_CODES_PER_SUB})'
        g.codes = (g.codes | set(add)) - set(remove)
    log.info(f'[stream] group {sid} patched: +{len(add)} -{len(remove)} '
             f'=> {len(g.codes)} codes')
    return True, None


def destroy_group(sid):
    with _groups_lock:
        g = _groups.pop(sid, None)
    if g is None:
        return False
    with g.conns_lock:
        for conn in list(g.conns):
            conn.closed = True
            try:
                conn.q.put_nowait(None)  # wake handler to exit
            except queue.Full:
                pass
        g.conns.clear()
    log.info(f'[stream] group {sid} destroyed')
    return True


def _register_conn(conn):
    global _conn_count
    with _conn_count_lock:
        if _conn_count >= MAX_STREAM_CONNS:
            return False
        _conn_count += 1
    return True


def _release_conn():
    global _conn_count
    with _conn_count_lock:
        if _conn_count > 0:
            _conn_count -= 1


# ── HTTP layer ─────────────────────────────────────────────────────────────

class StreamHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'ChinaFinanceRSS/stream'

    def log_message(self, fmt, *args):
        log.info('[stream] %s - %s' % (self.address_string(), fmt % args))

    # -- management endpoints (short-lived) --

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length > 65536:
            return None
        body = self.rfile.read(length) if length else b''
        try:
            return json.loads(body.decode('utf-8')) if body else {}
        except Exception:
            return None

    def _send_json(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if urlparse(self.path).path != '/stream/subscriptions':
            self._send_json(404, {'error': 'not found'})
            return
        body = self._read_json_body()
        if body is None:
            self._send_json(400, {'error': 'invalid JSON body'})
            return
        sid, err = create_group(body.get('codes') or [], body.get('fields'))
        if err:
            self._send_json(400, {'error': err})
            return
        self._send_json(201, {'sid': sid, 'codes': sorted(get_group(sid).codes),
                              'fields': get_group(sid).fields})

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/stream/quote/'):
            self._serve_sse(path.rsplit('/', 1)[1])
            return
        if path.startswith('/stream/subscriptions/'):
            sid = path.rsplit('/', 1)[1]
            g = get_group(sid)
            if g is None:
                self._send_json(404, {'error': 'not found'})
                return
            body = json.dumps({
                'sid': g.sid, 'fields': g.fields,
                'codes': sorted(g.codes), 'conns': len(g.conns),
                'last_push_ts': g.last_push_ts,
                'created_ts': g.created_ts,
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(404, {'error': 'not found'})

    def do_PATCH(self):
        path = urlparse(self.path).path
        if not path.startswith('/stream/subscriptions/'):
            self._send_json(404, {'error': 'not found'})
            return
        sid = path.rsplit('/', 1)[1]
        body = self._read_json_body()
        if body is None:
            self._send_json(400, {'error': 'invalid JSON body'})
            return
        ok, err = patch_group(sid, body.get('add'), body.get('remove'))
        if not ok:
            self._send_json(404 if err == 'subscription not found' else 400,
                            {'error': err})
            return
        g = get_group(sid)
        self._send_json(200, {'sid': sid, 'codes': sorted(g.codes)})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith('/stream/subscriptions/'):
            self._send_json(404, {'error': 'not found'})
            return
        sid = path.rsplit('/', 1)[1]
        self._send_json(200, {'deleted': destroy_group(sid)})

    # -- SSE endpoint (long-lived) --

    def _serve_sse(self, sid):
        g = get_group(sid)
        if g is None:
            self._send_json(404, {'error': 'subscription not found'})
            return
        conn = _SSEConn()
        if not _register_conn(conn):
            self._send_json(503, {'error': 'too many stream connections'})
            return
        with g.conns_lock:
            g.conns.add(conn)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            while not conn.closed:
                try:
                    frame = conn.q.get(timeout=STREAM_PING_INTERVAL)
                    if frame is None:
                        break
                    self.wfile.write(
                        b'event: quote\nid: '
                        + str(int(time.time() * 1000)).encode()
                        + b'\ndata: ' + frame.encode('utf-8') + b'\n\n')
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(
                        b'event: ping\ndata: {}\n\n')
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            conn.closed = True
            with g.conns_lock:
                g.conns.discard(conn)
            _release_conn()


def make_stream_server(max_workers=None):
    """Build the stream HTTP server (BoundedThreadPoolServer for load shed)."""
    from server import BoundedThreadPoolServer
    max_workers = max_workers or (MAX_STREAM_CONNS + 10)
    return BoundedThreadPoolServer(('', STREAM_PORT), StreamHandler,
                                   max_workers=max_workers)


def run_stream_server():
    """Entry point for the stream server daemon thread."""
    srv = make_stream_server()
    log.info(f'[stream] SSE server on http://localhost:{STREAM_PORT}')
    log.info(f'[stream] limits: conns<={MAX_STREAM_CONNS} '
             f'codes/sub<={MAX_CODES_PER_SUB} dedup<={MAX_DEDUP_CODES}')
    srv.serve_forever()
