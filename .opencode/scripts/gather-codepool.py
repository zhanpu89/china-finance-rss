#!/usr/bin/env python3
"""Gather a realistic stock-code pool (>= 1000 codes) for tier stress tests.

Feeds: CLS hotplate board list -> per-board /cls/plate constituents.  The
service's own endpoints are the only source (no direct upstream access), so
this also warms the plate cache a little on the way.

Usage:
    python3 .opencode/scripts/gather-codepool.py [--url http://127.0.0.1:8053] [--out /tmp/opencode/codepool.json]

Stdlib only.  Boards are fetched serially with a small delay; a failing board
is skipped, not fatal.
"""
import argparse
import json
import re
import time
import urllib.request
import urllib.error

_BOARD_CODE = re.compile(r'^cls\d+$')
_CODE = re.compile(r'^(sh|sz|bj)\d{6}$')
_MAX_BOARDS = 45
_MAX_RETRY = 2
_DELAY = 0.15


def _get_json(url, timeout=20):
    last = None
    for _ in range(_MAX_RETRY):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            last = e
            time.sleep(0.3)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8053')
    ap.add_argument('--out', default='/tmp/opencode/codepool.json')
    args = ap.parse_args()

    hot = _get_json(f'{args.url}/cls/hotplate')
    boards = []
    for key in ('plate_industry', 'plate_concept', 'plate_area'):
        sec = hot.get(key) or {}
        plate_data = sec.get('plate_data') or sec.get('data') or []
        for item in plate_data:
            code = (item or {}).get('secu_code') or (item or {}).get('code')
            if code and _BOARD_CODE.match(str(code)):
                boards.append(str(code))
    boards = sorted(set(boards))[:_MAX_BOARDS]
    print(f'boards: {len(boards)}')

    pool = []
    seen = set()
    ok = 0
    for code in boards:
        try:
            data = _get_json(f'{args.url}/cls/plate?code={code}')
        except Exception as e:
            print(f'  skip {code}: {e}')
            continue
        for stock in (data.get('stocks') or []):
            s = (stock or {}).get('secu_code') or ''
            if _CODE.match(s) and s not in seen:
                seen.add(s)
                pool.append(s)
        ok += 1
        time.sleep(_DELAY)
    # top up with the known-good seed list if the boards come up short
    seeds = ['sh600519', 'sz000001', 'sz300059', 'sh600036', 'sz002415',
             'sh601318', 'sz300750', 'sz000858', 'sh601012', 'sz002594',
             'sh600276', 'sz300999', 'sz002230', 'sh601899', 'sz000002',
             'sh600030', 'sh600887', 'sz300015', 'sh601166', 'sz002714',
             'sh600900', 'sz002475', 'sh600309', 'sz000651', 'sh600585',
             'sz300139']
    for s in seeds:
        if s not in seen:
            seen.add(s)
            pool.append(s)
    with open(args.out, 'w') as f:
        json.dump(pool, f)
    print(f'boards fetched OK: {ok}/{len(boards)}')
    print(f'pool: {len(pool)} codes -> {args.out}')
    if len(pool) < 1000:
        print('WARNING: pool < 1000; a tier will reuse codes (fairness via '
              'round-robin slicing stays valid).')


if __name__ == '__main__':
    main()