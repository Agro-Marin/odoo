"""Regression tests for ``odoo.libs.collections.misc.Reverse``."""

import unittest

from odoo.libs.collections.misc import Reverse


class TestReverse(unittest.TestCase):
    def test_eq_non_reverse_is_false_not_error(self):
        # comparing to a non-Reverse must not AttributeError on other.val
        self.assertFalse(Reverse(1) == 1)
        self.assertTrue(Reverse(1) != 1)

    def test_eq_reverse(self):
        self.assertEqual(Reverse(1), Reverse(1))
        self.assertNotEqual(Reverse(1), Reverse(2))

    def test_reversed_sort_order_preserved(self):
        self.assertEqual(
            sorted([Reverse(3), Reverse(1), Reverse(2)]),
            [Reverse(3), Reverse(2), Reverse(1)],
        )


if __name__ == "__main__":
    unittest.main()
