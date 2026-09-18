#!/usr/bin/env python3
"""Independent mutation harness for the RSS conditional-GET P8 fixes.

Copies `china_finance_rss/` + `tests/` to /tmp/opencode/mut/<variant>, injects
exactly one mutation, runs the full suite there, and records which tests turn
red.  It never writes to the repository.

    python3 doc/tester/mutate_p8_conditional_get.py
"""
import json
import os
import re
import shutil
import subprocess
import sys

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = '/tmp/opencode/mut'

MUTATIONS = [
    ('M1_disable_fingerprint_inheritance', 'china_finance_rss/cache.py',
     "and prev.get('fingerprint') == fingerprint):", "and False):",
     ['test_t_cache_33_fingerprint_inherits_across_expiry',
      'test_t63_ims_cross_ttl_still_304',
      'test_t64_fingerprint_inherit_and_change_two_ways']),
    ('M2_feed_cache_key_always_path', 'china_finance_rss/server.py',
     "    if PUBLIC_BASE_URL:\n        return path\n"
     "    return path + _FEED_KEY_SEP + base_url\n",
     "    return path\n",
     ['test_t65_cross_host_key_isolation',
      'test_t71_feed_fetch_lock_table_converges']),
    ('M3_release_not_in_finally', 'china_finance_rss/server.py',
     "        finally:\n"
     "            feed_fetch_release(cache_key)               "
     "# \u2605 F8: also on the exception path\n"
     "        return xml, entry['last_modified']              "
     "# entry is always a dict\n",
     "        except BaseException:\n            raise\n"
     "        feed_fetch_release(cache_key)                   "
     "# mutation: success-only\n"
     "        return xml, entry['last_modified']\n",
     ['test_t72_exception_path_reclaims_key']),
    ('M4_drop_304_incr', 'china_finance_rss/server.py',
     "        metrics.incr('http_304_total')                  "
     "# \u2605 F3: single-point 304 count\n",
     "",
     ['test_t66_http_304_total_increments']),
]


def fresh_copy(dest, mutate=None):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for sub in ('china_finance_rss', 'tests'):
        shutil.copytree(os.path.join(SRC, sub), os.path.join(dest, sub),
                        ignore=shutil.ignore_patterns('__pycache__'))
    if mutate:
        rel, old, new = mutate
        p = os.path.join(dest, rel)
        with open(p, encoding='utf-8') as fh:
            text = fh.read()
        n = text.count(old)
        assert n == 1, f'anchor count {n} != 1 in {rel}'
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(text.replace(old, new))


def run_suite(dest):
    # `python -m unittest` puts cwd (dest) on sys.path[0].
    p = subprocess.run([sys.executable, '-m', 'unittest', 'discover',
                        '-s', 'tests', '-v'],
                       cwd=dest, capture_output=True, text=True, timeout=300)
    out = p.stdout + '\n' + p.stderr
    red = sorted({m.group(1) for m in re.finditer(
        r'^(?:FAIL|ERROR): (\S+)', out, re.M)})
    tail = [ln for ln in out.splitlines() if ln.startswith('Ran ')
            or ln.startswith('OK') or ln.startswith('FAILED')]
    return {'returncode': p.returncode, 'red_tests': red,
            'summary': tail[-2:] if tail else []}


def main():
    results = {'baseline': run_suite(fresh_copy(os.path.join(ROOT, 'base'))),
               'mutations': {}}
    for name, rel, old, new, expect in MUTATIONS:
        dest = os.path.join(ROOT, name)
        fresh_copy(dest, (rel, old, new))
        r = run_suite(dest)
        r['expected_red'] = expect
        r['expected_all_red'] = all(
            any(e in t for t in r['red_tests']) for e in expect)
        results['mutations'][name] = r
    text = json.dumps(results, ensure_ascii=False, indent=2)
    with open('/tmp/opencode/mutation_results.json', 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(text)


if __name__ == '__main__':
    main()
