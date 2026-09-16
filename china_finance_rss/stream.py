"""

Subscription groups are reaped automatically after STREAM_GROUP_IDLE_TTL seconds without any live connection (client must re-POST to re-subscribe after that).
SSE push server + subscription groups for short-line trading clients.

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
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import config, metrics
from .config import (
    STREAM_PORT,
    MAX_STREAM_CONNS, MAX_CODES_PER_SUB, MAX_DEDUP_CODES, MAX_GROUPS,
    MGMT_BODY_TIMEOUT, STREAM_PING_INTERVAL, STREAM_QUEUE_BYTES_BUDGET,
    stream_frame_bytes, _trading_tiers,
)
from .stock_api import (
    BATCH_MAX_WORKERS, _prefetch_advance, _prefetch_slice, cached_batch,
    handle_cls_basic_infos, handle_cls_fundflow, handle_cls_timeline,
)

log = logging.getLogger('stream')

# field -> handler; _FIELD_DOMAINS maps field name → cached_batch domain
# (explicit so a future field/domain split cannot silently miss the cache).
_FIELD_HANDLERS = {
    'quote': handle_cls_basic_infos,
    'fundflow': handle_cls_fundflow,
    'timeline': handle_cls_timeline,
}
_FIELD_DOMAINS = {'quote': 'quote', 'fundflow': 'fundflow', 'timeline': 'timeline'}
_STREAM_REFRESH_KEY = 'stream_refresh'

# ── Refresh capacity model (BR-STR-16, recalibrated by BUG-P6C-01/P6C-06) ──
# A tick's fresh refresh costs `codes × _fetches_per_code(fields)` upstream REST
# calls, executed as per-field *serial* phases (each phase ≤ BATCH_MAX_WORKERS
# wide).  `coverage` is therefore measured in fetch-calls per tick, never in
# codes; `coverage_codes` is the code count whose full refresh fits the budget.
# `fields` is the *subscribed* set (`_subscribed_fields()`), so a quote-only
# group pays 1 call/code instead of the historical unconditional 3-field cost.
_TICK_BUDGET_FRACTION = 0.8
# Serial-equivalent seconds one upstream REST call occupies one batch worker.
# Recalibrated against the r3 deployment measurement (BUG-P6C-06): the cold
# path costs ≈2.2 s per worker-call (20 codes × 3 fields cold = 10.5 s at
# BATCH_MAX_WORKERS=8; the per-tick 1.0 estimate was still ~2× optimistic, so a
# 51-fetch tick measured ≈14 s > the 6.4 s budget).  At tick=8 /
# BATCH_MAX_WORKERS=8 this yields coverage=23 fetch-calls per tick, i.e.
# coverage_codes=23 for a one-domain group — a <20-code group full-refreshes
# every tick (23 × 2.2 / 8 = 6.3 s ≤ 0.8 × 8 s).
_PER_FETCH_EST = 2.2
# Upstream REST calls per code per field.  Every steady-state domain costs ONE
# call/code: `quote` (handle_cls_basic_infos → fetch_cls_basic_info) is
# two-phase — basic_info + stock detail (sector) — but phase 2 is served from
# the 7-day `sector` cache once warm, so the steady-state cost is 1 (the old
# `2` priced the cold path, over-charging every tick — BUG-P6C-06).
# fundflow/timeline were always 1.  Unknown (test-injected) fields default to
# _DEFAULT_FETCH_CALLS.  This map is the single authority for the per-code cost
# model.
_FIELD_FETCH_CALLS = {'quote': 1, 'fundflow': 1, 'timeline': 1}
_DEFAULT_FETCH_CALLS = 1

# P1-4 admission cap (create_group / patch_group): the cross-group distinct-frame
# working set may not exceed the queue byte budget, otherwise a legal
# subscription set would force every tick to evict other groups' real frames.
_FRAME_BUDGET_ERR = ('subscription frames would exceed the '
                     f'{STREAM_QUEUE_BYTES_BUDGET}-byte stream frame budget')

# P2: consecutive `push_loop` failures back off 1, 2, 4, … ticks up to this cap,
# so an exception path can never degrade into the old ~1 s spin (which re-ran the
# round up to `tick` times per interval and multiplied upstream pressure).
_PUSH_ERROR_BACKOFF_CAP_TICKS = 8

# Workers kept free above the SSE connection cap for management requests
# (POST/PATCH/DELETE/GET status) — see `make_stream_server`.
_MGMT_WORKER_RESERVE = 10

_groups = {}            # sid -> SubscriptionGroup
_groups_lock = threading.RLock()   # nested acquisition in CRUD paths
_conn_count = 0
_conn_count_lock = threading.Lock()

# distinct-frame accounting (BR-STR-5..9). _frame_bytes_lock is a leaf: it only
# guards integer/dict arithmetic + metrics gauge publication (no other lock).
_frame_bytes_lock = threading.Lock()
_queue_bytes = 0
_group_bytes = {}       # sid -> bytes retained by that group's distinct frames
_live_frames = 0
_frame_peak_bytes = 0
_slice_view_lock = threading.Lock()   # leaf lock for _prefetch_slice's view dict


class SubscriptionGroup:
    """A named watchlist: codes + subscribed fields + live SSE connections.

    BR-STR-1: `codes` is always a frozenset and `fields` a tuple. Mutation
    happens by whole replacement under _groups_lock, so the broadcast path can
    iterate them lock-free (BR-STR-4).
    """

    def __init__(self, sid, codes, fields):
        self.sid = sid
        self.fields = tuple(fields)
        self.codes = frozenset(codes)
        self.conns = set()          # of _SSEConn
        self.conns_lock = threading.Lock()
        self.last_push_ts = 0.0
        self.created_ts = time.time()


def _new_sid():
    while True:
        sid = uuid.uuid4().hex[:12]
        with _groups_lock:
            if sid not in _groups:
                return sid


def _valid_fields(fields):
    """Return the requested fields, deduped; ``None``/empty ⇒ all fields.

    S2-4 (fail-closed): an explicitly requested *unknown* field raises
    ``ValueError`` instead of being silently intersected away.  The old
    ``out or list(_FIELD_HANDLERS)`` fallback turned ``fields=["nonsense"]``
    into all three domains — tripling frame bytes and upstream cost while the
    client got a structure it never asked for and no error signal.  Only
    "no fields supplied" falls back to the all-field default.
    """
    if not fields:
        return list(_FIELD_HANDLERS)
    out = []
    for f in fields:
        if f not in _FIELD_HANDLERS:
            raise ValueError(f'unknown field: {f}')
        if f not in out:
            out.append(f)
    return out


def _deduped_codes_unlocked():
    """Union of codes across ALL groups (CRUD pool-limit ledger).
    Caller must hold _groups_lock."""
    codes = set()
    for g in _groups.values():
        codes |= g.codes
    return codes


def _projected_frame_bytes_unlocked():
    """Steady-state distinct-frame bytes for ALL groups (P1-4 admission cap).

    = Σ_g stream_frame_bytes(|codes_g|, |fields_g|), i.e. the bytes retained
    when every group holds its one current frame.  `_broadcast` retains one
    frame per live group, so keeping this ≤ STREAM_QUEUE_BYTES_BUDGET is what
    prevents the budget from evicting other groups' real frames on every tick.
    Conservatively counts every group's full code set (shared codes included).

    Caller must hold _groups_lock."""
    return sum(stream_frame_bytes(len(g.codes), len(g.fields))
               for g in _groups.values())


def _max_group_frame_bytes_unlocked(exclude_sid=None):
    """Largest single group frame, in bytes (S2-2 admission margin).

    ``exclude_sid`` lets ``patch_group`` re-price the group it is about to
    replace.  Caller must hold _groups_lock."""
    return max((stream_frame_bytes(len(g.codes), len(g.fields))
                for sid, g in _groups.items() if sid != exclude_sid), default=0)


def _active_deduped_codes_unlocked():
    """Union of codes of groups WITH live connections only.

    The refresh pool must follow live demand — a zombie group would
    otherwise keep the CDP fetch loop burning CPU for codes nobody
    consumes. Caller must hold _groups_lock."""
    codes = set()
    for g in _groups.values():
        if g.conns:
            codes |= g.codes
    return codes


def _active_codes():
    """Union of codes of live groups (bounds the per-tick refresh set)."""
    with _groups_lock:
        return _active_deduped_codes_unlocked()


def _subscribed_fields_unlocked():
    """Union of fields subscribed by LIVE groups, in `_FIELD_HANDLERS` order.

    "Live" = has ≥1 connection, the same demand rule as
    `_active_deduped_codes_unlocked` — a zombie group must never keep paying
    for upstream domains nobody consumes.  Ordered by `_FIELD_HANDLERS` so the
    per-field serial phases and the resulting frame layout are deterministic.
    Returns `[]` when no group is live.  Caller must hold `_groups_lock."""
    wanted = set()
    for g in _groups.values():
        if g.conns:
            wanted.update(g.fields)
    return [f for f in _FIELD_HANDLERS if f in wanted]


def _subscribed_fields():
    """Union of fields subscribed by live groups (`[]` when none are live)."""
    with _groups_lock:
        return _subscribed_fields_unlocked()


def _active_targets():
    """``(codes, fields)`` for the current live demand, under ONE lock.

    Reading both together keeps the refresh field set consistent with the code
    set: two separate reads could interleave with a group closing, yielding a
    code pool whose fields are no longer subscribed (BUG-P6C-06).
    """
    with _groups_lock:
        codes = _active_deduped_codes_unlocked()
        if not codes:
            return set(), []
        return codes, _subscribed_fields_unlocked()


def _deduped_codes():
    """Union of codes across all groups (bounds the refresh set)."""
    with _groups_lock:
        return _deduped_codes_unlocked()


def _fetches_per_code(fields=None):
    """Upstream REST calls needed to refresh one code across ``fields``.

    ``fields`` defaults to (or is empty ⇒) every supported field, i.e. the
    historical all-field cost, so direct callers always get a well-defined
    non-zero number.  `_refresh_pool` passes the *subscribed* set, which is
    what makes a quote-only group one third of the old upstream cost.
    """
    fields = _FIELD_HANDLERS if not fields else fields
    return sum(_FIELD_FETCH_CALLS.get(f, _DEFAULT_FETCH_CALLS)
               for f in fields)


def refresh_capacity(tick, fields=None):
    """Return ``(coverage, coverage_codes)`` for ``tick`` (BR-STR-16).

    ``coverage``       fetch-calls/tick fitting the 0.8×tick budget
    ``coverage_codes`` codes/tick whose *full* refresh fits that budget (≥ 1)

    Both are derived from the single calibration pair
    ``_PER_FETCH_EST``/``_FIELD_FETCH_CALLS`` **and the subscribed field set**
    (BUG-P6C-06), so the C1 threshold and the C2 slice size can never disagree
    with each other or with the real per-code upstream cost.
    """
    coverage = max(1, int(_TICK_BUDGET_FRACTION * tick * BATCH_MAX_WORKERS
                          / _PER_FETCH_EST))
    return coverage, max(1, coverage // _fetches_per_code(fields))


def _resolve_refresh_fields(fields):
    """Field set to refresh: explicit arg → live subscription union → all.

    Ordering always follows `_FIELD_HANDLERS` so the per-field serial phases
    and the frame layout stay deterministic.  The all-fields fallback keeps a
    bare ``_refresh_pool(codes)`` (tests / tools / no live subscription)
    working exactly as before.
    """
    if fields is not None:
        wanted = set(fields)
        return [f for f in _FIELD_HANDLERS if f in wanted]
    return _subscribed_fields() or list(_FIELD_HANDLERS)


# ── Last-known value carry-forward (P1-4) ──────────────────────────────────
# C2 shards a large pool, so only `coverage_codes` codes are refreshed per tick
# and the rest used to arrive as pure `null` — indistinguishable from a code
# with no data at all, which made a 200-code subscription >95% null every frame.
# We keep the last non-null value per code/field and carry it into later frames,
# listing those codes in `stale` so a client can still tell "not refreshed this
# tick" (stale) apart from "no data at all" (missing).  Pruned to the live pool
# every tick ⇒ bounded by MAX_DEDUP_CODES.
_last_known = {}
_last_known_lock = threading.Lock()


def _carry_forward(snapshot, codes, fields):
    """Merge last-known values into `snapshot`; return ``(merged, stale_codes)``.

    ``stale_codes`` = codes whose row came (wholly or partly) from a previous
    tick because this tick neither refreshed nor cached them.  Fresh values
    update the store; code keys outside `codes` are dropped (pool shrink
    reclaims memory).  A code is never counted both stale and missing: it only
    becomes stale when a previous value actually exists.
    """
    global _last_known
    stale = set()
    merged = dict(snapshot)
    with _last_known_lock:
        _last_known = {c: _last_known[c] for c in codes if c in _last_known}
        for code in codes:
            row = merged.get(code)
            known = _last_known.get(code)
            if known is None:
                if row is not None:
                    _last_known[code] = {f: v for f, v in row.items()
                                         if v is not None}
                continue
            new_row = dict(row) if row is not None else {}
            carried = False
            for f in fields:
                if new_row.get(f) is None and known.get(f) is not None:
                    new_row[f] = known[f]
                    carried = True
            if row is None or carried:
                merged[code] = new_row
                stale.add(code)
            store = {f: v for f, v in new_row.items() if v is not None}
            if store:
                _last_known[code] = store
            elif code in _last_known:
                del _last_known[code]
    return merged, stale


def _clear_last_known():
    """Drop the carry-forward store (no live demand ⇒ nothing to carry)."""
    with _last_known_lock:
        _last_known.clear()


def _refresh_pool(codes, now=None, fields=None, tick=None, deadline=None):
    """Build {code: {field: data}} = fresh(slice) ∪ cached(active − slice).

    BR-STR-16..24: condition C1 (whole-pool refresh) or per-tick sharded
    round-robin, with the remainder read from the terminal cache (no network).
    Condition C1 is cost-weighted (`fetches_per_code × n ≤ coverage`), so a
    field that costs several upstream calls counts as several.

    BUG-P6C-06: only the *subscribed* field union is refreshed — `fields` when
    given (the scheduler passes what `_active_targets()` read), else
    `_subscribed_fields()`.  The old unconditional `_FIELD_HANDLERS` sweep made
    a quote-only group pay for fundflow + timeline it never asked for; with two
    of the three call sites dropped the same tick budget covers ~3× the codes.

    S2-1: handler-supplied ``_errors`` (the reserved key of
    ``cache.build_batch_response``) is *kept* as ``snapshot['_errors']`` instead
    of being dropped, so the frame can tell an upstream failure apart from
    "no cached data yet".  It is still never a stock item (BR-STR-22 / AR-7).

    `now` is an injection point for tests; the scheduler uses wall-clock time.
    It is also forwarded to the terminal-cache read, so a test can drive the
    sharded (C2) path with genuinely expired cache entries (T4).

    `tick` and `deadline` come from `_push_once` (one tick computation, one
    shared per-tick budget — P1-1/P1-6); a direct caller gets them recomputed
    here, and a field phase that starts past `deadline` is skipped and its codes
    marked ``tick_budget_exceeded`` in ``_errors`` rather than blocking the
    push thread.
    """
    snapshot = {}
    errors = {}                                     # ★ S2-1: code -> error kind
    active = sorted(codes)                          # BR-STR-23: stable order
    n = len(active)
    if n == 0:
        # Direct-call fast path only (tests / tools).  The scheduler never
        # reaches it: `_push_once` guards with `if codes:` and publishes the
        # empty-pool lag reset itself (BUG-P6C-08).  Do NOT move the gauge
        # write back here — that is exactly what made the fix dead code while a
        # direct `_refresh_pool([])` unit test stayed green.
        return snapshot
    fields = _resolve_refresh_fields(fields)
    # ★ P1-6: the scheduler computes `tick` once and passes it in, so the C1/C2
    # threshold and the dispatch cadence can never disagree at a tier flip
    # (09:30/11:30/13:00 gave 8 s here vs 120 s in `_push_once`).
    if tick is None:
        tick = tick_interval()
    if deadline is None:
        # ★ P1-1: all field phases share ONE tick budget.  Without it each
        # handler fell back to `_BATCH_BUDGET_REST` (15 s) and three serial
        # phases could block the push thread for 45 s — every SSE connection
        # starved of `event: quote` exactly when the market is busiest.
        deadline = time.time() + _TICK_BUDGET_FRACTION * tick
    coverage, coverage_codes = refresh_capacity(tick, fields)
    fetches_per_code = _fetches_per_code(fields)

    if fetches_per_code * n <= coverage:            # BR-STR-17: C1
        sl, rest, lag = active, [], 0               # whole pool ⇒ nothing lags
    else:                                           # BR-STR-18: C2 sharded rotation
        view = {c: 0.0 for c in active}             # temporary rotation view
        sl, _next = _prefetch_slice(view, _slice_view_lock, _STREAM_REFRESH_KEY,
                                    coverage_codes)
        _prefetch_advance(_STREAM_REFRESH_KEY, len(sl), n)
        sl_set = set(sl)
        rest = [c for c in active if c not in sl_set]
        lag = -(-n // max(1, len(sl)))              # ceil(n / |slice|)

    for field in fields:                            # fresh (≤ coverage fetches)
        handler = _FIELD_HANDLERS.get(field)
        if handler is None:
            continue    # defensive: `fields` comes from _resolve_refresh_fields,
                        # so this only fires if _FIELD_HANDLERS was patched apart
        if time.time() >= deadline:                 # ★ P1-1: over budget ⇒ skip
            for code in sl:
                errors.setdefault(code, 'tick_budget_exceeded')
            break
        fetched = handler(list(sl), deadline=deadline)  # BR-STR-24: no `dropped`
        if not fetched:
            continue
        for code, data in fetched.items():
            if not isinstance(code, str) or code.startswith('_'):
                if code == '_errors' and isinstance(data, dict):
                    errors.update(data)             # ★ S2-1: keep for the frame
                continue                            # ★ BR-STR-22 / AR-7
            if data is not None:
                snapshot.setdefault(code, {})[field] = data

    if rest:                                        # cached (no network)
        for field in fields:
            domain = _FIELD_DOMAINS.get(field)
            if domain is None:
                continue    # defensive: see the handler guard above
            for code, data in cached_batch(domain, rest, now=now).items():
                if not isinstance(code, str) or code.startswith('_'):
                    continue                        # ★ BR-STR-22 / AR-7 (defence parity)
                if data is not None:
                    snapshot.setdefault(code, {})[field] = data

    metrics.set_gauge('stream_refresh_lag_ticks', lag)   # BR-STR-21
    if errors:
        snapshot['_errors'] = errors                # ★ S2-1: frame metadata only
    return snapshot


def _build_frame(snapshot, codes, fields):
    """Full-snapshot SSE frame (data: {...}).

    S2-1: the frame is a *true* full snapshot — ``items`` covers **every**
    subscribed code, with ``null`` for each requested field that has no data.
    Previously absent codes were silently omitted, so a C2-sharded tick could
    deliver ~7 of 200 subscribed codes with no marker at all: the client could
    not distinguish "no quote" from "upstream down" from "not covered yet".

    Explicit metadata makes that cheap to detect:
      ``codes_total``    subscribed code count for this group
      ``fields``         subscribed field set (requested shape)
      ``missing``        codes with no data for any requested field (sorted)
      ``missing_count``  ``len(missing)``
      ``stale``          codes whose value is carried over from a previous tick
                         (this tick neither refreshed nor cached them); present
                         only when non-empty (P1-4).  A stale code has data, so
                         it is never also in ``missing``.
      ``stale_count``    ``len(stale)``
      ``errors``         code → upstream error kind (`_errors` from the
                         handlers); present only when non-empty.  A code that is
                         in ``missing`` but *not* in ``errors`` has no data and
                         no reported failure (it simply was not refreshed/cached
                         yet and will be covered by a later tick); a code with
                         data can still appear in ``errors`` when one of its
                         fields failed upstream.

    ``codes`` (frozenset) and ``fields`` (tuple) are immutable, so the frame can
    be built outside every lock (BR-STR-2).  Returns None only when ``codes`` is
    empty (no subscription ⇒ nothing to snapshot).
    """
    if not codes:
        return None
    errors = snapshot.get('_errors') if isinstance(snapshot, dict) else None
    stale = snapshot.get('_stale') if isinstance(snapshot, dict) else None
    items = {}
    missing = []
    for code in sorted(codes):                      # deterministic frame bytes
        entry = snapshot.get(code) or {}
        row = {f: entry.get(f) for f in fields}
        if all(v is None for v in row.values()):
            missing.append(code)
        items[code] = row
    payload = {
        'ts': int(time.time() * 1000),
        'codes_total': len(codes),
        'fields': list(fields),
        'items': items,
        'missing': missing,
        'missing_count': len(missing),
    }
    if errors:
        err = {c: errors[c] for c in sorted(errors) if c in items}
        if err:
            payload['errors'] = err
    if stale:
        st = sorted(c for c in stale if c in items)
        if st:
            payload['stale'] = st
            payload['stale_count'] = len(st)
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def tick_interval():
    """Push cadence = L1 tier (8s in trading, 120s off-hours)."""
    return _trading_tiers()['L1']


# ── connection / broadcast ─────────────────────────────────────────────────

class _SSEConn:
    """One live SSE client: queue drained by its handler thread."""

    def __init__(self):
        # Bounded queue: a slow client cannot make us buffer frames without
        # bound (L1 tick drops frames for a lagging client — next tick
        # overwrites). None sentinel wakes the handler to exit (not billed).
        self.q = queue.Queue(maxsize=8)
        self.closed = False


class _Frame:
    """One distinct broadcast frame shared by every connection of a group.

    `refs` = how many connection queues currently hold this frame. Billing is
    per distinct frame (BR-STR-5), guarded by _frame_bytes_lock (BR-STR-7).
    """

    __slots__ = ('payload', 'size', 'sid', 'refs')

    def __init__(self, payload, sid):
        self.payload = payload
        self.size = len(payload)
        self.sid = sid
        self.refs = 0


def _frame_acquire(f):
    """BR-STR-6/7 (P1-1): bill the frame *before* it is enqueued.

    Callers must hold no other lock.  refs 0→1 bills `f.size` once; a caller
    that ends up NOT enqueueing (both put_nowait attempts raise queue.Full)
    must roll back with `_frame_release(f)` so "not enqueued ⇒ not billed"
    still holds.  Because the frame only becomes reachable via put_nowait, a
    consumer that observes it always finds refs>=1, so its release can never
    short-circuit — no ghost frames (BR-STR-9 / §4.2).  The only divergence is
    the bounded, self-correcting one in-flight enqueue where refs leads the
    queue count by 1 until the put lands or is rolled back.
    """
    global _queue_bytes, _live_frames, _frame_peak_bytes
    with _frame_bytes_lock:
        f.refs += 1
        if f.refs == 1:
            _queue_bytes += f.size
            _group_bytes[f.sid] = _group_bytes.get(f.sid, 0) + f.size
            _live_frames += 1
            if f.size > _frame_peak_bytes:
                _frame_peak_bytes = f.size
        qb, live, peak = _queue_bytes, _live_frames, _frame_peak_bytes
    metrics.set_gauge('stream_queue_bytes', qb)        # publish outside the lock
    metrics.set_gauge('stream_frame_distinct', live)
    metrics.set_gauge('stream_frame_peak_bytes', peak)


def _frame_release(f):
    """BR-STR-6/7: inverse of acquire; idempotent (refs<=0 is a no-op)."""
    global _queue_bytes, _live_frames
    with _frame_bytes_lock:
        if f.refs <= 0:
            return
        f.refs -= 1
        if f.refs == 0:
            _queue_bytes -= f.size
            left = _group_bytes.get(f.sid, 0) - f.size
            if left > 0:
                _group_bytes[f.sid] = left
            else:
                _group_bytes.pop(f.sid, None)
            _live_frames -= 1
        qb, live = _queue_bytes, _live_frames
    metrics.set_gauge('stream_queue_bytes', qb)
    metrics.set_gauge('stream_frame_distinct', live)


def _pop_oldest_frame(conn):
    """BR-STR-10/12: take the queue head; consume None sentinels; never bill them."""
    while True:
        try:
            f = conn.q.get_nowait()
        except queue.Empty:
            return None
        if isinstance(f, _Frame):
            return f
        if f is None:
            return None            # sentinel consumed (conn must be closed)
        return None                # legacy non-_Frame fixture: not billed


def _drain_conn_queue(conn):
    """BR-STR-13: drain and release every frame; None sentinels are skipped.

    Returns the number of frames released. Idempotent (empty queue ⇒ 0)."""
    released = 0
    while True:
        try:
            f = conn.q.get_nowait()
        except queue.Empty:
            break
        if isinstance(f, _Frame):
            _frame_release(f)
            released += 1
    return released


def _reserve_for(incoming_len):
    """BR-STR-11/15: evict oldest frames until `incoming_len` fits the budget.

    Victim selection: the group with the most retained bytes → its fullest
    connection → its queue head. Groups with no droppable _Frame join this
    round's `skip` set (their byte ledger is NOT cleared — P2-6), which grows
    monotonically ⇒ the loop terminates. Returns the number of frames dropped.
    """
    dropped = 0
    skip = set()
    while True:
        with _frame_bytes_lock:
            if _queue_bytes + incoming_len <= STREAM_QUEUE_BYTES_BUDGET:
                return dropped
            sid = max((s for s in _group_bytes if s not in skip),
                      key=_group_bytes.get, default=None)
        if sid is None:
            return dropped                          # no droppable candidate
        g = get_group(sid)
        if g is None:
            skip.add(sid)                           # group gone; do not pop bytes
            continue
        with g.conns_lock:
            conns = sorted(g.conns, key=lambda c: c.q.qsize(), reverse=True)
        old = None
        for conn in conns:                          # fullest connection first
            old = _pop_oldest_frame(conn)
            if old is not None:
                break
        if old is None:
            skip.add(sid)                           # nothing droppable this round
            continue
        _frame_release(old)
        metrics.incr('stream_frame_dropped_total')
        dropped += 1


def _broadcast(snapshot):
    """BR-STR-2/9/10/11/13: frame build + enqueue outside all group locks."""
    now = time.time()
    with _groups_lock:
        groups = list(_groups.values())             # ① snapshot then release
    for g in groups:
        codes, fields = g.codes, g.fields           # ★ lock-free (frozenset/tuple)
        with g.conns_lock:
            conns = list(g.conns)                   # ② snapshot then release
        if not conns:
            # Zombie group: no live connections — skip frame build entirely.
            # last_push_ts not refreshed, so the idle sweeper reaps it.
            continue
        # ★ P2: a closed-but-not-yet-discarded connection is not a destination.
        # Reserving budget for a frame that will be enqueued to nobody evicted
        # other groups' real frames; filter first, then reserve.
        live = [c for c in conns if not c.closed]
        if not live:
            continue
        payload = _build_frame(snapshot, codes, fields)     # ★ outside locks
        if payload is None:
            continue
        frame = _Frame(payload, g.sid)
        _reserve_for(frame.size)                    # make room before enqueueing
        for conn in live:
            if conn.closed:
                continue
            # ★ BR-STR-9 (P1-1): bill BEFORE the frame becomes visible. A handler
            # blocked in q.get() is woken by put_nowait's notify and can consume
            # → _frame_release on another core; with the old put-then-acquire
            # order that release saw refs==0 and short-circuited (idempotent
            # no-op), so the following acquire stranded a ghost frame — permanent
            # _queue_bytes/_group_bytes/_live_frames drift. Acquiring first makes
            # refs>=1 hold before the frame is reachable, so the consumer's
            # release always decrements a frame that was actually billed.
            _frame_acquire(frame)
            try:
                conn.q.put_nowait(frame)
            except queue.Full:
                # Slow client: drop the OLDEST buffered frame so a recovered
                # client reads the NEWEST quote (AC-A2). None sentinels are
                # consumed but never billed.
                old = _pop_oldest_frame(conn)
                if isinstance(old, _Frame):
                    _frame_release(old)
                    metrics.incr('stream_frame_dropped_total')
                try:
                    conn.q.put_nowait(frame)
                except queue.Full:
                    _frame_release(frame)   # ★ never enqueued ⇒ un-bill
                    continue
            if conn.closed:             # ★ BR-STR-13: put/closed race收口
                _drain_conn_queue(conn)
        g.last_push_ts = now


_GROUP_IDLE_TTL = config.STREAM_GROUP_IDLE_TTL  # idle zombie group reaper
_last_group_sweep = 0.0


def _sweep_idle_groups(now=None):
    """Reclaim zombie groups (no connections, idle > TTL). Cheap O(len) pass."""
    now = time.time() if now is None else now
    with _groups_lock:
        idle = [sid for sid, g in _groups.items()
                if not g.conns
                and now - max(g.last_push_ts, g.created_ts) > _GROUP_IDLE_TTL]
    for sid in idle:
        try:
            # Re-check emptiness INSIDE the lock, before destroying: a client
            # may have reconnected between collection and destruction
            # (TOCTOU). conns is read under _groups_lock (RLock) then closed
            # under conns_lock — lock order groups→conns, no cycle.
            with _groups_lock:
                g = _groups.get(sid)
                if g is None:
                    continue
                with g.conns_lock:
                    if g.conns:
                        continue  # client reconnected — keep the group
                _groups.pop(sid, None)
            log.info(f'[stream] group {sid} swept (idle > {_GROUP_IDLE_TTL:.0f}s, no conns)')
        except Exception as e:
            log.warning(f'[stream] sweep {sid} failed: {e}')


def _tick_sleep_seconds(t0, tick, now):
    """BR-STR-27 cadence baseline + BUG-P6C-06 integer-tick grid alignment.

    The interval baseline stays this round's start (`t0`), so a slow refresh
    cannot silently slip the cadence.  The sleep is always to the *next* grid
    point ``t0 + k×tick`` strictly after `now`, with
    ``k = floor((now − t0) / tick) + 1`` (≥ 1):
    a round that fits the budget sleeps to ``t0 + tick``; a round that overruns
    slips whole ticks and starts on the next grid point.

    The old rule floored the delay at ``0.25 × tick`` once the round overran
    the budget.  A round longer than one whole tick then produced a frame 2 s
    after the previous one — the "2 s back-to-back duplicate frame" — preceded
    by a 12–17 s stall: a two-peak inter-frame histogram.  On the grid the
    interval is never shorter than one tick, so no short burst can be emitted.
    """
    elapsed = now - t0
    k = int(elapsed // tick) + 1                     # next grid point after now
    if k < 1:                                        # clock skew guard
        k = 1
    return max(t0 + k * tick - now, 0.0)


def _push_once(t0=None):
    """One scheduled iteration of `push_loop`; returns that round's sleep delay.

    Extracted (BUG-P6C-08) so a test can drive **the real scheduled path** —
    the `if codes:` guard and its empty-pool branch included — without an
    unbounded loop.

    The empty-pool reset of `stream_refresh_lag_ticks` lives HERE, not in
    `_refresh_pool`: the latter is unreachable once the pool is empty (the
    guard below), so the gauge used to strand at its last C2 value forever
    after the final subscription went away (tester r4 §5, 150s/≥2 ticks at 2).
    """
    global _last_group_sweep
    t0 = time.time() if t0 is None else t0
    tick = tick_interval()
    now = time.time()
    if now - _last_group_sweep >= 60:
        _sweep_idle_groups(now)
        _last_group_sweep = now
    # ★ BUG-P6C-06: codes + fields read together (one lock acquisition)
    # so the refresh set can never disagree with the live subscription.
    codes, fields = _active_targets()
    if codes:
        snapshot = _refresh_pool(codes, now, fields, tick=tick)   # ★ P1-6
        snapshot, stale = _carry_forward(snapshot, codes, fields)  # ★ P1-4
        if stale:
            snapshot['_stale'] = stale          # frame metadata only (reserved)
        _broadcast(snapshot)
    else:
        # No live demand ⇒ no backlog.  The ONLY production path that can
        # reset the gauge after the pool empties (BUG-P6C-08).
        metrics.set_gauge('stream_refresh_lag_ticks', 0)
        _clear_last_known()                     # nothing to carry forward
    duration = time.time() - t0
    metrics.set_gauge('stream_tick_duration_ms', round(duration * 1000, 2))
    # Empty rounds cost ~0ms, so neither counter grows on this branch: degraded
    # and slip are strictly a property of a refresh that ran and overran.
    if duration > _TICK_BUDGET_FRACTION * tick:
        metrics.incr('stream_tick_degraded_total')
    if duration >= tick:
        metrics.incr('stream_tick_slip_total')
    return _tick_sleep_seconds(t0, tick, time.time())    # ★ BR-STR-27


def push_loop():
    """Background thread: refresh the active pool every L1 tick, then fan out.

    BR-STR-25..27: the tick budget baseline is this round's start time, so a
    slow refresh cannot eat into the next interval (no silent slip).  The
    iteration body is `_push_once` (kept separate so the empty-pool lag reset
    is reachable from a test — BUG-P6C-08).

    P2: a failing round stays on the tick grid with exponential backoff
    (1, 2, 4, … ticks, capped) instead of the old fixed ``sleep(1)``.  A fault
    that repeats used to degrade the loop into a ~1 s spin — up to ~tick×
    rounds per interval, multiplying upstream pressure exactly when it is worst.
    """
    consecutive = 0
    while True:
        t0 = time.time()
        tick = tick_interval()
        try:
            delay = _push_once(t0)
            consecutive = 0
        except Exception as e:
            consecutive += 1
            log.error(f'[stream] push_loop error (x{consecutive}): {e}')
            spans = min(2 ** (consecutive - 1), _PUSH_ERROR_BACKOFF_CAP_TICKS)
            # Back off on the tick grid: the exponential span when it fits,
            # otherwise the next grid point — never a ~1 s spin (and never a
            # busy loop when the failing round itself overran the span).
            backoff = spans * tick - (time.time() - t0)
            delay = max(backoff, _tick_sleep_seconds(t0, tick, time.time()))
        if delay > 0:
            time.sleep(delay)


# ── group CRUD (used by HTTP handlers and tests) ───────────────────────────

def create_group(codes, fields):
    """Validate and create a subscription group. Returns (sid, error).

    S2-4: an explicitly requested unknown field is a 400 (``_valid_fields``
    raises) — it is never silently widened to the all-field default.

    P1-6/S2-4b: codes are folded through the single authority
    (``config.canonical_code``) and deduped *after* folding, so ``600519.SH``,
    ``SH600519`` and ``sh600519`` are one subscription entry.  An invalid code
    (``canonical_code`` → ``None``) is a 400 ``invalid stock code`` — the code
    never reaches the pool, and a local regex is never the gate.
    """
    if not codes:
        return None, 'codes required'
    if len(codes) > MAX_CODES_PER_SUB:
        return None, f'too many codes (max {MAX_CODES_PER_SUB})'
    try:
        g_fields = tuple(_valid_fields(fields))
    except (ValueError, TypeError) as exc:
        return None, str(exc)
    seen = set()
    clean = []
    for c in codes:                                     # ★ P1-6 canonicalisation
        # `config.canonical_code` is the single authority (S2-4b / P1-6): it is
        # the only place that folds the dotted (`600519.SH`) and prefixed
        # (`SH600519`) spellings onto the one lowercase prefixed form the rest
        # of the system keys on.  A local regex here would let `600519.SH` in
        # as a *third* identity next to `sh600519` — two pool/cache/ledger keys
        # (and two upstream fetches) for one stock.
        code = config.canonical_code(c)
        if code is None:                                # invalid ⇒ 400 (§2.2)
            return None, f'invalid stock code: {c}'
        if code not in seen:                            # dedupe, post-fold
            seen.add(code)
            clean.append(code)
    with _groups_lock:
        if len(_groups) >= MAX_GROUPS:                  # ★ BR-STR-29
            return None, f'too many groups (max {MAX_GROUPS})'
        total = len(_deduped_codes_unlocked()) + len(clean)
        if total > MAX_DEDUP_CODES:
            return None, f'pool would exceed {MAX_DEDUP_CODES} codes'
        # ★ P1-4/S2-2: keep the cross-group distinct-frame working set *plus one
        # full frame* inside the queue byte budget.  Without the single-frame
        # margin a legal set whose working set exactly fills the budget (9 full
        # groups) forced every `_broadcast` to evict a real frame per group per
        # tick (AC-E5).
        incoming = stream_frame_bytes(len(clean), len(g_fields))
        projected = _projected_frame_bytes_unlocked() + incoming
        largest = max(_max_group_frame_bytes_unlocked(), incoming)
        if projected + largest > STREAM_QUEUE_BYTES_BUDGET:
            return None, _FRAME_BUDGET_ERR
        sid = _new_sid()
        group = SubscriptionGroup(sid, clean, g_fields)     # ★ local (no KeyError)
        _groups[sid] = group
    log.info(f'[stream] group {sid} created: {len(clean)} codes, '
             f'fields={group.fields}')
    return sid, None


def get_group(sid):
    with _groups_lock:
        return _groups.get(sid)


def patch_group(sid, add, remove):
    """Add/remove codes on a group. Returns (ok, error).

    P1-6/S2-4b: codes are canonicalised via ``config.canonical_code``
    (``600519.SH`` / ``SH600519`` → ``sh600519``), so an add/remove in any
    accepted spelling hits the same entry the group already stores.
    S2-4d: the group is read under the *same* ``_groups_lock`` that performs the
    mutation, so a concurrent ``destroy_group`` can no longer make this a
    false-success mutation on a detached object (the old unlocked `get_group`
    read plus late lock acquisition had that window).
    """
    add = add or []
    remove = remove or []
    norm_add, norm_remove = [], []
    for c in add:                                       # ★ P1-6 (see create_group)
        code = config.canonical_code(c)
        if code is None:
            return False, f'invalid stock code: {c}'
        norm_add.append(code)
    for c in remove:
        code = config.canonical_code(c)
        if code is None:
            return False, f'invalid stock code: {c}'
        norm_remove.append(code)
    with _groups_lock:
        g = _groups.get(sid)                        # ★ S2-4d: read under the lock
        if g is None:
            return False, 'subscription not found'
        others = _deduped_codes_unlocked() - g.codes
        projected = len(others | (g.codes | set(norm_add)) - set(norm_remove))
        if projected > MAX_DEDUP_CODES:
            return False, f'pool would exceed {MAX_DEDUP_CODES} codes'
        if len(g.codes) + len(norm_add) - len(set(norm_remove)) > MAX_CODES_PER_SUB:
            return False, f'too many codes (max {MAX_CODES_PER_SUB})'
        new_codes = (g.codes | frozenset(norm_add)) - frozenset(norm_remove)
        # ★ P1-4/S2-2: same cross-group frame-budget cap + single-frame margin.
        old_f = stream_frame_bytes(len(g.codes), len(g.fields))
        new_f = stream_frame_bytes(len(new_codes), len(g.fields))
        projected_bytes = _projected_frame_bytes_unlocked() - old_f + new_f
        largest = max(_max_group_frame_bytes_unlocked(exclude_sid=sid), new_f)
        if projected_bytes + largest > STREAM_QUEUE_BYTES_BUDGET:
            return False, _FRAME_BUDGET_ERR
        g.codes = new_codes                                       # ★ BR-STR-1
    log.info(f'[stream] group {sid} patched: +{len(norm_add)} '
             f'-{len(norm_remove)} => {len(g.codes)} codes')
    return True, None


def destroy_group(sid):
    with _groups_lock:
        g = _groups.pop(sid, None)
    if g is None:
        return False
    with g.conns_lock:
        conns = list(g.conns)
        for conn in conns:
            conn.closed = True
            try:
                conn.q.put_nowait(None)  # wake handler to exit (not billed)
            except queue.Full:
                # accepted: full queue drops the sentinel, handler still exits
                # via get timeout + closed flag (worst case <= ~60s, bounded)
                pass
        g.conns.clear()
    for conn in conns:                       # ★ BR-STR-13: drain outside the lock
        _drain_conn_queue(conn)
    log.info(f'[stream] group {sid} destroyed')
    return True


def _register_conn(conn):
    global _conn_count
    with _conn_count_lock:
        if _conn_count >= MAX_STREAM_CONNS:
            return False
        _conn_count += 1
    return True


def _release_conn(conn=None):
    """BR-STR-13/30: single teardown point — drain first, then decrement (idempotent)."""
    global _conn_count
    if conn is not None:
        _drain_conn_queue(conn)
    with _conn_count_lock:
        if _conn_count > 0:
            _conn_count -= 1


# ── HTTP layer ─────────────────────────────────────────────────────────────

def _require_code_list(value):
    """``(ok, list)`` — ``codes``/``add``/``remove`` must be JSON arrays.

    P1-2: a non-container body value (``{"codes":123}``, ``{"add":true}``) used
    to reach ``len()``/``for`` inside create_group/patch_group and raise a
    ``TypeError`` *outside* their try, bubbling out of the handler and resetting
    the client connection instead of the contract's 400.  ``None``/absent maps
    to ``[]`` (the handlers keep their own "required" semantics).
    """
    if value is None:
        return True, []
    if isinstance(value, list):
        return True, value
    return False, None


def _capacity_meta(codes, fields):
    """Per-tick refresh capacity for a subscription's field set (P1-4).

    Surfaces the C2 coverage limit in the create/patch response so a client can
    size its watchlist instead of discovering a >95%-null frame later.  Keys are
    additive — the existing ``sid``/``codes``/``fields`` contract is unchanged.
    """
    _, coverage_codes = refresh_capacity(tick_interval(), fields)
    n = len(codes)
    if n <= coverage_codes:
        return {'refresh_capacity_codes': coverage_codes}
    lag = -(-n // coverage_codes)
    return {
        'refresh_capacity_codes': coverage_codes,
        'refresh_lag_ticks': lag,
        'capacity_warning': (
            f'subscription has {n} codes but only {coverage_codes} refresh per '
            f'tick; frames are sharded and each code lags ~{lag} ticks'),
    }


class StreamHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'ChinaFinanceRSS/stream'
    timeout = 30  # socket timeout: a stalled client can't hold a pool thread
                  # on rfile.read / wfile.write of a management request.
                  # _serve_sse re-sets its own longer timeout below.

    def log_message(self, fmt, *args):
        log.info('[stream] %s - %s' % (self.address_string(), fmt % args))

    def log_error(self, fmt, *args):
        # P1-3: a torn-down connection can still emit one "Request timed out"
        # from the base handler — expected churn, not an operational error, so
        # suppress the noise (RSSHandler parity).
        if fmt == 'Request timed out: %r':
            return
        self.log_message(fmt, *args)

    # -- management endpoints (short-lived) --

    def _read_json_body(self):
        """BR-STR-32: read budget = MGMT_BODY_TIMEOUT; invalid CL ⇒ do not read."""
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except (ValueError, TypeError):
            return None
        if length < 0 or length > 65536:
            return None                            # do not touch the socket
        conn = getattr(self, 'connection', None)
        prev = None
        if conn is not None:
            try:
                prev = conn.gettimeout()
                conn.settimeout(MGMT_BODY_TIMEOUT)  # ★ 5s read budget
            except OSError:
                conn = None
        try:
            body = self.rfile.read(length) if length else b''
        except (socket.timeout, TimeoutError, OSError):
            return None                            # slow client: release ≤5s
        finally:
            if conn is not None:
                try:
                    conn.settimeout(prev if prev is not None else self.timeout)
                except OSError:
                    pass
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
        if not isinstance(body, dict):
            self._send_json(400, {'error': 'JSON body must be an object'})
            return
        ok, codes = _require_code_list(body.get('codes'))
        if not ok:
            self._send_json(400, {'error': 'codes must be a list'})
            return
        sid, err = create_group(codes, body.get('fields'))
        if err:
            self._send_json(400, {'error': err})
            return
        g = get_group(sid)
        resp = {'sid': sid, 'codes': sorted(g.codes), 'fields': list(g.fields)}
        resp.update(_capacity_meta(g.codes, g.fields))     # ★ P1-4
        self._send_json(201, resp)

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
        if not isinstance(body, dict):
            self._send_json(400, {'error': 'JSON body must be an object'})
            return
        ok, add = _require_code_list(body.get('add'))
        if not ok:
            self._send_json(400, {'error': 'add must be a list'})
            return
        ok, remove = _require_code_list(body.get('remove'))
        if not ok:
            self._send_json(400, {'error': 'remove must be a list'})
            return
        ok, err = patch_group(sid, add, remove)
        if not ok:
            self._send_json(404 if err == 'subscription not found' else 400,
                            {'error': err})
            return
        g = get_group(sid)
        if g is None:                               # P2: destroy raced the patch
            self._send_json(404, {'error': 'subscription not found'})
            return
        resp = {'sid': sid, 'codes': sorted(g.codes)}
        resp.update(_capacity_meta(g.codes, g.fields))     # ★ P1-4
        self._send_json(200, resp)

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
        if not _register_conn(conn):                 # BR-STR-30 → 503
            metrics.incr('http_503_total')           # P2: 503 total across paths
            self._send_json(503, {'error': 'too many stream connections'})
            return
        with g.conns_lock:
            g.conns.add(conn)
        with _groups_lock:                           # ★ P2-7: destroy vs register
            alive = _groups.get(sid) is g
        if not alive:
            conn.closed = True
            with g.conns_lock:
                g.conns.discard(conn)
            _release_conn(conn)                      # drain (empty) + decrement
            self._send_json(404, {'error': 'subscription not found'})
            return
        stalled = False
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            # P1-3: the stream closes the connection when it ends (`finally`
            # below), so advertise that instead of a keep-alive the socket will
            # not honour.
            self.send_header('Connection', 'close')
            self.end_headers()
            # Socket-level timeout so a stalled client (full TCP window)
            # can't hold the handler thread indefinitely on wfile.write;
            # OSError is caught below alongside the disconnect cases.
            self.connection.settimeout(STREAM_PING_INTERVAL * 2)   # BR-STR-31
            while not conn.closed:
                try:
                    f = conn.q.get(timeout=STREAM_PING_INTERVAL)
                except queue.Empty:
                    self.wfile.write(b'event: ping\ndata: {}\n\n')
                    self.wfile.flush()
                    continue
                if f is None:
                    break                            # wake sentinel (not billed)
                frame = f.payload if isinstance(f, _Frame) else f
                try:
                    self.wfile.write(
                        b'event: quote\nid: '
                        + str(int(time.time() * 1000)).encode()
                        + b'\ndata: ' + frame.encode('utf-8') + b'\n\n')
                    self.wfile.flush()
                finally:
                    if isinstance(f, _Frame):
                        _frame_release(f)            # BR-STR-14: release on consume
        except (BrokenPipeError, ConnectionResetError, OSError):
            stalled = True                           # write path failed / timed out
        finally:
            conn.closed = True
            with g.conns_lock:
                g.conns.discard(conn)
            if stalled and not conn.q.full():        # BR-STR-35
                metrics.incr('stream_slow_client_total')
            _release_conn(conn)                      # ★ BR-STR-13: drain + decrement
            # ★ P1-3: without this flag `handle()` would re-enter
            # `handle_one_request` and block on `rfile.readline()` for up to the
            # 40 s socket timeout, pinning the pool worker AND the `_inflight`
            # slot for a client that already left (starving management requests
            # under reconnect churn).  A finished stream has no further purpose.
            self.close_connection = True


def make_stream_server(max_workers=None):
    """Build the stream HTTP server (BoundedThreadPoolServer for load shed).

    BR-STR-30 / P1-4: the inflight cap is explicit — MAX_STREAM_CONNS +
    _MGMT_WORKER_RESERVE so the 100-connection register threshold is not masked
    by the main-port default (MAX_INFLIGHT=40).

    P2 (pool split, evaluated): SSE and management share this one pool.  A
    dedicated management pool needs request-type dispatch before the handler
    runs, and the server cannot tell an SSE GET from a management GET until the
    request line is parsed — so the cheap equivalent is used instead: SSE
    registration is capped at MAX_STREAM_CONNS and the pool keeps
    `_MGMT_WORKER_RESERVE` workers above it, leaving management a worker even at
    a full SSE set.  The P1-3 `close_connection` fix reclaims the 40 s
    dead-connection hold that used to consume that reserve.
    """
    from .server import BoundedThreadPoolServer
    max_workers = max_workers or (MAX_STREAM_CONNS + _MGMT_WORKER_RESERVE)
    return BoundedThreadPoolServer((config.STREAM_HOST, STREAM_PORT), StreamHandler,
                                   max_workers=max_workers,
                                   max_inflight=MAX_STREAM_CONNS + _MGMT_WORKER_RESERVE)


def run_stream_server():
    """Entry point for the stream server daemon thread."""
    srv = make_stream_server()
    log.info(f'[stream] SSE server on http://localhost:{STREAM_PORT}')
    log.info(f'[stream] limits: conns<={MAX_STREAM_CONNS} '
             f'codes/sub<={MAX_CODES_PER_SUB} dedup<={MAX_DEDUP_CODES}')
    srv.serve_forever()
