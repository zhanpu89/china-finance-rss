"""Zero-dependency in-process metrics registry (leaf module).

Per ``doc/detailed/metrics.md`` v1.1: counters/gauges are registered and
snapshotted centrally so ``/healthz`` can expose a ``metrics`` field.  It is a
Layer-0 leaf: it imports no ``china_finance_rss`` module, holds no background
thread and never blocks business code (fail-safe: warning + ignore, never raise).
"""

import logging
import threading

log = logging.getLogger('metrics')

_counters = {}
_gauges = {}
_lock = threading.Lock()      # leaf lock: never held while calling other modules
_warned = set()               # warning de-dup; intentionally lock-free (tolerated race)

# Frozen name registry (§3.2). Used for warning only — writes are never blocked.
_KNOWN = frozenset({
    'http_503_total', 'stream_frame_dropped_total', 'stream_queue_bytes',
    'stream_frame_distinct', 'stream_frame_peak_bytes', 'stream_tick_duration_ms',
    'stream_tick_slip_total', 'stream_refresh_lag_ticks', 'stream_tick_degraded_total',
    'stream_slow_client_total', 'cache_entries', 'cache_hit_ratio',
    'negative_cache_size', 'upstream_fail_total', 'upstream_fetch_total',
    'code_cooldown_list', 'cdp_restart_window', 'healthz_stale_total', 'healthz_inflight',
})

# Zero/empty value for every registered name (BUG-P6C-04).  ``snapshot()``
# always publishes these names so monitoring can tell "never happened" from
# "never instrumented".  This table is read-only fallback metadata: it is
# never written into ``_counters``/``_gauges``, so a metric's first ``incr``
# still fixes its shape (int vs labelled dict) per BR-MET-1.
_DEFAULTS = {
    'http_503_total': 0,
    'stream_frame_dropped_total': 0,
    'stream_queue_bytes': 0,
    'stream_frame_distinct': 0,
    'stream_frame_peak_bytes': 0,
    'stream_tick_duration_ms': 0,
    'stream_tick_slip_total': 0,
    'stream_refresh_lag_ticks': 0,
    'stream_tick_degraded_total': 0,
    'stream_slow_client_total': 0,
    'cache_entries': {},
    'cache_hit_ratio': 0.0,
    'negative_cache_size': 0,
    'upstream_fail_total': {},
    'upstream_fetch_total': {},
    'code_cooldown_list': [],
    'cdp_restart_window': {},
    'healthz_stale_total': 0,
    'healthz_inflight': 0,
}
assert set(_DEFAULTS) == _KNOWN      # every frozen name has a declared zero

# Gauges whose value is a label->number mapping (written with ``key=``).  Unlike
# counters — where any dict shape means "labelled" — a *gauge* may legitimately
# hold a dict as its value (``cdp_restart_window``), so the labelled/unlabelled
# shape guard needs this explicit registry instead of a runtime type test (P2-13).
_LABELED_GAUGES = frozenset({'cache_entries'})
assert _LABELED_GAUGES <= _KNOWN


def _warn_once(msg):
    if msg not in _warned:
        _warned.add(msg)
        log.warning('[metrics] %s', msg)


def incr(name, n=1, key=None):
    """Increment a counter; ``key`` non-None selects a labelled counter."""
    if not isinstance(name, str):
        _warn_once(f'non-str metric name {name!r} ignored')
        return
    if not isinstance(n, int) or isinstance(n, bool):
        _warn_once(f'non-int increment {n!r} for {name} ignored')
        return
    if name not in _KNOWN:
        _warn_once(f'unregistered metric name {name!r}')
    with _lock:
        if key is None:
            cur = _counters.get(name)
            if isinstance(cur, dict):
                _warn_once(f'counter {name}: unlabeled/labeled mismatch')
                return
            _counters[name] = (cur or 0) + n
        else:
            cur = _counters.get(name)
            if cur is None:
                _counters[name] = {key: n}
            elif isinstance(cur, dict):
                cur[key] = cur.get(key, 0) + n
            else:
                _warn_once(f'counter {name}: labeled/unlabeled mismatch')
                return


def set_gauge(name, value, key=None):
    """Set a gauge; ``key`` non-None writes one label of a labelled gauge.

    Shape guards mirror :func:`incr` (P2-13): a labelled gauge
    (:data:`_LABELED_GAUGES`) can never be overwritten wholesale by an
    unlabelled write, and an unlabelled gauge can never silently sprout a label
    dict.  Both mismatches warn once and are ignored — observation must never
    break, or corrupt, business state.
    """
    if not isinstance(name, str):
        _warn_once(f'non-str metric name {name!r} ignored')
        return
    if name not in _KNOWN:
        _warn_once(f'unregistered metric name {name!r}')
    with _lock:
        cur = _gauges.get(name)
        if key is None:
            if name in _LABELED_GAUGES and isinstance(cur, dict):
                _warn_once(f'gauge {name}: unlabeled/labeled mismatch')
                return
            _gauges[name] = value
        else:
            if name not in _LABELED_GAUGES:
                _warn_once(f'gauge {name}: labeled write to an unlabelled gauge')
                return
            if cur is None:
                _gauges[name] = {key: value}
            elif isinstance(cur, dict):
                cur[key] = value
            else:
                _warn_once(f'gauge {name}: labeled/unlabeled mismatch')
                return


def _clone(v):
    """Deep-copy a JSON-ish value without the (non-allowlisted) ``copy`` module."""
    if isinstance(v, dict):
        return {str(k): _clone(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clone(x) for x in v]
    if isinstance(v, tuple):
        return [_clone(x) for x in v]
    if isinstance(v, set):
        return [_clone(x) for x in v]
    return v


def snapshot():
    """Return a deep-copied ``{name: value}`` merge of counters and gauges.

    Every registered name is present even before its first write (BUG-P6C-04):
    names absent from ``_counters``/``_gauges`` fall back to
    ``_DEFAULTS``, so e.g. ``stream_frame_dropped_total`` reads 0 rather than
    going missing.  Written values always win.

    ``_lock`` is held only for a *shallow* copy of the registry (S1-4): the
    expensive deep clone of large list/dict values runs outside the critical
    section, so a ``/healthz`` poll can never block a business write for the
    duration of a full clone.  Every mutable container is shallow-copied while
    the lock is held (P2-12): dicts via ``.copy()`` *and* lists via ``list(v)``,
    so a list gauge mutated in place cannot make the out-of-lock clone iterate
    a live object (``list changed size during iteration`` / torn values).
    """
    with _lock:
        items = [(k, list(v) if isinstance(v, list)
                  else v.copy() if isinstance(v, dict) else v)
                 for k, v in _counters.items()]
        items += [(k, list(v) if isinstance(v, list)
                   else v.copy() if isinstance(v, dict) else v)
                  for k, v in _gauges.items()]
    out = {k: _clone(v) for k, v in items}
    for name, default in _DEFAULTS.items():
        if name not in out:
            out[name] = _clone(default)
    return out


def reset():
    """Clear all counters and gauges (test isolation only).

    Internal state is emptied; ``snapshot()`` still publishes every registered
    name at its zero value (BUG-P6C-04).
    """
    with _lock:
        _counters.clear()
        _gauges.clear()
    _warned.clear()
