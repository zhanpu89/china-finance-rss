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
            self.assertIn(p['tier'], {'L1', 'L2', 'L3', 'L4'})
            self.assertGreater(p['ttl'], 0)
            if p['pool_refresh'] is not None:
                self.assertGreaterEqual(p['pool_refresh'], p['ttl'])

    def test_realtime_domains_le_l1(self):                    # CFG-T2 / BR-CFG-6
        for d in ('quote', 'fundflow', 'timeline'):
            self.assertLessEqual(config.cache_policy(d, now=TRADING)['ttl'], 8)
            self.assertLessEqual(config.cache_policy(d, now=OFF_HOURS)['ttl'], 120)

    def test_ttl_convergence(self):                           # CFG-T3
        cases = {
            'feed': (30, 180), 'quote': (8, 120), 'announcement': (30, 180),
            'longhu': (300, 300), 'margin': (600, 600),
        }
        for d, (on, off) in cases.items():
            self.assertEqual(config.cache_policy(d, now=TRADING)['ttl'], on)
            self.assertEqual(config.cache_policy(d, now=OFF_HOURS)['ttl'], off)

    def test_policy_values(self):
        self.assertEqual(config.cache_policy('margin', now=TRADING)['pool_refresh'], 1200)
        self.assertIsNone(config.cache_policy('sector', now=TRADING)['pool_refresh'])
        self.assertEqual(config.cache_policy('f10', now=TRADING)['pool_max'],
                         config.MAX_DEDUP_CODES)
        self.assertEqual(config.cache_policy('announcement', now=TRADING)['cache_max'], 500)
        self.assertEqual(config.cache_policy('plate', now=TRADING)['pool_max'], 200)
        self.assertEqual(config.cache_policy('quote', now=TRADING)['cache_max'], 2000)

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
                         {'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300})
        self.assertEqual(config._trading_tiers(_ts(2026, 9, 14, 20, 0)),
                         {'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300})

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
        self.assertEqual(p2['ttl'], 8)

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


class TradingHolidayTests(unittest.TestCase):
    def test_default_holidays_empty_do_not_change_behaviour(self):    # P2
        self.assertEqual(config.TRADING_HOLIDAYS, frozenset())
        self.assertTrue(config._is_trading_hours(TRADING))
        self.assertEqual(config._trading_tiers(TRADING),
                         {'L1': 8, 'L2': 12, 'L3': 30, 'L4': 300})

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
                             {'L1': 120, 'L2': 120, 'L3': 180, 'L4': 300})
            self.assertEqual(config.cache_policy('quote', now=TRADING)['ttl'], 120)


class DeprecatedAliasRemovedTests(unittest.TestCase):
    def test_cache_ttl_alias_is_gone(self):                            # P2
        self.assertFalse(hasattr(config, 'CACHE_TTL'))
        from china_finance_rss import utils
        self.assertFalse(hasattr(utils, 'CACHE_TTL'))
        # utils still imports cleanly after the same change-set edit.
        self.assertTrue(callable(utils.generate_rss))


if __name__ == '__main__':
    unittest.main()
