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

import gc
import json
import logging
import os
import signal
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlparse

from . import config
from . import metrics

log = logging.getLogger('cdp')


# Env-registry single source (config.md §1.1): both names are registered in
# config.py, so this module never re-reads os.environ — a second definition
# would let an env change land on one side only (code-discipline §6).
CDP_URL = config.CDP_URL
# Short throttle so a crashed Chrome is restarted quickly (2c2g OOM recovery).
_chrome_restart_lock = threading.RLock()  # RLock so full_chrome_restart→ensure_chrome doesn't deadlock
_last_chrome_restart = 0
_CHROME_RESTART_THROTTLE = config.CDP_RESTART_THROTTLE
_RECONNECT_RETRY_WINDOW = 45  # seconds to wait out throttle + startup before giving up


# ── Chrome restart window state machine (AR-12 / R19) ──────────────────────
# Single authoritative state for the restart window. Written only by the
# _mark_* primitives, read only through restart_window_snapshot().

_RESTART_STATES = frozenset({'idle', 'restarting', 'unavailable'})
_restart_window = {'state': 'idle', 'window_start': None, 'window_end': None}
_restart_window_lock = threading.Lock()


def restart_window_snapshot():
    """Return a copy of the restart window (thread-safe)."""
    with _restart_window_lock:                                # BR-CDP-4
        return dict(_restart_window)


def _publish_window():
    metrics.set_gauge('cdp_restart_window', restart_window_snapshot())   # BR-CDP-5


def _mark_restarting():
    """idle/unavailable -> restarting (idempotent: window_start not refreshed)."""
    changed = False
    with _restart_window_lock:
        if _restart_window['state'] != 'restarting':
            _restart_window['state'] = 'restarting'
            _restart_window['window_start'] = time.time()
            _restart_window['window_end'] = None
            changed = True
    if changed:
        _publish_window()


def _mark_idle():
    """any -> idle (idempotent: a plain reachable poll must not touch the window)."""
    changed = False
    with _restart_window_lock:
        if _restart_window['state'] != 'idle':
            _restart_window['state'] = 'idle'
            _restart_window['window_end'] = time.time()
            changed = True
    if changed:
        _publish_window()


def _mark_unavailable():
    """any -> unavailable (from idle the window opens and closes in one step)."""
    changed = False
    now = time.time()
    with _restart_window_lock:
        if _restart_window['state'] != 'unavailable':
            if _restart_window['state'] == 'idle':
                _restart_window['window_start'] = now
            _restart_window['state'] = 'unavailable'
            _restart_window['window_end'] = now
            changed = True
    if changed:
        _publish_window()
        log.error('[CDP] restart window → unavailable')


def page_data(page):
    """R18: the single defensive page-data accessor. Total function, never raises.

    Returns a non-empty dict, or None when the page is None / get_data raises /
    returns a non-dict / returns an empty dict (cache cleared during a restart
    window). No key-level fallback — callers decide the endpoint shape.
    """
    if page is None:
        return None
    try:
        data = page.get_data()
    except Exception as exc:
        log.warning('[CDP] page_data: get_data failed: %s', exc)
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


def cdp_ready():
    """True when config.cdp_engine is initialised and ready (watchdog reuse)."""
    eng = config.cdp_engine
    return bool(eng and eng.ready)


def watchdog_restart_skip_reason(now=None):
    """BR-CDP-6/7: the single decision function for the watchdog restart.

    Returns None to allow a restart, else a reason string (short-circuited):
    not_ready / already_restarting / trading_hours / recent_restart.
    """
    now = time.time() if now is None else now
    if not cdp_ready():
        return 'not_ready'
    if restart_window_snapshot()['state'] == 'restarting':
        return 'already_restarting'
    if config._is_trading_hours(now):                             # ADR-012: avoid trading
        return 'trading_hours'
    if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
        return 'recent_restart'
    return None


