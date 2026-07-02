#!/usr/bin/env python3
"""Monitor CDP data freshness over time.

Polls /finance/market and /quotation/market every 5s, tracks per-field
timestamps, and reports which data is actually being refreshed.

Usage:
    python freshness_test.py [--duration SECONDS]
"""

import sys
import json
import time
from urllib.request import Request, urlopen

BASE = 'http://localhost:8053'
POLL_INTERVAL = 5
DEFAULT_DURATION = 300  # 5 minutes


def fetch_json(path):
    req = Request(BASE + path)
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def flatten(d, prefix=''):
    """Flatten nested dict into dot-separated keys."""
    items = {}
    for k, v in d.items():
        key = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            items.update(flatten(v, key))
        else:
            items[key] = v
    return items


def main():
    duration = DEFAULT_DURATION
    if '--duration' in sys.argv:
        idx = sys.argv.index('--duration')
        duration = int(sys.argv[idx + 1])

    endpoints = ['/finance/market', '/quotation/market']
    # name -> { field -> last_value, last_seen, changes }
    history = {ep: {} for ep in endpoints}
    end_time = time.time() + duration

    print(f"Monitoring {len(endpoints)} endpoints every {POLL_INTERVAL}s for {duration}s")
    print(f"{'Time':>20} | {'Endpoint':>18} | {'Changed':>7} | {'Fields':>30}")
    print('-' * 80)

    while time.time() < end_time:
        t0 = time.perf_counter()
        cycle_ts = time.time()

        for ep in endpoints:
            try:
                data = fetch_json(ep)
            except Exception as e:
                print(f"{time.strftime('%H:%M:%S', time.localtime()):>20} | {ep:>18} | {'ERR':>7} | {e}")
                continue

            fields = flatten(data)
            changed = 0
            new_set = 0
            prev = history[ep]

            for key, val in fields.items():
                prev_val, prev_ts = prev.get(key, (None, 0))
                if prev_val is None:
                    new_set += 1
                elif val != prev_val:
                    changed += 1
                prev[key] = (val, cycle_ts)

            # Log summary
            ts = time.strftime('%H:%M:%S', time.localtime())
            extra = ', '.join(
                f'{k}={v}'
                for k, v in sorted(fields.items())
                if not isinstance(v, (dict, list)) and k in ('error', 'ws_count')
            )
            print(f"{ts:>20} | {ep:>18} | {changed:>4}+{new_set:>2} | {extra}")

            # If WS data is present, show its count and age
            ws_count = data.get('ws_count')
            ws_latest = data.get('ws_latest', [])
            if ws_count is not None:
                ws_ts = time.strftime('%H:%M:%S', time.localtime())
                print(f"{'':>20} | {'':>18} | {'':>7} | ws_count={ws_count}, ws_latest={len(ws_latest)} items")

        elapsed = time.perf_counter() - t0
        sleep = max(0, POLL_INTERVAL - elapsed)
        if sleep:
            time.sleep(sleep)

    # Final summary
    print(f"\n{'='*60}")
    print("FINAL FRESHNESS REPORT")
    print(f"{'='*60}")

    now = time.time()
    for ep in endpoints:
        fields = history[ep]
        if not fields:
            print(f"\n{ep}: NO DATA")
            continue

        # Group by staleness
        stale = []
        fresh = []
        for key, (val, last_ts) in sorted(fields.items()):
            age = now - last_ts
            if age > 60:
                stale.append((key, age, val))
            else:
                fresh.append(key)

        total = len(fields)
        if not stale:
            print(f"\n{ep}: ALL {total} fields fresh (<60s since last change)")
        else:
            print(f"\n{ep}: {len(stale)}/{total} fields stale (>60s)")
            for key, age, val in stale:
                print(f"  STALE {age:5.0f}s  {key} = {repr(val)[:60]}")

    print(f"\nDuration: {duration}s at {POLL_INTERVAL}s interval")
    print("Done.")


if __name__ == '__main__':
    main()
