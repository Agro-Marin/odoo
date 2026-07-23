"""Regression tests for ``odoo.libs.set_expression`` canonicalization."""

import itertools
import random
import unittest

from odoo.libs.set_expression import SetDefinitions


def _defs():
    # A subset of B; A disjoint from C; C subset of D; E disjoint from B.
    return SetDefinitions(
        {
            1: {"ref": "A", "supersets": [2], "disjoints": [3]},
            2: {"ref": "B"},
            3: {"ref": "C", "supersets": [4]},
            4: {"ref": "D"},
            5: {"ref": "E", "disjoints": [2]},
        }
    )


class TestSetExpression(unittest.TestCase):
    def test_intersection_is_canonical(self):
        defs = _defs()
        a, b, c = defs.parse("A"), defs.parse("B"), defs.parse("C")
        # A disjoint C => A & B & C is empty, regardless of grouping/order.
        self.assertEqual((b & c) & a, a & (b & c))
        self.assertTrue(((b & c) & a).is_empty())
        self.assertTrue((a & (b & c)).is_empty())
        self.assertEqual(hash((b & c) & a), hash(a & (b & c)))

    def test_intersection_commutative_and_associative(self):
        defs = _defs()
        names = ["A", "B", "C", "D", "E"]
        sets = {n: defs.parse(n) for n in names}
        rng = random.Random(7)
        for _ in range(2000):
            x, y, z = (sets[rng.choice(names)] for _ in range(3))
            self.assertEqual(x & y, y & x)
            self.assertEqual((x & y) & z, x & (y & z))

    def test_empty_set_matches_nobody(self):
        defs = _defs()
        names = ["A", "B", "C", "D", "E"]
        sets = {n: defs.parse(n) for n in names}
        rng = random.Random(9)
        for _ in range(500):
            x, y, z = (sets[rng.choice(names)] for _ in range(3))
            expr = (x & y) & z
            if expr.is_empty():
                for size in range(1, 6):
                    for combo in itertools.combinations(range(1, 6), size):
                        self.assertFalse(expr.matches(set(combo)))

    def test_matches_empty_generator(self):
        # an empty iterator must match nothing, including the universe.
        defs = _defs()
        self.assertFalse(defs.universe.matches(iter([])))
        self.assertFalse(defs.universe.matches(set()))
        self.assertFalse((~defs.parse("A")).matches(iter([])))


if __name__ == "__main__":
    unittest.main()
