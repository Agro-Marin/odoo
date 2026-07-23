"""Regression tests for ``odoo.libs.func.lazy`` proxying."""

import copy
import pickle
import unittest

from odoo.libs.func import lazy


class TestLazy(unittest.TestCase):
    def test_copy_of_evaluated_lazy(self):
        obj = lazy(lambda: 41 + 1)
        _ = obj + 0  # force evaluation
        clone = copy.copy(obj)
        self.assertEqual(clone, 42)
        self.assertIsInstance(clone, lazy)

    def test_pickle_roundtrip_unevaluated(self):
        obj = lazy(lambda x: x + 1, 6)
        restored = pickle.loads(pickle.dumps(obj))  # noqa: S301  # trusted test data
        self.assertEqual(restored, 7)
        self.assertIsInstance(restored, lazy)

    def test_round_with_ndigits(self):
        obj = lazy(lambda: 3.14159)
        self.assertEqual(round(obj, 2), 3.14)
        self.assertEqual(round(obj), 3)

    def test_next_on_iterator(self):
        obj = lazy(lambda: iter([1, 2, 3]))
        self.assertEqual(next(obj), 1)
        self.assertEqual(next(obj), 2)

    def test_three_arg_pow(self):
        obj = lazy(lambda: 3)
        self.assertEqual(pow(obj, 3, 5), 2)
        self.assertEqual(obj**2, 9)

    def test_memoized_once(self):
        calls = []

        def make():
            calls.append(1)
            return 10

        obj = lazy(make)
        self.assertEqual(obj + 0, 10)
        self.assertEqual(obj + 1, 11)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
