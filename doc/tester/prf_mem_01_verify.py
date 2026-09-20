"""PRF-MEM-01 实值核对（只读探测，不改生产/测试代码）。

核对 config.cache_policy(d) 的 pool_max / cache_max 实值 + DOMAIN_MATRIX 原始行。
运行：python doc/tester/prf_mem_01_verify.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from china_finance_rss import config  # noqa: E402

TRADING = None  # pool_max/cache_max 与 now 无关，用默认时钟即可

# 本次变更域（期望实值）
CHANGED = {
    'quote':    {'pool_max': 1000, 'cache_max': 1000},
    'fundflow': {'pool_max': 1000, 'cache_max': 1000},
    'timeline': {'pool_max': 500,  'cache_max': 500},
    'depth':    {'pool_max': config.MAX_DEDUP_CODES, 'cache_max': 500},
}

# 未变更域（回归核对）
UNTOUCHED = {
    'plate':        {'pool_max': 200,  'cache_max': None},
    'feed':         {'pool_max': 100,  'cache_max': 100},
    'announcement': {'pool_max': config.MAX_DEDUP_CODES, 'cache_max': 500},
    'f10':          {'pool_max': config.MAX_DEDUP_CODES, 'cache_max': 500},
    'margin':       {'pool_max': 16,   'cache_max': None},
    'sector':       {'pool_max': 2000, 'cache_max': 2000},
}

rows = []
fail = []


def check(domain, expect, group):
    got = config.cache_policy(domain, now=TRADING)
    ok = (got['pool_max'] == expect['pool_max']
          and got['cache_max'] == expect['cache_max'])
    if not ok:
        fail.append({'domain': domain, 'group': group, 'expect': expect,
                     'got': {'pool_max': got['pool_max'],
                             'cache_max': got['cache_max']}})
    rows.append({'domain': domain, 'group': group,
                 'pool_max': got['pool_max'], 'cache_max': got['cache_max'],
                 'expect_pool': expect['pool_max'],
                 'expect_cache': expect['cache_max'], 'ok': ok})


for d, e in CHANGED.items():
    check(d, e, 'changed')
for d, e in UNTOUCHED.items():
    check(d, e, 'untouched')

# 全部 12 域快照（含原始矩阵 spec，1:1 对照 SAD）
snapshot = {}
for d in sorted(config.DOMAIN_MATRIX):
    p = config.cache_policy(d, now=TRADING)
    snapshot[d] = {'tier': p['tier'], 'ttl': p['ttl'],
                   'pool_refresh': p['pool_refresh'],
                   'pool_max': p['pool_max'], 'cache_max': p['cache_max'],
                   'pool_spec': config.DOMAIN_MATRIX[d][3],
                   'cache_spec': config.DOMAIN_MATRIX[d][4]}

out = {
    'domain_count': len(config.DOMAIN_MATRIX),
    'rows': rows,
    'snapshot': snapshot,
    'consts': {'MAX_DEDUP_CODES': config.MAX_DEDUP_CODES,
               'MAX_CODES_PER_SUB': config.MAX_CODES_PER_SUB},
    'fail': fail,
    'verdict': 'PASS' if not fail else 'FAIL',
}
print(json.dumps(out, ensure_ascii=False, indent=1))
