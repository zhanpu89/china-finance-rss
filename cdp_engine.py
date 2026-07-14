#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent CDP engine for financial data collection via Chrome DevTools Protocol.

Architecture:
  - One Chrome browser instance (auto-start on first use)
  - Each monitored site gets one persistent Page with its own WS connection
  - Background heartbeat thread per page: polls collected data, auto-reconnects
  - Thread-safe shared cache for API consumption (read from cache, never touch WS)

Compared to the old request-driven approach (create tab → navigate → wait → destroy),
this reduces API latency from 3-8s to <1ms and captures WebSocket frames.
"""

import atexit
import gc
import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse


CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')
_chrome_restart_lock = threading.RLock()  # RLock so full_chrome_restart→ensure_chrome doesn't deadlock
_last_chrome_restart = 0

API_KEY_MAP = {
    'emotion': 'market_sentiment',
    'articles': 'articles',
    'up_down': 'advance_decline',
    'tline': 'timeline',
    'refresh': 'live_refresh',
    'anchor': 'anchor',
    'basic': 'basic_info',
    'hot_plate': 'hot_plate',
    'index_stock_list': 'stock_ranking',
    'stock_ipo': 'stock_ipo',
    'bj_stock_info': 'bj_stock_info',
    'index/home': 'index_home',
    # Stock detail page APIs
    '/quote/stock/': 'stock_quote',           # real-time price / fundflow
    'stock/assoc_plate': 'stock_plate',       # related sectors
    'company_info': 'stock_company_info',     # F10 company info
    'quote/index/ann': 'stock_announcement',  # announcements
    'stock/detail': 'stock_detail',           # stock detail (if used)
    'fund_flow': 'fund_flow',                 # fund flow
    'capital_flow': 'fund_flow',              # fund flow (alt path)
    'money_stream': 'fund_flow',              # fund flow (alt path)
    'zjjl': 'fund_flow',                      # fund flow (拼音缩写)
    'f10': 'stock_f10',                       # F10 info (general)
    'finance_main': 'stock_f10',              # F10 financial summary
    'shareholder': 'stock_shareholder',       # F10 shareholder info
}


def remap_keys(data):
    """Rename URL-derived keys to meaningful short names."""
    if not isinstance(data, dict):
        return data
    mapped = {}
    for url, value in data.items():
        key = next((name for pattern, name in API_KEY_MAP.items() if pattern in str(url)), None)
        mapped[key or url] = value
    return mapped


INTERCEPTOR_JS = """
window.__cdp_api = {};
window.__cdp_refetch = {};
window.__cdp_ws = [];

var _shouldCapture = function(url) {
    return url.indexOf('emotion') > -1 || url.indexOf('articles') > -1 ||
           url.indexOf('up_down') > -1 || url.indexOf('tline') > -1 ||
           url.indexOf('refresh') > -1 || url.indexOf('anchor') > -1 ||
           url.indexOf('basic') > -1 ||
           url.indexOf('hot_plate') > -1 || url.indexOf('index_stock_list') > -1 ||
           url.indexOf('stock_ipo') > -1 || url.indexOf('bj_stock_info') > -1 ||
           url.indexOf('index/home') > -1 ||
           url.indexOf('/quote/stock/') > -1 || url.indexOf('assoc_plate') > -1 ||
           url.indexOf('company_info') > -1 || url.indexOf('/index/ann') > -1 ||
           url.indexOf('stock/detail') > -1 ||
           url.indexOf('fund_flow') > -1 || url.indexOf('capital_flow') > -1 ||
           url.indexOf('money_stream') > -1 || url.indexOf('zjjl') > -1 ||
           url.indexOf('f10') > -1 || url.indexOf('shareholder') > -1 ||
           url.indexOf('finance_main') > -1;
};

var _origFetch = window.fetch.bind(window);
window.fetch = function(url, opts) {
    return _origFetch(url, opts).then(async function(resp) {
        var clone = resp.clone();
        var ct = clone.headers.get('content-type') || '';
        if (ct.includes('json')) {
            var reqUrl = typeof url === 'string' ? url : url.url;
            if (_shouldCapture(reqUrl)) {
                try {
                    var text = await clone.text();
                    window.__cdp_api[reqUrl] = JSON.parse(text);
                } catch(e) {}
            }
        }
        return resp;
    });
};

