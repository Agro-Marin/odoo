import unittest

from odoo.libs.lru import LRU


class TestLRU(unittest.TestCase):
    def test_shrink_keeps_most_recent(self):
        cache = LRU(10)
        for i in range(10):
            cache[i] = i
        cache.count = 3
        self.assertEqual(len(cache), 3)
        self.assertEqual(sorted(cache.keys()), [7, 8, 9])

    def test_shrink_respects_recent_access(self):
        cache = LRU(5)
        for i in range(5):
            cache[i] = i
        _ = cache[0]
        cache.count = 2
        self.assertEqual(len(cache), 2)
        self.assertIn(0, cache)

    def test_count_must_be_positive(self):
        cache = LRU(5)
        with self.assertRaises(ValueError):
            cache.count = 0


class TestLRURepr(unittest.TestCase):
    def test_repr_reports_occupancy(self):
        lru = LRU(10, [(i, i) for i in range(3)])
        self.assertEqual(repr(lru), "LRU(count=10, size=3, gen=0)")

    def test_repr_tracks_clear_generation(self):
        lru = LRU(4, [(1, "a")])
        lru.clear()
        self.assertEqual(repr(lru), "LRU(count=4, size=0, gen=1)")

    def test_repr_does_not_leak_contents(self):
        lru = LRU(4, [("secret-key", "secret-value")])
        self.assertNotIn("secret", repr(lru))

    def test_repr_uses_the_actual_class_name(self):
        class Sub(LRU):
            pass

        self.assertTrue(repr(Sub(2)).startswith("Sub("))


if __name__ == "__main__":
    unittest.main()
