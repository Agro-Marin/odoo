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
        self.ormcache_lrus = defaultdict(lambda: LRU(1000))


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
        self.assertEqual(model.double(5), 10)
        self.assertEqual(model.double(5), 10)
        self.assertEqual(calls, [5])

        counter = self._counter()
        self.assertEqual((counter.hit, counter.miss), (1, 1))
        self.assertEqual(counter.cache_name, "default")
        self.assertEqual((counter.tx_hit, counter.tx_miss, counter.tx_err), (0, 0, 0))
        self.assertNotIn("_ormcache_lookups", model.env.cr.cache)

    def test_flag_on_collects_tx_stats(self):
        cache_mod._TX_STATS_ENABLED = True
        calls = []
        model = _Model(calls)

        self.assertEqual(model.double(7), 14)
        self.assertIn("_ormcache_lookups", model.env.cr.cache)
        counter = self._counter()
        self.assertEqual(counter.hit, 0)
        self.assertEqual((counter.miss, counter.tx_miss), (1, 1))
        self.assertEqual(counter.cache_name, "default")

        model.env.cr.cache.clear()
        self.assertEqual(model.double(7), 14)
        self.assertEqual((counter.hit, counter.tx_hit), (1, 1))


if __name__ == "__main__":
    unittest.main()
