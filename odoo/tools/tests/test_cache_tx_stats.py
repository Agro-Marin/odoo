"""Behaviour of the ormcache per-transaction-stats toggle (``_TX_STATS_ENABLED``).

The raw hit/miss counters and ``cache_name`` are collected in both modes; the
per-transaction dedup stats (``tx_hit``/``tx_miss`` and the per-cursor
``_ormcache_lookups`` set) are only collected when the flag is on.  Pure-Python:
a stub model supplies the ``pool``/``env`` the lookup closure reads — no database.
"""

import unittest
from collections import defaultdict

from odoo.libs.lru import LRU
from odoo.tools import cache as cache_mod
from odoo.tools.cache import ormcache


class _Cursor:
    def __init__(self):
        self.cache = {}


class _Env:
    def __init__(self):
        self.cr = _Cursor()


class _Pool:
    db_name = "testdb"

    def __init__(self):
        # the closure reads the name-mangled ``pool._Registry__caches``; assign
        # the literal name via __dict__ (a plain attribute here would mangle to
        # ``_Pool__caches``). Real caches are LRU stores (the lookup reads their
        # ``.generation``), so mirror that here rather than using a plain dict.
        self.__dict__["_Registry__caches"] = defaultdict(lambda: LRU(1000))


class _Model:
    _name = "test.tx_stats"

    def __init__(self, calls):
        self.pool = _Pool()
        self.env = _Env()
        self._calls = calls

    @ormcache("a")
    def double(self, a):
        self._calls.append(a)
        return a * 2


class TestOrmcacheTxStats(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, cache_mod, "_TX_STATS_ENABLED", cache_mod._TX_STATS_ENABLED
        )
        saved = dict(cache_mod._COUNTERS)
        cache_mod._COUNTERS.clear()

        def restore():
            cache_mod._COUNTERS.clear()
            cache_mod._COUNTERS.update(saved)

        self.addCleanup(restore)

    @staticmethod
    def _counter():
        return next(iter(cache_mod._COUNTERS.values()))

    def test_flag_off_skips_tx_stats(self):
        cache_mod._TX_STATS_ENABLED = False
        calls = []
        model = _Model(calls)
        self.assertEqual(model.double(5), 10)  # cold: miss, method runs
        self.assertEqual(model.double(5), 10)  # warm: hit, method does not run
        self.assertEqual(calls, [5])

        counter = self._counter()
        self.assertEqual((counter.hit, counter.miss), (1, 1))
        self.assertEqual(counter.cache_name, "default")  # always set
        # per-transaction stats are NOT collected on the fast path
        self.assertEqual((counter.tx_hit, counter.tx_miss, counter.tx_err), (0, 0, 0))
        self.assertNotIn("_ormcache_lookups", model.env.cr.cache)

    def test_flag_on_collects_tx_stats(self):
        cache_mod._TX_STATS_ENABLED = True
        calls = []
        model = _Model(calls)

        # transaction 1: cold cache -> a tx miss, and the dedup set is created.
        self.assertEqual(model.double(7), 14)
        self.assertIn("_ormcache_lookups", model.env.cr.cache)
        counter = self._counter()
        self.assertEqual(counter.hit, 0)
        self.assertEqual((counter.miss, counter.tx_miss), (1, 1))
        self.assertEqual(counter.cache_name, "default")

        # transaction 2: warm cache, fresh dedup set -> a tx hit.
        model.env.cr.cache.clear()
        self.assertEqual(model.double(7), 14)
        self.assertEqual((counter.hit, counter.tx_hit), (1, 1))


if __name__ == "__main__":
    unittest.main()
