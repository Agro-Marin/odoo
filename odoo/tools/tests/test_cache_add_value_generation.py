import unittest
from collections import defaultdict

from odoo.libs.lru import LRU
from odoo.tools.cache import ormcache


class _Pool:
    def __init__(self):
        self.ormcache_lrus = defaultdict(lambda: LRU(1000))


class _Model:
    _name = "test.add_value"

    def __init__(self):
        self.pool = _Pool()

    @ormcache("name")
    def _get_id(self, name):
        raise AssertionError("primed via add_value; _get_id must not run")


class TestAddValueGeneration(unittest.TestCase):
    def setUp(self):
        self.model = _Model()
        self.cache = type(self.model)._get_id.__cache__
        self.lru = self.model.pool.ormcache_lrus[self.cache.cache_name]

    def _key(self, name):
        return self.cache.key(self.model, name)

    def test_without_generation_the_write_is_unconditional(self):
        self.cache.add_value(self.model, "a", cache_value=1)
        self.assertEqual(self.lru[self._key("a")], 1)

    def test_matching_generation_writes(self):
        gen = self.cache.generation_of(self.model)
        self.cache.add_value(self.model, "a", cache_value=1, generation=gen)
        self.assertEqual(self.lru[self._key("a")], 1)

    def test_a_clear_between_snapshot_and_write_drops_the_stale_value(self):
        gen = self.cache.generation_of(self.model)
        self.lru.clear()
        self.assertNotEqual(self.cache.generation_of(self.model), gen)
        self.cache.add_value(self.model, "a", cache_value=1, generation=gen)
        with self.assertRaises(KeyError):
            self.lru[self._key("a")]

    def test_generation_of_tracks_clears(self):
        g0 = self.cache.generation_of(self.model)
        self.lru.clear()
        self.assertEqual(self.cache.generation_of(self.model), g0 + 1)


if __name__ == "__main__":
    unittest.main()
