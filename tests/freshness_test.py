#!/usr/bin/env python3
"""Monitor CDP data freshness over time.

Polls /finance/market and /quotation/market every 5s. Renders two
metrics per field:

  last_fetch  — last time the server returned a value (any value)
  last_change — last time the value actually changed

This distinguishes "server not fetching" from "market data is stable".

Usage:
    python tests/freshness_test.py [--duration SECONDS]
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
    # { field: { last_fetch, last_change, value } }
    fields = {}
    end_time = time.time() + duration

    print(f"Polling {len(endpoints)} endpoints every {POLL_INTERVAL}s for {duration}s")
    print(f"{'Time':>20} | {'Endpoint':>18} | {'Fetch':>5} | {'Changed':>7}")
    print('-' * 70)

    import math
    cycle_results = {ep: [] for ep in endpoints}

    while time.time() < end_time:
        t0 = time.perf_counter()
        now = time.time()

        for ep in endpoints:
            try:
                data = fetch_json(ep)
            except Exception as e:
                print(f"{time.strftime('%H:%M:%S', time.localtime()):>20} | {ep:>18} | {'ERR':>5} | {e}")
                continue

            flat = flatten(data)
            fetch_ok = True
            changed_count = 0

            for key, val in flat.items():
                rec = fields.get(key)
                if rec is None:
                    fields[key] = {'last_fetch': now, 'last_change': now, 'value': val, 'ep': ep}
                    changed_count += 1
                else:
                    rec['last_fetch'] = now
                    if val != rec['value']:
                        rec['last_change'] = now
                        rec['value'] = val
                        changed_count += 1

            ws_count = data.get('ws_count')
            ws_parts = f' ws={ws_count}' if ws_count is not None else ''
            ts = time.strftime('%H:%M:%S', time.localtime())
            print(f"{ts:>20} | {ep:>18} | {'OK':>5} | {changed_count:>4}{ws_parts}")

        elapsed = time.perf_counter() - t0
        sleep = max(0, POLL_INTERVAL - elapsed)
        if sleep:
            time.sleep(sleep)

    # ── Final report ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("FIELD FRESHNESS REPORT")
    print(f"{'='*70}")

    now = time.time()
    by_ep = {}
    for key, rec in fields.items():
        by_ep.setdefault(rec['ep'], []).append((key, rec))

    for ep in sorted(by_ep):
        entries = by_ep[ep]
        print(f"\n  [{ep}]  {len(entries)} fields tracked\n")
        print(f"  {'Field':>40} | {'LastFetch':>10} | {'LastChange':>10} | "
              f"{'FetchAge':>8} | {'StableSince':>8}")
        print('  ' + '-' * 85)

        warn_fetch = []
        warn_stable = []
        ok = []

        for key, rec in sorted(entries):
            fetch_age = now - rec['last_fetch']
            change_age = now - rec['last_change']
            fc = time.strftime('%H:%M:%S', time.localtime(rec['last_fetch']))
            cc = time.strftime('%H:%M:%S', time.localtime(rec['last_change']))
            val_str = repr(rec['value'])[:40]

            if fetch_age > 120:
                warn_fetch.append((fetch_age, change_age, key, val_str))
            elif change_age > 120:
                warn_stable.append((fetch_age, change_age, key, val_str))
            else:
                ok.append((fetch_age, change_age, key, val_str))

            print(f"  {key:>40} | {fc:>10} | {cc:>10} | "
                  f"{fetch_age:>7.0f}s | {change_age:>7.0f}s")

        # Summary counts
        print(f"\n  Fresh (fetch≤120s): {len(ok)} fields")
        for fa, ca, key, vs in ok:
            vs = repr(fields[key]['value'])[:40]
            print(f"    {key:<42} last_change={ca:.0f}s ago  val={vs}")

        print(f"\n  Stable (fetch OK, value unchanged >120s): {len(warn_stable)} fields")
        for fa, ca, key, vs in warn_stable:
            print(f"    {key:<42} last_fetch={fa:.0f}s  last_change={ca:.0f}s  val={vs}")

        print(f"\n  WARNING — fetch interval >120s: {len(warn_fetch)} fields")
        for fa, ca, key, vs in warn_fetch:
            print(f"    {key:<42} last_fetch={fa:.0f}s  last_change={ca:.0f}s  val={vs}")

    print(f"\nDuration: {duration}s at {POLL_INTERVAL}s interval")
    print("Done.")


if __name__ == '__main__':
    main()