# REV-DES-19: publish the initial idle window at import time so
# metrics.snapshot() always contains cdp_restart_window.
_publish_window()


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
                with open(f'/proc/{entry}/cmdline', 'rb') as f:
                    cmdline = f.read().decode('utf-8', errors='replace')
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
        _mark_idle()                                             # reachable -> idle
        return True
    except Exception:
        pass

    global _last_chrome_restart
    now = time.time()
    with _chrome_restart_lock:
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE:
            log.warning(f'[CDP] Chrome restart throttled (last restart: {_last_chrome_restart:.0f}, now: {now:.0f})')
            return False                                         # throttled = not attempted
        # Double-check after lock
        try:
            urllib.request.urlopen(f"http://{host}:{port}/json", timeout=2)
            _mark_idle()
            return True
        except Exception:
            pass

        # §3.2: the restart window must always reach a terminal state (idle on
        # success / unavailable on failure). `which` and `Popen` raise under
        # fork pressure (2c2g OOM), and this function is also called from
        # _reconnect()/_ensure_ws() inside the heartbeat thread — an escape
        # would both terminate that thread and leave the window stuck at
        # 'restarting' (pinning watchdog_restart_skip_reason() at
        # 'already_restarting' forever). Fail closed as 'unavailable'.
        try:
            _kill_chrome_on_port(port)
            _last_chrome_restart = time.time()

            candidates = [
                'google-chrome', 'google-chrome-stable', 'chromium',
                'chromium-browser', 'google-chrome-unstable',
            ]
            chrome = next((c for c in candidates if subprocess.run(
                ['which', c], capture_output=True).returncode == 0), None)
            if not chrome:
                _mark_unavailable()                              # real failure
                return False

            log.info(f'[CDP] starting {chrome} --headless --remote-debugging-port={port}')
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
                    _mark_idle()                                 # startup succeeded
                    return True
                except:
                    time.sleep(1)
            _mark_unavailable()                                  # 15 retries exhausted
            return False
        except Exception as exc:
            log.exception(f'[CDP] ensure_chrome: unexpected error ({exc})')
            _mark_unavailable()                                  # never leave the window open
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
    log.warning(f'[CDP] full_chrome_restart: killing Chrome on port {port}, starting fresh...')
    with _chrome_restart_lock:
        now = time.time()
        if now - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
            log.warning(f'[CDP] full_chrome_restart: Chrome restarted recently ({now - _last_chrome_restart:.0f}s ago) — skipping back-to-back restart')
            return False                                         # not attempted: state kept
        _mark_restarting()                                       # enter the restart window
        try:
            _kill_chrome_on_port(port)
            _last_chrome_restart = 0  # allow ensure_chrome to proceed
            gc.collect()
            ok = ensure_chrome(cdp_url)                          # marks idle/unavailable itself
            if ok:
                _last_chrome_restart = time.time()
            log.info(f'[CDP] full_chrome_restart: {"OK" if ok else "FAILED"}')
            return ok
        except Exception as exc:
            log.exception(f'[CDP] full_chrome_restart: unexpected error ({exc})')
            return False
        finally:
            # §3.2: `restarting` must always reach a terminal state — idle
            # (success) or unavailable (failure); there is no "stuck
            # restarting" transition. Otherwise one escaping exception pins
            # watchdog_restart_skip_reason() at 'already_restarting' forever
            # (watchdog restart permanently dead) and /healthz misreports.
            if restart_window_snapshot()['state'] == 'restarting':
                _mark_unavailable()


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


