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
import json
import os
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlparse


CDP_URL = os.getenv('CDP_URL', 'http://localhost:9222')

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
window.__cdp_ws = [];

var _shouldCapture = function(url) {
    return url.indexOf('emotion') > -1 || url.indexOf('articles') > -1 ||
           url.indexOf('up_down') > -1 || url.indexOf('tline') > -1 ||
           url.indexOf('refresh') > -1 || url.indexOf('anchor') > -1 ||
           url.indexOf('basic') > -1 ||
           url.indexOf('hot_plate') > -1 || url.indexOf('index_stock_list') > -1 ||
           url.indexOf('stock_ipo') > -1 || url.indexOf('bj_stock_info') > -1 ||
           url.indexOf('index/home') > -1;
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


def ensure_chrome(cdp_url=CDP_URL):
    """Start headless Chrome if not running. Returns True if Chrome is available."""
    port = urlparse(cdp_url).port or 9222
    host = urlparse(cdp_url).hostname or 'localhost'

    try:
        urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
        return True
    except Exception:
        pass

    candidates = [
        'google-chrome', 'google-chrome-stable', 'chromium',
        'chromium-browser', 'google-chrome-unstable',
    ]
    chrome = next((c for c in candidates if subprocess.run(
        ['which', c], capture_output=True).returncode == 0), None)
    if not chrome:
        return False

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

    def __init__(self, name, target_url, cdp_host='localhost', cdp_port=9222):
        self.name = name
        self.target_url = target_url
        self.cdp_host = cdp_host
        self.cdp_port = cdp_port
        self.cache = {}
        self.last_updated = 0
        self._lock = threading.Lock()
        self._running = True
        self._ws = None
        self._target_id = None
        self._msg_id = 0
        self._connect()
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
        result = self._send_recv({
            'id': self._next_id(), 'method': 'Runtime.evaluate',
            'params': {'expression': js, 'returnByValue': True, 'awaitPromise': True}
        }, timeout)
        return result.get('result', {}).get('result', {}).get('value')

    def _heartbeat(self):
        """Background loop: poll collected data every 15s, reconnect on failure."""
        empty_count = 0
        while self._running:
            time.sleep(15)
            try:
                alive = self._evaluate('typeof window.__cdp_api !== "undefined"', timeout=5)
                if not alive:
                    print(f"[CDP:{self.name}] interceptor lost, reconnecting...")
                    self._reconnect()
                    empty_count = 0
                    continue

                raw = self._evaluate(
                    'var d=JSON.stringify({api:window.__cdp_api,ws:window.__cdp_ws});'
                    'window.__cdp_api={};window.__cdp_ws=[];d',
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
                ws_data = data.get('ws', []) or []

                if not api_data and not ws_data:
                    empty_count += 1
                    if empty_count >= 4:
                        print(f"[CDP:{self.name}] {empty_count}x empty polls, forcing reconnect...")
                        self._reconnect()
                        empty_count = 0
                    continue

                with self._lock:
                    if api_data:
                        self.cache.update(remap_keys(api_data))
                    if ws_data:
                        self.cache['__ws__'] = ws_data
                    self.last_updated = time.time()
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

    def get_data(self, max_age=None):
        """Return collected data. If max_age (seconds) set, returns None if stale."""
        with self._lock:
            if max_age and self.last_updated and time.time() - self.last_updated > max_age:
                return None
            return dict(self.cache) if self.cache else None

    def refresh(self):
        """Force an immediate data pull. Returns True on success."""
        try:
            raw = self._evaluate('JSON.stringify({api:window.__cdp_api,ws:window.__cdp_ws})', timeout=10)
            if raw:
                data = json.loads(raw)
                api_data = data.get('api', {}) or {}
                ws_data = data.get('ws', []) or []
                with self._lock:
                    if api_data:
                        self.cache.update(remap_keys(api_data))
                    if ws_data:
                        self.cache['__ws__'] = ws_data
                    self.last_updated = time.time()
                return True
        except:
            pass
        return False

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

    def add_page(self, name, target_url):
        """Create and register a persistent CDP page."""
        port = urlparse(CDP_URL).port or 9222
        host = urlparse(CDP_URL).hostname or 'localhost'
        try:
            page = CDPPage(name, target_url, cdp_host=host, cdp_port=port)
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
