"""Unit tests for config.cache_policy / DOMAIN_MATRIX / env defaults (config.md §8)."""

import os
import re
import unittest
from datetime import date, datetime, timezone, timedelta
from unittest import mock

from china_finance_rss import config

_CST = timezone(timedelta(hours=8))


def _ts(y, mo, d, h, mi):
    """Epoch seconds for a CST wall-clock instant."""
    return datetime(y, mo, d, h, mi, tzinfo=_CST).timestamp()


# 2026-09-14 is a Monday, 2026-09-19 a Saturday.
TRADING = _ts(2026, 9, 14, 10, 0)
OFF_HOURS = _ts(2026, 9, 14, 20, 0)
_FIXED_KEYS = {'tier', 'ttl', 'pool_refresh', 'pool_max', 'cache_max'}


class CachePolicyTests(unittest.TestCase):
    def test_policy_shape_and_invariants(self):               # CFG-T1 / INV-1a
        for d in config.DOMAIN_MATRIX:
            p = config.cache_policy(d, now=TRADING)
            self.assertEqual(set(p) - {'encoding'}, _FIXED_KEYS)
            self.assertIn(p['tier'], {'L0', 'L1', 'L2', 'L3', 'L4'})
            self.assertGreater(p['ttl'], 0)
            if p['pool_refresh'] is not None:
                self.assertGreaterEqual(p['pool_refresh'], p['ttl'])

    def test_realtime_domains_le_l1(self):                    # CFG-T2 / BR-CFG-6
        for d in ('quote', 'fundflow', 'timeline'):
            self.assertLessEqual(config.cache_policy(d, now=TRADING)['ttl'], 8)
            self.assertLessEqual(config.cache_policy(d, now=OFF_HOURS)['ttl'], 120)

    def test_ttl_convergence(self):                           # CFG-T3
        cases = {
            'feed': (30, 180), 'quote': (4, 120), 'announcement': (30, 180),
            'longhu': (300, 300), 'margin': (600, 600),
        }
        for d, (on, off) in cases.items():
            self.assertEqual(config.cache_policy(d, now=TRADING)['ttl'], on)
            self.assertEqual(config.cache_policy(d, now=OFF_HOURS)['ttl'], off)

    def test_l0_is_the_fastest_tier(self):
        """L0 (quote + depth) is 4s in-session — the upstream's measured 3.0s
        tick gives a physical floor, 4s is the nearest poll above it — and is
        pinned to the L1 baseline (120s) off-hours so a closed market pays no
        extra requests."""
        self.assertEqual(config.cache_policy('quote', now=TRADING)['tier'], 'L0')
        self.assertEqual(config.cache_policy('depth', now=TRADING)['tier'], 'L0')
        self.assertEqual(config.cache_policy('quote', now=TRADING)['ttl'], 4)
        self.assertEqual(config.cache_policy('depth', now=TRADING)['ttl'], 4)
        self.assertEqual(config.cache_policy('quote', now=OFF_HOURS)['ttl'], 120)
        self.assertEqual(config.cache_policy('depth', now=OFF_HOURS)['ttl'], 120)
        # depth shares quote's cadence but owns its own pool/cache budget
        self.assertEqual(config.cache_policy('depth', now=TRADING)['cache_max'], 500)
        self.assertEqual(config.cache_policy('depth', now=TRADING)['pool_max'],
                         config.MAX_DEDUP_CODES)

    def test_policy_values(self):
        self.assertEqual(config.cache_policy('margin', now=TRADING)['pool_refresh'], 1200)
        self.assertIsNone(config.cache_policy('sector', now=TRADING)['pool_refresh'])
        self.assertEqual(config.cache_policy('f10', now=TRADING)['pool_max'],
                         config.MAX_DEDUP_CODES)
        self.assertEqual(config.cache_policy('announcement', now=TRADING)['cache_max'], 500)
        self.assertEqual(config.cache_policy('plate', now=TRADING)['pool_max'], 200)
        self.assertEqual(config.cache_policy('quote', now=TRADING)['cache_max'], 1000)

    def test_prf_mem_01_pool_cache_contract(self):        # CFG-T19（PRF-MEM-01）
        """3 域 pool/cache 同源收缩；depth 不变。默认值以字面量锁定，防静默回退。"""
        self.assertEqual(config.MAX_QUOTE_POOL, 1000)
        self.assertEqual(config.MAX_FUNDFLOW_POOL, 1000)
        self.assertEqual(config.MAX_TIMELINE_POOL, 500)
        q = config.cache_policy('quote', now=TRADING)
        f = config.cache_policy('fundflow', now=TRADING)
        t = config.cache_policy('timeline', now=TRADING)
        d = config.cache_policy('depth', now=TRADING)
        self.assertEqual((q['pool_max'], q['cache_max']), (1000, 1000))
        self.assertEqual((f['pool_max'], f['cache_max']), (1000, 1000))
        self.assertEqual((t['pool_max'], t['cache_max']), (500, 500))
        self.assertEqual((d['pool_max'], d['cache_max']), (config.MAX_DEDUP_CODES, 500))
        # spec 与 env 注册名单的链接（结构性断言，不做运行期热替换）
        self.assertEqual(config.DOMAIN_MATRIX['quote'][3], 'env:MAX_QUOTE_POOL')
        self.assertEqual(config.DOMAIN_MATRIX['fundflow'][3], 'env:MAX_FUNDFLOW_POOL')
        self.assertEqual(config.DOMAIN_MATRIX['timeline'][3], 'env:MAX_TIMELINE_POOL')

    def test_prf_mem_01_pool_caps_are_frozen_at_import(self):   # BR-CFG-10
        """cache_policy 不依赖可变模块全局：运行期重绑定常量不改变策略输出。"""
        original = config.MAX_TIMELINE_POOL
        config.MAX_TIMELINE_POOL = 400
        try:
            self.assertEqual(config.cache_policy('timeline', now=TRADING)['pool_max'], 500)
        finally:
            config.MAX_TIMELINE_POOL = original

    def test_prf_mem_01_env_registry_is_immutable(self):        # BR-CFG-10 / P1-1
        """注册映射本身不可变：运行期改写键/值都抛 TypeError（'导入期冻结'名副其实）。"""
        with self.assertRaises(TypeError):
            config._POOL_MAX_ENVS['MAX_TIMELINE_POOL'] = 9999
        with self.assertRaises(TypeError):
            config._POOL_MAX_ENVS['MAX_NEW_POOL'] = 1
        # 且未注册名仍是 ValueError
        self.assertEqual(config.cache_policy('timeline', now=TRADING)['pool_max'], 500)

    def test_prf_mem_01_bad_env_spec_fails_fast(self):          # P2-1
        """未注册/未定义的 env 名单一律 ValueError（不是 KeyError）。"""
        for bad in ('env:NOT_REGISTERED', 'env:', 'env:MAX_NOT_DEFINED'):
            with self.assertRaises(ValueError):
                config._resolve_pool_max(bad)

    def test_sector_override_ignores_tier_and_time(self):     # BR-CFG-2
        self.assertEqual(config.cache_policy('sector', now=TRADING)['ttl'], 604800)
        self.assertEqual(config.cache_policy('sector', now=OFF_HOURS)['ttl'], 604800)

    def test_now_injection_and_boundaries(self):              # CFG-T4
        self.assertTrue(config._is_trading_hours(_ts(2026, 9, 14, 9, 30)))
        self.assertTrue(config._is_trading_hours(_ts(2026, 9, 14, 11, 30)))
        self.assertFalse(config._is_trading_hours(_ts(2026, 9, 14, 12, 0)))
        self.assertTrue(config._is_trading_hours(_ts(2026, 9, 14, 13, 0)))
        self.assertTrue(config._is_trading_hours(_ts(2026, 9, 14, 14, 59)))
        self.assertFalse(config._is_trading_hours(_ts(2026, 9, 14, 15, 0)))
        self.assertFalse(config._is_trading_hours(_ts(2026, 9, 19, 10, 0)))  # Saturday
        self.assertEqual(config._trading_tiers(_ts(2026, 9, 14, 10, 0)),
                         {'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300})
        self.assertEqual(config._trading_tiers(_ts(2026, 9, 14, 20, 0)),
                         {'L0': 120, 'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300})

    def test_default_clock_equivalent_to_explicit_now(self):
        import time as _time
        # now=None (current clock) must agree with an explicit `now` epoch.
        self.assertEqual(config._trading_tiers(now=_time.time()),
                         config._trading_tiers())

    def test_unknown_domain_raises(self):                     # CFG-T5
        with self.assertRaises(KeyError) as ctx:
            config.cache_policy('nope')
        msg = str(ctx.exception)
        for d in config.DOMAIN_MATRIX:
            self.assertIn(d, msg)

    def test_return_value_isolation(self):                    # CFG-T6
        p1 = config.cache_policy('quote', now=TRADING)
        p2 = config.cache_policy('quote', now=TRADING)
        self.assertIsNot(p1, p2)
        p1['ttl'] = -1
        self.assertEqual(p2['ttl'], 4)

    def test_longhu_encoding(self):                           # CFG-T7
        self.assertEqual(config.cache_policy('longhu')['encoding'], 'gbk')
        for d in config.DOMAIN_MATRIX:
            if d != 'longhu':
                self.assertNotIn('encoding', config.cache_policy(d))

    def test_na_normalisation(self):                          # CFG-T8
        self.assertIsNone(config.cache_policy('news_url')['pool_max'])
        self.assertIsNone(config.cache_policy('news_url')['cache_max'])
        self.assertIsNone(config.cache_policy('longhu')['cache_max'])
        self.assertEqual(config.DOMAIN_MATRIX['news_url'][3], 'n/a')

    def test_url_cache_only_domains_declare_no_cache_max(self):  # P2-9
        """`cache_max` bounds a terminal/feed cache; URL-cache-only domains
        (plate/news_url/longhu/margin) must not advertise a per-domain cap the
        URL cache never reads — operators would otherwise tune a dead setting."""
        for d in ('plate', 'news_url', 'longhu', 'margin'):
            self.assertIsNone(config.cache_policy(d, now=TRADING)['cache_max'])

    def test_env_defaults(self):                              # CFG-T9
        self.assertEqual(config.MAX_INFLIGHT, config.MAX_WORKERS * 2)
        self.assertEqual(config.MAX_GROUPS, 200)
        self.assertEqual(config.MGMT_BODY_TIMEOUT, 5)
        self.assertEqual(config.STREAM_QUEUE_BYTES_BUDGET, 134217728)
        self.assertEqual(config.NEG_TTL, 5)
        self.assertEqual(config.PROBE_TIMEOUT, 2)
        self.assertEqual(config.MAX_HEALTH_INFLIGHT, 5)
        self.assertEqual(config.STREAM_PING_INTERVAL, 20)
        # BUG-SSE-DEPTH-01: the SSE capacity knobs.  At the old 16 workers the
        # 3-domain × 50-code set fell into C2 (coverage_codes 42 < 50) and the
        # cold first frame took 12.33s; 20 workers put it back in C1.  Guarded
        # at the config layer so a future revert is caught independently of the
        # stream-level capacity test.
        self.assertEqual(config.BATCH_MAX_WORKERS, 20)
        self.assertEqual(config.HTTP_POOL_MAX_PER_HOST, 24)
        self.assertGreaterEqual(config.HTTP_POOL_MAX_PER_HOST,
                                config.BATCH_MAX_WORKERS)
        self.assertEqual(config.STREAM_PER_FETCH_EST, 0.3)
        # PRF-MEM-01: the 3 domain pool-cap env defaults (config.md §8 CFG-T9).
        self.assertEqual(config.MAX_QUOTE_POOL, 1000)
        self.assertEqual(config.MAX_FUNDFLOW_POOL, 1000)
        self.assertEqual(config.MAX_TIMELINE_POOL, 500)

    def test_no_bare_ttl_literals(self):                      # CFG-T10
        pkg = os.path.dirname(os.path.abspath(config.__file__))
        pat = re.compile(r'\bttl\s*=\s*-?\d')
        offenders = []
        for name in ('cache.py', 'stock_api.py', 'market_api.py',
                     'server.py', 'stream.py'):
            path = os.path.join(pkg, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as fh:
                for i, line in enumerate(fh, 1):
                    code = line.split('#', 1)[0]      # ignore comments
                    if pat.search(code):
                        offenders.append(f'{name}:{i}')
        self.assertEqual(offenders, [])


class CanonicalCodeTests(unittest.TestCase):
    """P1-6: `canonical_code` is the single authority for stock-code identity.

    Frozen interface consumed by server.py / stream.py.
    """

    def test_prefixed_forms_normalise_to_lowercase(self):
        for raw in ('sh600519', 'SH600519', 'Sh600519', '  sh600519  '):
            self.assertEqual(config.canonical_code(raw), 'sh600519')
        self.assertEqual(config.canonical_code('SZ000001'), 'sz000001')
        self.assertEqual(config.canonical_code('bj430047'), 'bj430047')

    def test_dotted_forms_map_to_the_prefixed_form(self):
        self.assertEqual(config.canonical_code('600519.SH'), 'sh600519')
        self.assertEqual(config.canonical_code('600519.sh'), 'sh600519')
        self.assertEqual(config.canonical_code('000001.SZ'), 'sz000001')
        self.assertEqual(config.canonical_code('430047.BJ'), 'bj430047')

    def test_invalid_inputs_return_none(self):
        for raw in (None, 600519, '', '   ', 'sh60051', '600519', 'xx600519',
                    '600519.XX', 'sh6005190'):
            self.assertIsNone(config.canonical_code(raw), repr(raw))

    def test_idempotent(self):
        for raw in ('600519.SH', 'sz000001', '430047.BJ'):
            once = config.canonical_code(raw)
            self.assertEqual(config.canonical_code(once), once)

    def test_validation_regex_still_accepts_both_forms(self):
        # Backward compatibility: stream.py keeps importing VALID_STOCK_CODE.
        self.assertTrue(config.VALID_STOCK_CODE.match('sh600519'))
        self.assertTrue(config.VALID_STOCK_CODE.match('600519.SH'))


class UpstreamSecuCodeTests(unittest.TestCase):
    """P1: the upstream wire spelling differs per exchange — SH/SZ keep the
    prefixed canonical form, BSE needs the dotted uppercase-suffixed form
    (``bj430047`` → ``430047.BJ``).  ``canonical_code`` stays the internal
    identity key; only URL construction converts.
    """

    def test_bse_maps_to_the_dotted_uppercase_form(self):
        self.assertEqual(config.upstream_secu_code('bj430047'), '430047.BJ')
        self.assertEqual(config.upstream_secu_code('bj832000'), '832000.BJ')

    def test_shanghai_and_shenzhen_are_unchanged(self):
        self.assertEqual(config.upstream_secu_code('sh600519'), 'sh600519')
        self.assertEqual(config.upstream_secu_code('sz000001'), 'sz000001')

    def test_accepted_dotted_input_normalises_to_the_wire_form(self):
        self.assertEqual(config.upstream_secu_code('430047.BJ'), '430047.BJ')
        self.assertEqual(config.upstream_secu_code('600519.SH'), 'sh600519')

    def test_invalid_input_is_returned_verbatim(self):
        for raw in (None, 600519, '', '   ', 'sh60051', '600519', 'xx600519'):
            self.assertEqual(config.upstream_secu_code(raw), raw, repr(raw))

    def test_canonical_identity_is_not_changed_by_the_wire_mapping(self):
        # The mapping is a pure read: the canonical key/value domain is fixed.
        for raw in ('bj430047', '430047.BJ', 'sh600519', '600519.SH'):
            before = config.canonical_code(raw)
            config.upstream_secu_code(raw)
            self.assertEqual(config.canonical_code(raw), before)
        self.assertEqual(config.canonical_code('430047.BJ'), 'bj430047')
        self.assertEqual(config.canonical_code('bj430047'), 'bj430047')


class TradingHolidayTests(unittest.TestCase):
    def test_default_holidays_empty_do_not_change_behaviour(self):    # P2
        self.assertEqual(config.TRADING_HOLIDAYS, frozenset())
        self.assertTrue(config._is_trading_hours(TRADING))
        self.assertEqual(config._trading_tiers(TRADING),
                         {'L0': 4, 'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300})

    def test_parse_holidays_skips_blanks(self):                        # P2
        parsed = config._parse_holidays(' 2026-10-01 , ,2026-10-02 ')
        self.assertEqual(parsed, frozenset({date(2026, 10, 1),
                                            date(2026, 10, 2)}))
        self.assertEqual(config._parse_holidays(''), frozenset())
        self.assertEqual(config._parse_holidays(None), frozenset())

    def test_parse_holidays_rejects_malformed_date(self):              # P2
        with self.assertRaises(ValueError):
            config._parse_holidays('2026-13-99')

    def test_configured_holiday_is_off_hours(self):                    # P2
        with mock.patch.object(config, 'TRADING_HOLIDAYS',
                               frozenset({date(2026, 9, 14)})):
            self.assertFalse(config._is_trading_hours(TRADING))
            self.assertEqual(config._trading_tiers(TRADING),
                             {'L0': 120, 'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300})
            self.assertEqual(config.cache_policy('quote', now=TRADING)['ttl'], 120)


class WarmHostsTests(unittest.TestCase):
    """`warm_hosts()` derives the pre-warm transport keys from the URL constants
    (single authority), deduped and stable."""

    def test_derives_the_sse_hot_path_host(self):
        self.assertEqual(config.warm_hosts(),
                         (('https', 'x-quote.cls.cn', 443),))

    def test_follows_the_url_constants(self):
        with mock.patch.object(config, '_SSE_HOT_PATH_URLS',
                               ('https://a.example/x', 'https://a.example/y',
                                'http://b.example/z')):
            self.assertEqual(config.warm_hosts(),
                             (('https', 'a.example', 443),
                              ('http', 'b.example', 80)))


class DeprecatedAliasRemovedTests(unittest.TestCase):
    def test_cache_ttl_alias_is_gone(self):                            # P2
        self.assertFalse(hasattr(config, 'CACHE_TTL'))
        from china_finance_rss import utils
        self.assertFalse(hasattr(utils, 'CACHE_TTL'))
        # utils still imports cleanly after the same change-set edit.
        self.assertTrue(callable(utils.generate_rss))


if __name__ == '__main__':
    unittest.main()
