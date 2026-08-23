import itertools
import random
import unittest

from odoo.libs.set_expression import SetDefinitions


def _defs():
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

    def test_matches_accepts_a_one_shot_iterable(self):
        # `matches` materialises its argument before testing it; a generator
        # must not be consumed by an early check and then found empty.
        defs = _defs()
        self.assertTrue(defs.universe.matches(iter([1])))
        self.assertTrue(defs.parse("A").matches(iter([1])))


class TestMatchesFailsClosedForASubjectWithNoSets(unittest.TestCase):
    """No sets means no match, whatever the expression says.

    Read as plain boolean logic this is wrong three times over: the universal
    set contains everyone, `!A` holds for someone in no group at all, and so
    does `!A,!B`.  A truth-table comparison flags every one of them.

    It is a fail-closed rule, and it belongs here rather than in the callers:
    a group-less subject is one whose groups have not been established, and
    granting it every "everyone except A" rule in the system is the wrong way
    to be wrong.  Deleting the `not user_group_ids` guard in `Union.matches`
    makes all of these True and silently widens access.
    """

    def test_the_universal_set_does_not_match(self):
        self.assertFalse(_defs().universe.matches(set()))

    def test_a_negated_set_does_not_match(self):
        self.assertFalse((~_defs().parse("A")).matches(set()))

    def test_a_wholly_negative_expression_does_not_match(self):
        self.assertFalse(_defs().parse("!A,!B").matches(set()))

    def test_a_positive_expression_does_not_match_either(self):
        self.assertFalse(_defs().parse("A").matches(set()))

    def test_one_set_is_enough_to_turn_the_rule_off(self):
        # The guard keys on emptiness, not on membership: with any set at all,
        # ordinary semantics resume.
        defs = _defs()
        self.assertTrue(defs.universe.matches({1}))
        self.assertTrue((~defs.parse("A")).matches({2}))


if __name__ == "__main__":
    unittest.main()
