"""Regression tests for ``odoo.libs.collections.ordered_set``."""

import unittest

from odoo.libs.collections.ordered_set import LastOrderedSet, OrderedSet


class TestLastOrderedSet(unittest.TestCase):
    def test_update_moves_existing_to_end(self):
        s = LastOrderedSet([1, 2, 3])
        s.update([2])
        self.assertEqual(list(s), [1, 3, 2])

    def test_update_matches_repeated_add(self):
        s = LastOrderedSet([1, 2, 3])
        s.update([2, 4, 1])
        expected = LastOrderedSet([1, 2, 3])
        for e in (2, 4, 1):
            expected.add(e)
        self.assertEqual(list(s), list(expected))


class TestOrderedSet(unittest.TestCase):
    def test_first_insertion_order_preserved_on_update(self):
        s = OrderedSet([1, 2, 3])
        s.update([2])
        self.assertEqual(list(s), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