var _origOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(method, url) {
    this._cdp_url = typeof url === 'string' ? url : url.url;
    return _origOpen.apply(this, arguments);
};
var _origSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.send = function() {
    this.addEventListener('load', function() {
        var url = this._cdp_url || '';
        if (!url) return;
        if (_shouldCapture(url)) {
            try { window.__cdp_api[url] = JSON.parse(this.responseText); } catch(e) {}
        }
    });
    return _origSend.apply(this, arguments);
};

var _origWS = window.WebSocket;
window.WebSocket = function(url, protocols) {
    var ws = new _origWS(url, protocols);
    ws.addEventListener('message', function(e) {
        try { window.__cdp_ws.push({url: url, data: JSON.parse(e.data)}); } catch(e2) {}
        if (window.__cdp_ws.length > 200) window.__cdp_ws.shift();
    });
    return ws;
};
"""


def _chrome_pids_by_flag(flag):
    """Return PIDs of processes whose cmdline contains the given flag."""
    pids = []
    try:
        for entry in os.listdir('/proc/'):
            if not entry.isdigit():
                continue
            try:
                cmdline = open(f'/proc/{entry}/cmdline', 'rb').read().decode('utf-8', errors='replace')
                if flag in cmdline:
                    pids.append(int(entry))
            except (OSError, IOError):
                pass
    except Exception:
        pass
    return pids


def _kill_chrome_on_port(port):
    """Kill any Chrome processes bound to the given debugging port."""
    flag = f'remote-debugging-port={port}'
    for pid in _chrome_pids_by_flag(flag):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    # Also try pkill as fallback for processes not visible in /proc
    try:
        subprocess.run(['pkill', '-f', flag],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(0.5)


def ensure_chrome(cdp_url=CDP_URL):
    """Start headless Chrome if not running. Returns True if Chrome is available."""
    port = urlparse(cdp_url).port or 9222
    host = urlparse(cdp_url).hostname or 'localhost'

    try:
        urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
        return True
    except Exception:
        pass

    global _last_chrome_restart
    now = time.time()
    with _chrome_restart_lock:
        if now - _last_chrome_restart < 60:
            print(f'[CDP] Chrome restart throttled (last restart: {_last_chrome_restart:.0f}, now: {now:.0f})')
            return False
        # Double-check after lock
        try:
            urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
            return True
        except Exception:
            pass

        _kill_chrome_on_port(port)
        _last_chrome_restart = time.time()

        candidates = [
            'google-chrome', 'google-chrome-stable', 'chromium',
            'chromium-browser', 'google-chrome-unstable',
        ]
        chrome = next((c for c in candidates if subprocess.run(
            ['which', c], capture_output=True).returncode == 0), None)
        if not chrome:
            return False

        print(f'[CDP] starting {chrome} --headless --remote-debugging-port={port}')
        subprocess.Popen([
            chrome, '--headless', f'--remote-debugging-port={port}',
            '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
            '--disable-extensions', '--disable-default-apps',
            '--disable-component-extensions-with-background-pages',
            '--js-flags=--max_old_space_size=512',
            '--remote-allow-origins=*',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(15):
            try:
                urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
                return True
            except:
                time.sleep(1)
        return False


def full_chrome_restart(cdp_url=CDP_URL):
    """Kill ALL Chrome processes and start fresh — thread-safe, single-threaded.

    Unlike ensure_chrome (which only starts Chrome if missing), this *always* kills
    and restarts. Acquires _chrome_restart_lock so concurrent ensure_chrome() calls
    from other pages block safely, then find Chrome already running.

    After this returns, ALL old CDP connections are broken. Each CDPPage must
    reconnect via _reconnect() or _ensure_ws().
    """
    global _last_chrome_restart
    port = urlparse(cdp_url).port or 9222
    host = urlparse(cdp_url).hostname or 'localhost'
    print(f'[CDP] full_chrome_restart: killing Chrome on port {port}, starting fresh...')
    with _chrome_restart_lock:
        _kill_chrome_on_port(port)
        _last_chrome_restart = 0  # allow ensure_chrome to proceed
        gc.collect()
        ok = ensure_chrome(cdp_url)
        if ok:
            _last_chrome_restart = time.time()
        print(f'[CDP] full_chrome_restart: {"OK" if ok else "FAILED"}')
        return ok


def find_tab(pattern, cdp_url=CDP_URL):
    """Find existing tab with pattern in URL. Returns WS debugger URL or None."""
    host = urlparse(cdp_url).hostname or 'localhost'
    port = urlparse(cdp_url).port or 9222
    try:
        tabs = json.loads(
            urllib.request.urlopen(f"http://{host}:{port}/json", timeout=5).read()
        )
        tab = next((t for t in tabs if pattern in t.get('url', '')), None)
        if tab:
            ws = tab['webSocketDebuggerUrl']
            return ws.replace('127.0.0.1', host).replace('localhost', host)
    except:
        pass
    return None


def execute_js(ws_url, js, timeout=15):
    """Execute JS in a CDP tab and return the parsed result.

    Opens a temporary WS connection, sends Runtime.evaluate, waits for
    the response matching our command id, then closes the connection.
    """
    import websocket
    ws = websocket.create_connection(ws_url, timeout=timeout)
    msg_id = 1
    ws.send(json.dumps({
        'id': msg_id, 'method': 'Runtime.evaluate',
        'params': {'expression': js, 'awaitPromise': True, 'returnByValue': True}
    }))
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(deadline - time.time())
        try:
            msg = json.loads(ws.recv())
            if msg.get('id') == msg_id:
                raw = msg.get('result', {}).get('result', {}).get('value', '{}')
                ws.close()
                return json.loads(raw)
        except:
            break
    ws.close()
    return None


class CDPPage:
    """A persistent CDP page that auto-collects network data.

    Creates a hidden tab, injects JS interceptors (fetch + XHR + WebSocket),
    navigates to the target page, and runs a background heartbeat to
    periodically pull collected data into a thread-safe cache.
    """

    # Per-key TTL (seconds).
    # High-frequency keys: page auto-refreshes them via setInterval — short TTL.
    # Low-frequency keys: one-shot on page load, CDP re-fetches them — long TTL.
    KEY_TTL = 120
    KEY_TTL_OVERRIDES = {
        'market_sentiment': 60,   # emotion — page refreshes ~15s
        'basic_info': 60,         # basic   — page refreshes ~15-50s
        'live_refresh': 60,       # refresh — page refreshes ~15s
        'timeline': 60,           # tline — page refreshes ~50s
        'index_home': 60,         # page refreshes ~20s
        'hot_plate': 60,          # page refreshes ~20s
        'stock_ranking': 60,      # page refreshes ~20s
        '__ws__': 30,             # websocket data is transient
    }

    # Keys the page auto-refreshes — no proactive CDP re-fetch needed.
    _PAGE_REFRESHED_KEYS = frozenset({
        'market_sentiment', 'basic_info', 'live_refresh',
        'timeline', 'index_home', 'hot_plate', 'stock_ranking',
    })

    # Safety cap for _last_data — prevents unbounded growth if an
    # unrecognised URL with dynamic parameters enters remap_keys.
    _LAST_DATA_MAX_KEYS = 50

    def __init__(self, name, target_url, cdp_host='localhost', cdp_port=9222, heartbeat=True):
        self.name = name
        self.target_url = target_url
        self.cdp_host = cdp_host
        self.cdp_port = cdp_port
        self.cache = {}
        self._last_data = {}  # serving cache for external callers
        self.last_updated = time.time()
        self._lock = threading.Lock()
        self._ws_lock = threading.RLock()
        self._running = True
        self._ws = None
        self._target_id = None
        self._msg_id = 0
        self._key_last_seen = {}  # key -> timestamp of last refresh
        self._api_urls = {}       # remapped_key -> original URL for re-fetch
        self._last_data_max_age = 600  # max age (seconds) for _last_data entries
        self._last_data_ts = {}   # key -> timestamp when last added to _last_data
        self._navigate_lock = threading.Lock()
        self._connect()
        if heartbeat:
            threading.Thread(target=self._heartbeat, daemon=True).start()

    def _http_url(self):
        return f"http://{self.cdp_host}:{self.cdp_port}"

    def _next_id(self):
        self._msg_id += 1
        return self._msg_id

    def _create_target(self):
        """Create a new browser tab via CDP Target.createTarget."""
        import websocket
        tabs = json.loads(
            urllib.request.urlopen(f"{self._http_url()}/json", timeout=10).read()
        )
        if not tabs:
            return None, None
        browser_ws = tabs[0]['webSocketDebuggerUrl']
        browser_ws = browser_ws.replace('127.0.0.1', self.cdp_host).replace('localhost', self.cdp_host)
        ws = websocket.create_connection(browser_ws, timeout=30)
        ws.send(json.dumps({
            'id': 1, 'method': 'Target.createTarget',
            'params': {'url': 'about:blank'}
        }))
        result = json.loads(ws.recv())
        ws.close()
        target_id = result.get('result', {}).get('targetId')
        if not target_id:
            return None, None
        ws_url = f"ws://{self.cdp_host}:{self.cdp_port}/devtools/page/{target_id}"
        return target_id, ws_url

    def _connect(self):
        """Create target, connect persistent WS, inject interceptor, navigate."""
        import websocket
        target_id, ws_url = self._create_target()
        if not target_id:
            raise RuntimeError(f"Failed to create CDP target for {self.name}")

        ws = websocket.create_connection(ws_url, timeout=30)
        try:
            self._send_on(ws, {'id': self._next_id(), 'method': 'Page.enable'})
            self._send_recv_on(ws, {'id': self._next_id(), 'method': 'Page.addScriptToEvaluateOnNewDocument',
                                      'params': {'source': INTERCEPTOR_JS}})
            self._send_on(ws, {'id': self._next_id(), 'method': 'Page.navigate',
                                'params': {'url': self.target_url}})
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    msg = self._recv_on(ws, timeout=5)
                    if msg.get('method') == 'Page.loadEventFired':
                        break
                except:
                    break
        except Exception:
            ws.close()
            raise

        self._target_id = target_id
        self._ws = ws
        print(f"  \u2713 CDP page '{self.name}' \u2192 {self.target_url}")

    def _send_on(self, ws, msg):
        ws.send(json.dumps(msg))

    def _recv_on(self, ws, timeout=30):
        ws.settimeout(timeout)
        return json.loads(ws.recv())

    def _send_recv_on(self, ws, msg, timeout=30):
        """Send on a given WS and wait for the matching response."""
        self._send_on(ws, msg)
        msg_id = msg['id']
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                resp = self._recv_on(ws, timeout=remaining)
                if resp.get('id') == msg_id:
                    return resp
            except:
                break
        return {}

    def _send(self, msg):
        self._ws.send(json.dumps(msg))

    def _recv(self, timeout=30):
        self._ws.settimeout(timeout)
        return json.loads(self._ws.recv())

    def _send_recv(self, msg, timeout=30):
        """Send a command and wait for the matching response (skipping events)."""
        return self._send_recv_on(self._ws, msg, timeout=timeout)

    def _evaluate(self, js, timeout=10):
        """Evaluate JS in the page and return the result value."""
        with self._ws_lock:
            result = self._send_recv({
                'id': self._next_id(), 'method': 'Runtime.evaluate',
                'params': {'expression': js, 'returnByValue': True, 'awaitPromise': True}
            }, timeout)
        return result.get('result', {}).get('result', {}).get('value')

    def re_fetch_api(self, url):
        """Fire-and-forget re-fetch of an API URL, storing result in __cdp_refetch.

        __cdp_refetch is a secondary buffer that's not cleared by the interceptor,
        so data survives even if the fetch response arrives between heartbeat polls.
        Returns True if the fetch command was sent successfully (not a guarantee
        the response will arrive).
        """
        try:
            escaped = url.replace('\\', '\\\\').replace('"', '\\"')
            self._send({'id': self._next_id(), 'method': 'Runtime.evaluate',
                        'params': {'expression': f'fetch("{escaped}",{{cache:"no-store"}}).then(function(r){{return r.json()}}).then(function(d){{window.__cdp_refetch["{escaped}"]=d}}).catch(function(){{}})',
                                   'awaitPromise': False, 'returnByValue': False}})
            return True
        except Exception as e:
            print(f'[CDP:{self.name}] re_fetch_api failed for {url}: {e}')
            return False

    # Backward compat alias
    _re_fetch_api = re_fetch_api

    def evaluate_fetch(self, url, timeout=15):
        """Fetch a URL from within the browser context and return parsed JSON.

        Uses the page's JavaScript runtime to fire a fetch() call,
        so the request comes from the browser (same IP, cookies, headers).
        Returns parsed dict, or None on failure.

        This is NOT a fire-and-forget — it blocks until the fetch completes
        or the timeout expires, making it suitable for synchronous callers.
        """
        if not self._ensure_ws():
            return None
        escaped = url.replace('\\', '\\\\').replace('"', '\\"')
        js = (
            '(async function(){'
            'try{'
            'var r=await fetch("' + escaped + '",{credentials:"include",cache:"no-store"});'
            'if(!r.ok)return{error:"HTTP "+r.status};'
            'return await r.json();'
            '}catch(e){return{error:e.message}}'
            '})()'
        )
        try:
            return self._evaluate(js, timeout=timeout)
        except Exception as e:
            print(f'[CDP:{self.name}] evaluate_fetch failed for {url}: {e}')
            return None

    def _heartbeat_interval(self):
        """Return heartbeat sleep interval based on China A-share trading hours.

        During trading (Mon-Fri 09:30-11:30, 13:00-15:00 UTC+8): 10s.
        Outside trading: 60s — data doesn't change, reduce polling.
        """
        now = datetime.now(timezone.utc) + timedelta(hours=8)
        if now.weekday() >= 5:
            return 60
        h, m = now.hour, now.minute
        in_morning = (h == 9 and m >= 30) or (10 <= h <= 10) or (h == 11 and m <= 30)
        in_afternoon = (13 <= h <= 14)
        return 10 if (in_morning or in_afternoon) else 60

    def _heartbeat(self):
        """Background loop: poll collected data, reconnect on failure."""
        empty_count = 0
        while self._running:
            time.sleep(self._heartbeat_interval())
            try:
                alive = self._evaluate('typeof window.__cdp_api !== "undefined"', timeout=5)
                if not alive:
                    print(f"[CDP:{self.name}] interceptor lost, reconnecting...")
                    self._reconnect()
                    empty_count = 0
                    continue

                raw = self._evaluate(
                    'var d=JSON.stringify({api:window.__cdp_api,refetch:window.__cdp_refetch,ws:window.__cdp_ws});'
                    'window.__cdp_api={};window.__cdp_refetch={};window.__cdp_ws=[];d',
                    timeout=10
                )
                if not raw:
                    empty_count += 1
                    if empty_count >= 4:
                        print(f"[CDP:{self.name}] {empty_count}x empty polls, forcing reconnect...")
                        self._reconnect()
                        empty_count = 0
                    continue

                data = json.loads(raw)
                api_data = data.get('api', {}) or {}
                refetch_data = data.get('refetch', {}) or {}
                ws_data = data.get('ws', []) or {}
                all_api = {**api_data, **refetch_data}

                if not all_api and not ws_data:
                    empty_count += 1
                    if empty_count >= 6:
                        print(f"[CDP:{self.name}] {empty_count}x empty polls, forcing reconnect...")
                        self._reconnect()
                        empty_count = 0
                    continue

                with self._lock:
                    now = time.time()
                    if all_api:
                        remapped = remap_keys(all_api)
                        self.cache.update(remapped)
                        self._last_data.update(remapped)
                        for k in remapped:
                            self._last_data_ts[k] = now
                        if len(self._last_data) > self._LAST_DATA_MAX_KEYS:
                            # Evict oldest key if too many unrecognized URLs accumulated
                            oldest = min(self._last_data, key=lambda k: self._key_last_seen.get(k, 0))
                            del self._last_data[oldest]
                        for url_key, raw_val in all_api.items():
                            mapped = next((name for p, name in API_KEY_MAP.items()
                                           if p in str(url_key)), None)
                            if mapped:
                                self._key_last_seen[mapped] = now
                                self._api_urls[mapped] = url_key
                    if ws_data:
                        self.cache['__ws__'] = ws_data
                        self._last_data['__ws__'] = ws_data
                        self._last_data_ts['__ws__'] = now
                        self._key_last_seen['__ws__'] = now
                    # Expire stale keys from freshness cache
                    for key in list(self.cache.keys()):
                        last_seen = self._key_last_seen.get(key)
                        if last_seen is None:
                            continue
                        ttl = self.KEY_TTL_OVERRIDES.get(key, self.KEY_TTL)
                        if now - last_seen > ttl:
                            del self.cache[key]
                            del self._key_last_seen[key]
                    # Expire _last_data entries that haven't been seen in max_age
                    for key in list(self._last_data.keys()):
                        age = now - self._last_data_ts.get(key, 0)
                        if age > self._last_data_max_age:
                            del self._last_data[key]
                            self._last_data_ts.pop(key, None)
                            self._key_last_seen.pop(key, None)
                            self._api_urls.pop(key, None)
                    # Proactively re-fetch low-frequency APIs — page handles the high-frequency ones
                    RE_FETCH_AFTER = 25
                    for key in list(self._api_urls.keys()):
                        if key in self._PAGE_REFRESHED_KEYS:
                            continue
                        last_seen = self._key_last_seen.get(key, 0)
                        if last_seen and now - last_seen > RE_FETCH_AFTER:
                            self._re_fetch_api(self._api_urls[key])
                    self.last_updated = now
                empty_count = 0

            except Exception as e:
                print(f"[CDP:{self.name}] heartbeat: {e}, reconnecting...")
                self._reconnect()
                empty_count = 0

    def _close_target(self):
        """Close the old browser tab via CDP Target.closeTarget."""
        tid = self._target_id
        self._target_id = None
        if not tid:
            return
        try:
            info = json.loads(
                urllib.request.urlopen(f"{self._http_url()}/json/version", timeout=5).read()
            )
            browser_ws_url = info.get('webSocketDebuggerUrl', '')
            if browser_ws_url:
                browser_ws_url = browser_ws_url.replace('127.0.0.1', self.cdp_host).replace('localhost', self.cdp_host)
                import websocket
                ws = websocket.create_connection(browser_ws_url, timeout=10)
                ws.send(json.dumps({
                    'id': 1, 'method': 'Target.closeTarget',
                    'params': {'targetId': tid}
                }))
                ws.close()
        except:
            pass

    def _reconnect(self):
        """Close old WS + tab, try reconnecting. If Chrome died, restart it."""
        try:
            if self._ws:
                self._ws.close()
        except:
            pass
        self._close_target()
        with self._lock:
            self.cache.clear()
            self._key_last_seen.clear()
            self._api_urls.clear()
            # Stale WebSocket data from old session — discard on reconnect
            self._last_data.pop('__ws__', None)
            self._last_data_ts.pop('__ws__', None)
        for attempt in range(3):
            try:
                self._connect()
                return
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
        # All 3 attempts failed — Chrome might have crashed
        print(f"[CDP:{self.name}] 3 reconnect attempts failed, trying to restart Chrome...")
        if ensure_chrome():
            for attempt in range(3):
                try:
                    self._connect()
                    return
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
        print(f"[CDP:{self.name}] reconnect failed after Chrome restart")

    def get_data(self):
        """Return merged data — latest from live cache, gaps filled by _last_data.

        _last_data entries older than _last_data_max_age are skipped to
        prevent serving permanently stale data.
        """
        with self._lock:
            now = time.time()
            merged = {}
            for key, val in self._last_data.items():
                last_seen = self._key_last_seen.get(key)
                if last_seen is None or now - last_seen < self._last_data_max_age:
                    merged[key] = val
            merged.update(self.cache)
            return merged

    def refresh(self):
        """Force an immediate data pull. Returns True on success."""
        try:
            raw = self._evaluate('JSON.stringify({api:window.__cdp_api,refetch:window.__cdp_refetch,ws:window.__cdp_ws})', timeout=10)
            if raw:
                data = json.loads(raw)
                api_data = data.get('api', {}) or {}
                refetch_data = data.get('refetch', {}) or {}
                ws_data = data.get('ws', []) or {}
                all_api = {**api_data, **refetch_data}
                with self._lock:
                    now = time.time()
                    if all_api:
                        remapped = remap_keys(all_api)
                        self.cache.update(remapped)
                        self._last_data.update(remapped)
                        for k in remapped:
                            self._last_data_ts[k] = now
                        if len(self._last_data) > self._LAST_DATA_MAX_KEYS:
                            oldest = min(self._last_data, key=lambda k: self._key_last_seen.get(k, 0))
                            del self._last_data[oldest]
                        for url_key, raw_val in all_api.items():
                            mapped = next((name for p, name in API_KEY_MAP.items()
                                           if p in str(url_key)), None)
                            if mapped:
                                self._key_last_seen[mapped] = now
                                self._api_urls[mapped] = url_key
                    if ws_data:
                        self.cache['__ws__'] = ws_data
                        self._last_data['__ws__'] = ws_data
                        self._last_data_ts['__ws__'] = now
                        self._key_last_seen['__ws__'] = now
                    # Expire stale keys from freshness cache only
                    for key in list(self.cache.keys()):
                        last_seen = self._key_last_seen.get(key)
                        if last_seen is None:
                            continue
                        ttl = self.KEY_TTL_OVERRIDES.get(key, self.KEY_TTL)
                        if now - last_seen > ttl:
                            del self.cache[key]
                            del self._key_last_seen[key]
                    self.last_updated = now
                return True
        except:
            pass
        return False

    def _ensure_ws(self):
        """Reconnect WebSocket if disconnected (stock page, no heartbeat)."""
        if self._ws:
            try:
                if self._evaluate('1', timeout=3):
                    return True
            except Exception:
                pass
        if self._target_id:
            self._close_target()
        try:
            self._ws.close()
        except Exception:
            pass
        self._ws = None
        for attempt in range(3):
            try:
                self._connect()
                return True
            except Exception:
                if attempt == 0:
                    ensure_chrome()  # restart Chrome if down
                time.sleep(2)
        return False

    _nav_restart_counter = 0
    _MAX_PAGE_NAV_BEFORE_RECONNECT = 30

    def _maybe_reconnect(self):
        """Restart Chrome entirely after threshold navigations to free memory.

        Uses centralized full_chrome_restart() so only ONE thread kills/starts
        Chrome. Other pages' ensure_chrome() calls block on _chrome_restart_lock
        and find the fresh Chrome already running — no duplicate instances.
        """
        CDPPage._nav_restart_counter += 1
        if CDPPage._nav_restart_counter >= self._MAX_PAGE_NAV_BEFORE_RECONNECT:
            CDPPage._nav_restart_counter = 0
            print(f"[CDP:{self.name}] nav threshold ({self._MAX_PAGE_NAV_BEFORE_RECONNECT}) reached, "
                  f"full Chrome restart...")
            full_chrome_restart(f"http://{self.cdp_host}:{self.cdp_port}")
            # Reconnect this page to the fresh Chrome (clears cache, creates new tab)
            self._reconnect()
            return True
        return False

    def navigate_stock(self, stock_code, timeout=15, tabs=('fund_flow', 'f10')):
        """Navigate to a stock code, wait for fresh data, return True on success.

        Fair queuing via blocking lock (no timeout+retry) — avoids wasted
        CPU and retry deadlines under concurrent load.

        Args:
            tabs: Which tab sections to click after navigation.
                  ('fund_flow', 'f10') — both tabs (legacy, ~6s extra).
                  ('fund_flow',)       — fund flow only.
                  ()                   — no tabs, fastest (~2-3s total).
        """
        url = f'https://www.cls.cn/stock?code={stock_code}'
        # Fast path: skip navigation if cache already has fresh data for this code
        cached = ((self._last_data.get('basic_info') or {}).get('data') or {}).get('secu_code')
        if cached == stock_code:
            return True
        # Block until lock acquired — fair queuing across concurrent requests
        wait_start = time.time()
        self._navigate_lock.acquire()
        try:
            remaining = timeout - (time.time() - wait_start)
            if remaining < 2:
                return ((self._last_data.get('basic_info') or {}).get('data') or {}).get('secu_code') == stock_code
            # Free Chrome renderer processes by reconnecting page periodically
            self._maybe_reconnect()
            if not self._ensure_ws():
                return False
            with self._ws_lock:
                self._evaluate(
                    'window.__cdp_api={};window.__cdp_refetch={}',
                    timeout=3)
                self._send_recv({'id': self._next_id(), 'method': 'Page.navigate',
                                 'params': {'url': url}}, timeout=min(10, remaining))
            load_deadline = time.time() + min(15, remaining)
            while time.time() < load_deadline:
                try:
                    msg = self._recv(timeout=2)
                    if msg.get('method') == 'Page.loadEventFired':
                        break
                except:
                    break
            deadline = time.time() + max(2, remaining)
            last_seen_code = None
            stable_count = 0
            while time.time() < deadline:
                self.refresh()
                data = self.get_data()
                bi = (data.get('basic_info') or {}).get('data') or {}
                if bi.get('secu_code') == stock_code:
                    if tabs:
                        time.sleep(1)
                    self.refresh()
                    # BSE (北交所) stocks lack fund flow and F10 tabs — skip them
                    code_lower = stock_code.lower()
                    is_bse = code_lower.startswith('bj') or code_lower.endswith('bj')
                    if not is_bse:
                        if 'fund_flow' in tabs:
                            self._click_fund_flow_tab()
                            time.sleep(1)
                            self.refresh()
                        if 'f10' in tabs:
                            self._click_f10_tab()
                            time.sleep(1)
                            self.refresh()
                    return True
                # Fail fast: page settled on a wrong stock code
                secu_code = bi.get('secu_code')
                if secu_code:
                    if secu_code == last_seen_code:
                        stable_count += 1
                    else:
                        last_seen_code = secu_code
                        stable_count = 0
                    if stable_count >= 3:
                        break
                time.sleep(0.5)
            self.refresh()
            data = self.get_data()
            bi = (data.get('basic_info') or {}).get('data') or {}
            return bi.get('secu_code') == stock_code
        finally:
            self._navigate_lock.release()

    def _click_fund_flow_tab(self):
        """Click the fund flow (资金流向) tab on the stock detail page."""
        js = """
            (function(){
                var container = document.querySelector('[class*="tab" i]') || document.querySelector('[class*="detail" i]');
                if (!container) {
                    var els = document.querySelectorAll('span,div,a,li');
                    for (var i=0; i<els.length; i++) {
                        var t = els[i].textContent.trim();
                        if (t === '资金流向' || t === '资金' || t === '主力') {
                            els[i].click();
                            return t;
                        }
                    }
                    return null;
                }
                var items = container.querySelectorAll('span,div,a,li');
                for (var i=0; i<items.length; i++) {
                    var t = items[i].textContent.trim();
                    if (t === '资金流向' || t === '资金' || t === '主力') {
                        items[i].click();
                        return t;
                    }
                }
                return null;
            })()
        """
        try:
            self._evaluate(js, timeout=3)
        except Exception:
            pass

    def _click_f10_tab(self):
        """Click the 简况F10 tab on the stock detail page."""
        js = """
            (function(){
                var container = document.querySelector('[class*="tab" i]') || document.querySelector('[class*="detail" i]');
                if (!container) {
                    var els = document.querySelectorAll('span,div,a,li');
                    for (var i=0; i<els.length; i++) {
                        var t = els[i].textContent.trim();
                        if (t === '简况F10' || t === 'F10' || t === '公司概况') {
                            els[i].click();
                            return t;
                        }
                    }
                    return null;
                }
                var items = container.querySelectorAll('span,div,a,li');
                for (var i=0; i<items.length; i++) {
                    var t = items[i].textContent.trim();
                    if (t === '简况F10' || t === 'F10' || t === '公司概况') {
                        items[i].click();
                        return t;
                    }
                }
                return null;
            })()
        """
        try:
            self._evaluate(js, timeout=3)
        except Exception:
            pass

    def close(self):
        self._running = False
        try:
            if self._ws:
                self._ws.close()
        except:
            pass
        self._close_target()


class CDPEngine:
    """Manages Chrome browser instance and persistent CDP pages."""

    def __init__(self):
        self.pages = {}
        self._ready = False

    @property
    def ready(self):
        return self._ready

    def start(self):
        """Verify Chrome is running and accepting CDP connections."""
        port = urlparse(CDP_URL).port or 9222
        host = urlparse(CDP_URL).hostname or 'localhost'
        try:
            urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
            self._ready = True
            return True
        except:
            return False

    def add_page(self, name, target_url, heartbeat=True):
        """Create and register a persistent CDP page."""
        port = urlparse(CDP_URL).port or 9222
        host = urlparse(CDP_URL).hostname or 'localhost'
        try:
            page = CDPPage(name, target_url, cdp_host=host, cdp_port=port,
                           heartbeat=heartbeat)
            self.pages[name] = page
            return page
        except Exception as e:
            print(f"  \u2717 Failed to create page '{name}': {e}")
            return None

    def get_page(self, name):
        return self.pages.get(name)

    def shutdown(self):
        for page in self.pages.values():
            page.close()

    def __del__(self):
        self.shutdown()
