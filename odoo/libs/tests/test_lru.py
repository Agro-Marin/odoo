"""Regression tests for ``odoo.libs.lru.LRU`` resizing."""

import unittest

from odoo.libs.lru import LRU


class TestLRU(unittest.TestCase):
    def test_shrink_keeps_most_recent(self):
        cache = LRU(10)
        for i in range(10):
            cache[i] = i
        cache.count = 3
        self.assertEqual(len(cache), 3)
        # the three most-recently inserted keys survive
        self.assertEqual(sorted(cache.keys()), [7, 8, 9])

    def test_shrink_respects_recent_access(self):
        cache = LRU(5)
        for i in range(5):
            cache[i] = i
        _ = cache[0]  # touch key 0 -> now most recently used
        cache.count = 2
        self.assertEqual(len(cache), 2)
        self.assertIn(0, cache)

    def test_count_must_be_positive(self):
        cache = LRU(5)
        with self.assertRaises(ValueError):
            cache.count = 0


if __name__ == "__main__":
    unittest.main()