def _same_code(a, b):
    """True when two spelling variants denote the same stock (P1-6).

    Canonicalises with the single authority (``config.canonical_code``) so the
    fixed upstream ``SecuCode`` matches whether the caller asked for
    ``600519.SH`` or ``sh600519`` — an invalid/empty code never matches.
    """
    canon = config.canonical_code(a)
    return canon is not None and canon == config.canonical_code(b)


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
    # Also reused as the cap for self.cache (same growth risk).
    _LAST_DATA_MAX_KEYS = 50

    # Cap on orphaned-target bookkeeping (_created_targets) — prevents an
    # unbounded set if close failures persist across many reconnect storms.
    _MAX_TRACKED_TARGETS = 32
    _CLOSE_BUDGET = 3       # max targets to close per _close_target call
    _CLOSE_THROTTLE = 60    # seconds before retrying a failed close
    _CLOSE_MAX_FAILURES = 3 # consecutive failures before abandoning a target
    # Absolute ledger bound: even if every eviction candidate sits inside its
    # throttle window, the ledger must still stop growing — hard cap outranks
    # failure retry (prevents +1-per-storm-pass OOM feedback loop).
    _HARD_CAP = _MAX_TRACKED_TARGETS + 8   # ≈40 tracked targets

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
        # All target ids this page ever created via _create_target — used by
        # _close_target's sweep to reclaim tabs orphaned when a later
        # _connect() overwrote _target_id (see _close_target docstring).
        self._created_targets = list()  # insertion-ordered; oldest first
        self._close_failures = {}   # {target_id: (last_attempt_ts, fail_count)} — throttle+count failed closes
        self._msg_id = 0
        self._key_last_seen = {}  # key -> timestamp of last refresh
        self._api_urls = {}       # remapped_key -> original URL for re-fetch
        self._last_data_max_age = 600  # max age (seconds) for _last_data entries
        self._last_data_ts = {}   # key -> timestamp when last added to _last_data
        # RLock so a caller can hold the navigation lock across
        # navigate_stock() AND get_data() without deadlocking on the
        # re-entrant acquire inside navigate_stock(). This closes the race
        # where a concurrent request navigates the shared page to a different
        # code between the navigation and the data read.
        self._navigate_lock = threading.RLock()
        self._reconnect_lock = threading.Lock()  # serializes _reconnect / _ensure_ws
        self._last_sweep = time.time()  # heartbeat orphan-sweep gate (every ~300s)
        self._connect()
        if heartbeat:
            threading.Thread(target=self._heartbeat, daemon=True).start()

    def _http_url(self):
        return f"http://{self.cdp_host}:{self.cdp_port}"

    def _next_id(self):
        with self._ws_lock:
            self._msg_id += 1
            return self._msg_id

    def _create_target(self):
        """Create a new browser tab via CDP Target.createTarget."""
        import websocket
        tabs = json.loads(
            urllib.request.urlopen(f"{self._http_url()}/json", timeout=5).read()
        )
        if not tabs:
            return None, None
        browser_ws = tabs[0]['webSocketDebuggerUrl']
        browser_ws = browser_ws.replace('127.0.0.1', self.cdp_host).replace('localhost', self.cdp_host)
        # 5s cap on every CDP window here: bounds the _reconnect_lock hold when
        # Chrome is half-dead (healthy responses arrive well under 5s).
        ws = websocket.create_connection(browser_ws, timeout=5)
        ws.settimeout(5)  # covers the bare recv() below (default would be 30s)
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

    def _connect(self, budget=None):
        """Create target, connect persistent WS, inject interceptor, navigate.

        budget: absolute deadline shared across retry attempts (set by
        _reconnect) — when exhausted, fail fast so _reconnect_lock is never
        held for minutes by a half-dead Chrome.
        """
        import websocket
        if budget and time.time() >= budget:
            raise RuntimeError(f"[CDP:{self.name}] connect budget exhausted")
        target_id, ws_url = self._create_target()
        if not target_id:
            raise RuntimeError(f"Failed to create CDP target for {self.name}")

        # Set _target_id early so _close_target() can clean up on any failure.
        with self._ws_lock:
            active = self._target_id  # pre-connect active target — never evict it
            evicted = None
            if len(self._created_targets) >= self._MAX_TRACKED_TARGETS:
                # Evict oldest entry; never evict the current active target.
                # Skip ids inside their close-throttle window (same rule as
                # _close_target) so a stubborn failed target isn't re-picked
                # every eviction while closable orphans starve at the tail.
                evict_now = time.time()
                for i, old_id in enumerate(self._created_targets):
                    if old_id != active and evict_now - self._close_failures.get(old_id, (0, 0))[0] >= self._CLOSE_THROTTLE:
                        evicted = self._created_targets.pop(i)
                        break
                if evicted is None and len(self._created_targets) >= self._HARD_CAP:
                    # all candidates sit in their throttle window — hard cap
                    # outranks throttle: force-evict the oldest non-active.
                    for i, old_id in enumerate(self._created_targets):
                        if old_id != active:
                            evicted = self._created_targets.pop(i)
                            break
            self._created_targets.append(target_id)
            self._target_id = target_id
        if evicted and not self._close_one_target(evicted):
            now = time.time()
            if len(self._created_targets) >= self._HARD_CAP:
                # Hard cap outranks failure retry: stop re-registering, or the
                # ledger grows +1 per failed eviction (OOM feedback loop).
                self._close_failures.pop(evicted, None)
                log.warning(f'[CDP:{self.name}] evicted target {evicted} close failed; '
                            f'ledger at hard cap, tracking dropped (tab may remain in Chrome)')
            else:
                # keep the id in the sweep pool so the throttled retry +
                # ≥3-failure drop path reclaims it; silent drop would leak a
                # renderer per _connect (OOM loop).
                self._close_failures[evicted] = (now, 1)
                with self._ws_lock:
                    # index 0 = oldest: re-insert at head so further evictions
                    # reclaim the oldest orphans first.
                    self._created_targets.insert(0, evicted)
                log.warning(f'[CDP:{self.name}] evicted target {evicted} close failed; '
                            f'reregistered for throttled retry (tab may remain in Chrome)')
        elif evicted:
            # Close succeeded — drop the dead failure entry (hard-evicted ids
            # provably sit in their throttle window; same rule as sweep).
            self._close_failures.pop(evicted, None)
        if budget and time.time() >= budget:
            # Clock-bounded reclaim: an unbounded full sweep here piles 18-24s
            # of cleanup onto the very storm path that just exhausted budget.
            self._close_target(close_budget=time.time() + 5)
            raise RuntimeError(f"[CDP:{self.name}] connect budget exhausted")
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
        except Exception:
            self._close_target(close_budget=time.time() + 5)  # close orphaned tab, bounded
            raise
        try:
            self._send_on(ws, {'id': self._next_id(), 'method': 'Page.enable'})
            self._send_recv_on(ws, {'id': self._next_id(), 'method': 'Page.addScriptToEvaluateOnNewDocument',
                                      'params': {'source': INTERCEPTOR_JS}})
            self._send_on(ws, {'id': self._next_id(), 'method': 'Page.navigate',
                                'params': {'url': self.target_url}})
            # 5s cap (was 15s): loadEventFired arrives in <1s on healthy pages;
            # the old 15s window let a half-dead page hold _reconnect_lock long.
            load_deadline = min(time.time() + 5, budget) if budget else time.time() + 5
            while time.time() < load_deadline:
                try:
                    msg = self._recv_on(ws, timeout=5)
                    if msg.get('method') == 'Page.loadEventFired':
                        break
                except:
                    break
        except Exception:
            ws.close()
            self._close_target(close_budget=time.time() + 5)  # bounded reclaim
            raise

        self._ws = ws
        log.info(f"  \u2713 CDP page '{self.name}' \u2192 {self.target_url}")

    def _send_on(self, ws, msg):
        # websocket settimeout is persistent on the socket: a prior recv loop
        # may have left it at ~0, which makes the next sendall fail instantly
        # (spurious reconnect + cache.clear()). Re-assert a sane window so
        # send itself gets at least one full window.
        ws.settimeout(5)  # send only blocks when the socket buffer is full
        ws.send(json.dumps(msg))

    def _recv_on(self, ws, timeout=5):
        ws.settimeout(timeout)
        return json.loads(ws.recv())

    def _send_recv_on(self, ws, msg, timeout=5):
        """Send on a given WS and wait for the matching response."""
        self._send_on(ws, msg)
        msg_id = msg['id']
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            # remaining≈0 makes settimeout fail in <1ms — a spurious timeout
            # callers treat as a dead connection (spurious reconnect +
            # cache.clear()). Give one last full window instead.
            remaining = max(remaining, 0.5)
            try:
                resp = self._recv_on(ws, timeout=remaining)
                if resp.get('id') == msg_id:
                    return resp
            except:
                break
        return {}

    def _send(self, msg):
        self._ws.send(json.dumps(msg))

    def _recv(self, timeout=5):
        self._ws.settimeout(timeout)
        return json.loads(self._ws.recv())

    def _send_recv(self, msg, timeout=5):
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
            with self._ws_lock:
                self._send({'id': self._next_id(), 'method': 'Runtime.evaluate',
                            'params': {'expression': f'fetch("{escaped}",{{cache:"no-store"}}).then(function(r){{return r.json()}}).then(function(d){{window.__cdp_refetch["{escaped}"]=d}}).catch(function(){{}})',
                                       'awaitPromise': False, 'returnByValue': False}})
            return True
        except Exception as e:
            log.warning(f'[CDP:{self.name}] re_fetch_api failed for {url}: {e}')
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
            log.warning(f'[CDP:{self.name}] evaluate_fetch failed for {url}: {e}')
            return None

    def _heartbeat_interval(self):
        """Return heartbeat sleep interval based on China A-share trading hours.

        Trading (Mon-Fri 09:30-11:30, 13:00-15:00 UTC+8): 10s.
        Outside trading: 60s — data doesn't change, reduce polling.
        BR-CDP-8: trading-hours judgement has a single source in config.
        """
        return 10 if config._is_trading_hours() else 60

    def _evict_stalest_last_data_locked(self):
        """Drop the stalest ``_last_data`` entry with symmetric bookkeeping (P2-⑤).

        The hard cap used to delete only ``_last_data``, leaking one
        ``_last_data_ts`` entry per eviction (symmetric tables drifted apart and
        grew without bound).  ``_key_last_seen`` is the freshness clock shared
        with ``self.cache``'s TTL sweep, so it (and the ``_api_urls`` re-fetch
        registry) is dropped only once the key is gone from the live cache too —
        otherwise the cache sweep would skip the key forever and leak it there
        instead.  Caller must hold ``self._lock``.
        """
        oldest = min(self._last_data,
                     key=lambda k: self._key_last_seen.get(k, 0))
        del self._last_data[oldest]
        self._last_data_ts.pop(oldest, None)
        if oldest not in self.cache:
            self._key_last_seen.pop(oldest, None)
            self._api_urls.pop(oldest, None)

    def _ingest_payload(self, api_map, ws_data, now, run_refetch=True):
        """Merge collected API/WS payload into caches with freshness maintenance.

        Caller must hold `self._lock`. Shared by the heartbeat loop and the
        synchronous refresh() so both stay behaviorally identical.
        """
        if api_map:
            remapped = remap_keys(api_map)
            self.cache.update(remapped)
            self._last_data.update(remapped)
            for k in remapped:
                self._last_data_ts[k] = now
            if len(self._last_data) > self._LAST_DATA_MAX_KEYS:
                # Evict stalest keys until within cap; each eviction keeps the
                # _last_data_ts / _key_last_seen side tables in sync (P2-⑤).
                while len(self._last_data) > self._LAST_DATA_MAX_KEYS:
                    self._evict_stalest_last_data_locked()
            for url_key, raw_val in api_map.items():
                mapped = next((name for p, name in API_KEY_MAP.items()
                               if p in str(url_key)), None)
                if mapped:
                    self._key_last_seen[mapped] = now
                    self._api_urls[mapped] = url_key
                else:
                    # Unmapped URL (captured but not remappable, e.g. a
                    # '/index/ann' vs 'quote/index/ann' mismatch): track it so
                    # the TTL sweep below expires it from self.cache instead of
                    # letting it live there forever.
                    self._key_last_seen[url_key] = now
            if len(self.cache) > self._LAST_DATA_MAX_KEYS:
                # Shared cap with _last_data: evict the stalest key so
                # self.cache can't grow unbounded either.
                oldest = min(self.cache, key=lambda k: self._key_last_seen.get(k, 0))
                del self.cache[oldest]
                self._key_last_seen.pop(oldest, None)
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
        if run_refetch:
            # Proactively re-fetch low-frequency APIs — page handles high-frequency
            RE_FETCH_AFTER = 25
            for key in list(self._api_urls.keys()):
                if key in self._PAGE_REFRESHED_KEYS:
                    continue
                last_seen = self._key_last_seen.get(key, 0)
                if last_seen and now - last_seen > RE_FETCH_AFTER:
                    self._re_fetch_api(self._api_urls[key])
        self.last_updated = now

    def _heartbeat(self):
        """Background loop: poll collected data, reconnect on failure."""
        empty_count = 0
        while self._running:
            time.sleep(self._heartbeat_interval())
            try:
                alive = self._evaluate('typeof window.__cdp_api !== "undefined"', timeout=5)
                if not alive:
                    log.warning(f"[CDP:{self.name}] interceptor lost, reconnecting...")
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
                        log.warning(f"[CDP:{self.name}] {empty_count}x empty polls, forcing reconnect...")
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
                        log.warning(f"[CDP:{self.name}] {empty_count}x empty polls, forcing reconnect...")
                        self._reconnect()
                        empty_count = 0
                    continue

                with self._lock:
                    self._ingest_payload(all_api, ws_data, time.time())
                empty_count = 0
                # _close_target only runs on failure paths, so healthy streaks
                # never reclaim tabs orphaned by an earlier failed close. Sweep
                # at low frequency; skip when nothing beyond the active target
                # is tracked (len==1) so a healthy page is never torn down.
                if time.time() - self._last_sweep >= 300:
                    with self._ws_lock:
                        has_orphans = len(self._created_targets) > 1
                    if has_orphans:
                        # Sweep only orphans — never tear down the healthy
                        # active tab. Bounded lock wait (best-effort sweep):
                        # skip the round if the lock is busy so the sweep
                        # can't starve _ensure_ws/_reconnect, and clock-budget
                        # the sweep itself so a half-dead Chrome can't hold
                        # the lock for minutes.
                        if not self._reconnect_lock.acquire(timeout=2):
                            log.debug(f"[CDP:{self.name}] orphan sweep skipped: _reconnect_lock busy")
                        else:
                            try:
                                self._close_target(include_active=False, close_budget=time.time() + 5)
                            finally:
                                self._reconnect_lock.release()
                    self._last_sweep = time.time()

            except Exception as e:
                log.error(f"[CDP:{self.name}] heartbeat: {e}, reconnecting...")
                self._reconnect()
                empty_count = 0

    def _close_target(self, include_active=True, close_budget=None):
        """Close the tabs this page owns (idempotent).

        `_target_id` is only cleared after a CONFIRMED close: if closing fails
        (Chrome half-dead during OOM storms), the id is kept so later reconnect
        paths (_ensure_ws / _reconnect) retry the cleanup instead of silently
        leaking the tab. Every target id this page ever created is also swept,
        so tabs orphaned when a later _connect() overwrote _target_id still get
        reclaimed.

        Budget-capped: at most _CLOSE_BUDGET candidates per call (bounds the
        _reconnect_lock hold); failed closes are throttled _CLOSE_THROTTLEs to
        avoid re-hitting the same failing batch on every storm pass.
        close_budget: optional absolute deadline — the sweep stops when it
        expires (leftover candidates stay in the ledger for the next round),
        bounding the lock hold even when each candidate burns its full close
        path on a half-dead Chrome.
        """
        now = time.time()
        with self._ws_lock:
            tid = self._target_id
            leftovers = [t for t in self._created_targets if t != tid]
        # include_active=False (heartbeat sweep): never tear down the healthy
        # active tab, only reclaim orphans. tid never enters candidates, so the
        # _target_id-clear below is naturally skipped.
        candidates = ([tid] if tid and include_active else []) + leftovers
        # Skip targets that failed close within the throttle window
        candidates = [t for t in candidates
                      if now - self._close_failures.get(t, (0, 0))[0] >= self._CLOSE_THROTTLE]
        candidates = candidates[:self._CLOSE_BUDGET]
        ok = True
        tid_ok = True  # stays True once the CURRENT target is confirmed closed
        for t in candidates:
            if close_budget is not None and time.time() >= close_budget:
                if t == tid:
                    tid_ok = False  # tid not processed — keep it tracked
                break  # clock budget exhausted — leftovers stay for the next round
            if self._close_one_target(t):
                with self._ws_lock:
                    try:
                        self._created_targets.remove(t)
                    except ValueError:
                        pass
                self._close_failures.pop(t, None)
            else:
                ok = False
                if t == tid:
                    tid_ok = False
                _, fail_count = self._close_failures.get(t, (0, 0))
                fail_count += 1
                if fail_count >= self._CLOSE_MAX_FAILURES:
                    # Give up on a persistently-failing target: drop it from
                    # ledger and budget; warn the tab may remain in Chrome.
                    log.warning(f'[CDP:{self.name}] target {t} close failed {fail_count}x, '
                                f'dropped from tracking (tab may remain in Chrome)')
                    # Drop the throttle entry too: the id is removed from the
                    # ledger below so it can never re-enter candidates — the
                    # (ts,count) record would stay a permanent dead entry.
                    self._close_failures.pop(t, None)
                    with self._ws_lock:
                        if t == tid:
                            # Abandoned ACTIVE target: clear _target_id and
                            # idempotently close+detach its WS (exception-safe)
                            # so the ghost stops being tracked and no evaluation
                            # targets the dead tab.
                            if self._target_id == tid:
                                self._target_id = None
                            try:
                                self._ws.close()
                            except Exception:
                                pass
                            self._ws = None
                        try:
                            self._created_targets.remove(t)
                        except ValueError:
                            pass
                else:
                    self._close_failures[t] = (now, fail_count)  # throttle + count retries
        if tid and tid in candidates and tid_ok:
            # Clear _target_id as soon as the current tab is confirmed closed,
            # even if a leftover close failed — otherwise _target_id keeps
            # pointing at a ghost tab and later sweeps waste a budget slot
            # re-closing it. Only genuinely-failed closes enter the ledger.
            with self._ws_lock:
                if self._target_id == tid:
                    self._target_id = None
        return ok

    def _close_one_target(self, tid):
        """Close a single CDP target; True if confirmed gone (or already gone).

        Primary path: browser WS Target.closeTarget. If that fails (Chrome
        half-dead during OOM storms), fall back to the HTTP /json/close
        endpoint — a different transport that works even when the browser WS
        channel is jammed. "Target not found" counts as success: the tab is
        already gone, which is all we care about.
        """
        try:
            info = json.loads(
                urllib.request.urlopen(f"{self._http_url()}/json/version", timeout=2).read()
            )
            browser_ws_url = info.get('webSocketDebuggerUrl', '')
            if not browser_ws_url:
                raise RuntimeError('no webSocketDebuggerUrl in /json/version')
            browser_ws_url = browser_ws_url.replace('127.0.0.1', self.cdp_host)\
                                           .replace('localhost', self.cdp_host)
            import websocket
            ws = websocket.create_connection(browser_ws_url, timeout=2)
            try:
                ws.send(json.dumps({
                    'id': 1, 'method': 'Target.closeTarget',
                    'params': {'targetId': tid}
                }))
                deadline = time.time() + 2
                while time.time() < deadline:
                    ws.settimeout(deadline - time.time())
                    resp = json.loads(ws.recv())
                    if resp.get('id') == 1:
                        err = resp.get('error')
                        if not err or 'No target with given id' in str(err):
                            return True  # confirmed closed / already gone
                        break  # hard CDP error — fall through to HTTP fallback
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
        except Exception as e:
            log.warning(f'[CDP:{self.name}] closeTarget {tid} via browser WS failed: {e}')
        # Fallback: HTTP /json/close — different transport, works when WS jammed.
        try:
            urllib.request.urlopen(f"{self._http_url()}/json/close/{tid}", timeout=2).read()
            return True
        except Exception as e:
            body = ''
            if hasattr(e, 'read'):
                try:
                    body = e.read().decode(errors='replace').lower()
                except Exception:
                    pass
            if 'no such target' in body:
                return True  # already gone
            log.warning(f'[CDP:{self.name}] closeTarget {tid} via /json/close failed: {e}')
            return False

    def _reconnect(self):
        """Close old WS + tab, try reconnecting. If Chrome died, restart it.

        Serialized by _reconnect_lock so heartbeat + navigation threads
        never race on self._ws / self._target_id.
        """
        # Lock hold is bounded: connects carry a 35s budget and each
        # _close_target sweep a per-call clock budget — late waiters behind
        # this lock don't stall unboundedly (sweep uses timeout acquire).
        with self._reconnect_lock:
            try:
                if self._ws:
                    self._ws.close()
            except:
                pass
            self._close_target(close_budget=time.time() + 5)
            with self._lock:
                self.cache.clear()
                self._key_last_seen.clear()
                self._api_urls.clear()
                # P1-3: the serving cache is session data too.  Clearing only
                # `_key_last_seen` left `_last_data` behind, and a *missing*
                # clock used to count as fresh in `get_data` — so the
                # pre-restart snapshot stayed "fresh forever" and was re-issued
                # with a new timestamp by the next fetch.  Clear both together.
                self._last_data.clear()
                self._last_data_ts.clear()
            # Three attempts share ONE budget so a half-dead Chrome can't hold
            # _reconnect_lock for minutes (healthy connects take <2s each).
            budget = time.time() + 35
            for attempt in range(3):
                try:
                    self._connect(budget)
                    return
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
            # All 3 attempts failed — Chrome might have crashed. ensure_chrome()
            # enforces a throttle window; retry until it passes instead of
            # giving up (avoids permanent CDP outage on 2c2g OOM crash loops).
            log.error(f"[CDP:{self.name}] 3 reconnect attempts failed, trying to restart Chrome...")
            deadline = time.time() + _RECONNECT_RETRY_WINDOW
            while self._running and time.time() < deadline:
                if ensure_chrome():
                    for attempt in range(3):
                        try:
                            # Same budget semantics as phase 1: bound each
                            # connect by the retry-window deadline so a
                            # half-dead Chrome can't hold _reconnect_lock
                            # past its remaining window.
                            self._connect(deadline)
                            return
                        except Exception as e:
                            if attempt < 2:
                                time.sleep(2)
                # ensure_chrome() was throttled or Chrome still starting — wait
                time.sleep(2)
            log.error(f"[CDP:{self.name}] reconnect failed after Chrome restart")

    def get_data(self):
        """Return merged data — latest from live cache, gaps filled by _last_data.

        `_last_data` entries older than `_last_data_max_age` are skipped to
        prevent serving permanently stale data.  The age clock is
        `_last_data_ts` (written together with the value, cleared on reconnect);
        a *missing* clock counts as stale, never fresh — treating it as fresh
        let a reconnect's cleared clock re-issue the old snapshot indefinitely
        (P1-3).
        """
        with self._lock:
            now = time.time()
            merged = {}
            for key, val in self._last_data.items():
                ts = self._last_data_ts.get(key)
                if ts is not None and now - ts < self._last_data_max_age:
                    merged[key] = val
            merged.update(self.cache)
            return merged

    def refresh(self):
        """Force an immediate data pull. Returns True on success."""
        try:
            raw = self._evaluate(
                'var d=JSON.stringify({api:window.__cdp_api,refetch:window.__cdp_refetch,ws:window.__cdp_ws});'
                'window.__cdp_api={};window.__cdp_refetch={};window.__cdp_ws=[];d',
                timeout=10)
            if raw:
                data = json.loads(raw)
                api_data = data.get('api', {}) or {}
                refetch_data = data.get('refetch', {}) or {}
                ws_data = data.get('ws', []) or {}
                all_api = {**api_data, **refetch_data}
                with self._lock:
                    self._ingest_payload(all_api, ws_data, time.time())
                return True
        except:
            pass
        return False

    def _ensure_ws(self):
        """Reconnect WebSocket if disconnected (stock page, no heartbeat).

        Serialized by _reconnect_lock so it doesn't race with _reconnect().
        """
        with self._reconnect_lock:
            if self._ws:
                try:
                    if self._evaluate('1', timeout=3):
                        return True
                except Exception:
                    pass
            if self._target_id:
                self._close_target(close_budget=time.time() + 5)
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
            self._ws = None
            # Try immediate reconnects; if they fail, ensure Chrome is up
            # (waiting out the restart throttle) before retrying.
            budget = time.time() + 35  # same semantics as _reconnect phase 1
            for attempt in range(3):
                try:
                    self._connect(budget)
                    return True
                except Exception:
                    if attempt == 0:
                        ensure_chrome()  # restart Chrome if down
                    time.sleep(2)
            deadline = time.time() + _RECONNECT_RETRY_WINDOW
            while self._running and time.time() < deadline:
                if ensure_chrome():
                    for attempt in range(3):
                        try:
                            self._connect(deadline)
                            return True
                        except Exception:
                            if attempt < 2:
                                time.sleep(2)
                time.sleep(2)
            return False

    _nav_restart_counter = 0
    _MAX_PAGE_NAV_BEFORE_RECONNECT = 30
    _restart_counter_lock = threading.Lock()  # class-level: protects shared counter across instances

    def _maybe_reconnect(self):
        """Restart Chrome entirely after threshold navigations to free memory.

        The shared counter is bumped under the class-level
        _restart_counter_lock for exactly a counter update + threshold
        decision — no I/O. The actual restart (full_chrome_restart +
        _reconnect, 4-24s) runs OUTSIDE that lock, so nav-threshold pages
        block only each other's counter bump, not the whole navigation set.
        The heavyweight restart is still single-threaded via
        _chrome_restart_lock inside full_chrome_restart(); other pages that
        cross the threshold meanwhile just bump the counter and re-connect
        to the fresh Chrome via _ensure_ws().
        """
        with CDPPage._restart_counter_lock:
            CDPPage._nav_restart_counter += 1
            if CDPPage._nav_restart_counter >= self._MAX_PAGE_NAV_BEFORE_RECONNECT:
                CDPPage._nav_restart_counter = 0
            else:
                return False
        if time.time() - _last_chrome_restart < _CHROME_RESTART_THROTTLE * 2:
            # Chrome was just restarted (nav threshold or watchdog): a second
            # full_chrome_restart would kill the fresh Chrome back-to-back,
            # doubling the CDP-unavailable window. Counter already reset —
            # caller reconnects to the new Chrome via _ensure_ws() (self-heal).
            log.info(f"[CDP:{self.name}] nav threshold reached but Chrome restarted "
                  f"recently — skipping full restart, reconnecting to new Chrome")
            return False
        log.info(f"[CDP:{self.name}] nav threshold ({self._MAX_PAGE_NAV_BEFORE_RECONNECT}) reached, "
              f"full Chrome restart...")
        full_chrome_restart(f"http://{self.cdp_host}:{self.cdp_port}")
        # Reconnect this page to the fresh Chrome (clears cache, creates new tab)
        self._reconnect()
        return True

    def _fresh_secu_code_locked(self, now):
        """`secu_code` of a non-aged `_last_data['basic_info']`, else None.

        Caller must hold ``self._lock``.  The age clock is ``_last_data_ts`` —
        written together with the value and cleared on reconnect — and a missing
        clock counts as *stale* (P1-3), so a reconnect can no longer leave the
        old snapshot matching a code "forever".
        """
        bi = (self._last_data.get('basic_info') or {}).get('data') or {}
        ts = self._last_data_ts.get('basic_info')
        if ts is None or now - ts >= self._last_data_max_age:
            return None
        return bi.get('secu_code') if isinstance(bi, dict) else None

    def _acquire_navigate_lock(self, timeout):
        """Bounded ``_navigate_lock`` acquire (P1-2).

        Returns False without blocking when the timeout is non-positive or the
        lock stays busy for the whole budget, so a queued request can degrade
        instead of parking a worker/admission slot behind a ~60s navigation.
        """
        wait = max(0.0, timeout)
        if wait <= 0.0:
            return False
        try:
            return self._navigate_lock.acquire(timeout=wait)
        except Exception:
            return False

    def navigate_stock(self, stock_code, timeout=15, tabs=('fund_flow', 'f10')):
        """Navigate to a stock code, wait for fresh data, return True on success.

        Fair queuing with a *bounded* wait (P1-2): the lock wait is capped by
        ``timeout``, so a busy page degrades to False instead of parking the
        caller indefinitely (the CDP page pool is tiny and an unbounded wait
        used to occupy every admission slot → site-wide 503).

        Args:
            tabs: Which tab sections to click after navigation.
                  ('fund_flow', 'f10') — both tabs (legacy, ~6s extra).
                  ('fund_flow',)       — fund flow only.
                  ()                   — no tabs, fastest (~2-3s total).
        """
        # P1-6: operate on one canonical spelling; both accepted ingress forms
        # ('600519.SH' / 'sh600519') then compare equal against the upstream
        # SecuCode instead of one of them never matching.
        stock_code = config.canonical_code(stock_code) or stock_code
        url = f'https://www.cls.cn/stock?code={stock_code}'
        # Fast path: skip navigation only when the cached snapshot is *fresh*
        # for this code (max-age checked) — otherwise a stale page would never
        # re-navigate (P1-3).
        with self._lock:
            cached = self._fresh_secu_code_locked(time.time())
        if _same_code(cached, stock_code):
            return True
        # Block until lock acquired — fair queuing, bounded by the budget (P1-2)
        wait_start = time.time()
        if not self._acquire_navigate_lock(timeout):
            return False
        try:
            remaining = timeout - (time.time() - wait_start)
            if remaining < 2:
                with self._lock:
                    cached = self._fresh_secu_code_locked(time.time())
                return _same_code(cached, stock_code)
            # Free Chrome renderer processes by reconnecting page periodically
            self._maybe_reconnect()
            if not self._ensure_ws():
                return False
            def _send_navigate():
                with self._ws_lock:
                    self._evaluate(
                        'window.__cdp_api={};window.__cdp_refetch={}',
                        timeout=3)
                    self._send_recv({'id': self._next_id(), 'method': 'Page.navigate',
                                     'params': {'url': url}}, timeout=min(10, remaining))
            nav_started = time.time()
            try:
                _send_navigate()
            except Exception:
                if not self._ensure_ws():
                    return False
                _send_navigate()
            load_deadline = time.time() + min(15, remaining)
            with self._ws_lock:
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
                if _same_code(bi.get('secu_code'), stock_code):
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
                # Fail fast: page settled on a wrong stock code — but only if
                # the wrong code has persisted well past the navigation
                # transition window. Under concurrent navigation of the shared
                # page pool, the page legitimately shows the *previous* code
                # for a few seconds while the new code's page loads, so a
                # naive stable_count abort yields spurious nulls.
                secu_code = config.canonical_code(bi.get('secu_code'))
                if secu_code:
                    if secu_code == last_seen_code:
                        stable_count += 1
                    else:
                        last_seen_code = secu_code
                        stable_count = 0
                    if stable_count >= 3 and (time.time() - nav_started) > 6:
                        break
                time.sleep(0.5)
            self.refresh()
            data = self.get_data()
            bi = (data.get('basic_info') or {}).get('data') or {}
            return _same_code(bi.get('secu_code'), stock_code)
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
        # Bounded shutdown: half-dead Chrome burns ~24s/page budget-less
        # (3 candidates × 8s); 5 pages would stall exit ~2min.
        self._close_target(close_budget=time.time() + 5)


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
            _mark_idle()                                  # initial state is idle (idempotent)
            return True
        except Exception:
            _mark_unavailable()
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
            log.error(f"  \u2717 Failed to create page '{name}': {e}")
            return None

    def get_page(self, name):
        return self.pages.get(name)

    def shutdown(self):
        for page in self.pages.values():
            page.close()

    def __del__(self):
        self.shutdown()
