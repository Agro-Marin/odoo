from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import common
from odoo.tools import SetDefinitions, SetExpressionError


@common.tagged("at_install", "groups")
class TestGroupsObject(common.BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.definitions = SetDefinitions(
            {
                1: {"ref": "A"},
                2: {"ref": "A1", "supersets": [1]},  # A1 <= A
                3: {"ref": "A11", "supersets": [2]},  # A11 <= A1
                4: {"ref": "A2", "supersets": [1]},  # A2 <= A
                5: {"ref": "A21", "supersets": [4]},  # A21 <= A2
                6: {"ref": "A22", "supersets": [4]},  # A22 <= A2
                7: {"ref": "B"},
                8: {"ref": "B1", "supersets": [7]},  # B1 <= B
                9: {"ref": "B11", "supersets": [8]},  # B11 <= B1
                10: {"ref": "B2", "supersets": [7]},  # B2 <= B
                11: {
                    "ref": "BX",
                    "supersets": [7],  # BX <= B
                    "disjoints": [8, 10],
                },  # BX disjoint from B1, B2
                12: {"ref": "A1B1", "supersets": [2, 8]},  # A1B1 <= A1, B1
                13: {"ref": "C"},
                14: {"ref": "D", "disjoints": [1, 7]},  # D disjoint from A, B
                15: {
                    "ref": "E",
                    "disjoints": [1, 7, 14],
                },  # E disjoint from A, B, D
                16: {
                    "ref": "E1",
                    "supersets": [15],
                },  # E1 <= E (and thus disjoint from A, B, D)
            }
        )

    def test_groups_1_base(self):
        A = self.definitions.parse("A")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")

        self.assertTrue(hash(A), "'Group object must be hashable'")
        self.assertEqual(str(A), "'A'")
        self.assertEqual(str(B), "'B'")
        self.assertEqual(str(B1), "'B1'")

    def test_groups_2_and(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B11 = self.definitions.parse("B11")
        BX = self.definitions.parse("BX")
        universe = self.definitions.universe
        empty = self.definitions.empty

        self.assertEqual(str(A & B), "'A' & 'B'")
        self.assertEqual(str(B & A), "'A' & 'B'")
        self.assertEqual(str(B & BX), "'BX'")
        self.assertEqual(str(B1 & BX), "~*")
        self.assertEqual(str(B11 & BX), "~*")
        self.assertEqual(str(empty & empty), "~*")
        self.assertEqual(str(A & universe), "'A'")
        self.assertEqual(str(A & empty), "~*")
        self.assertEqual(str(A1 & ~A), "~*")
        self.assertEqual(str(A & A1 & universe), "'A1'")

    def test_groups_3_or(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B11 = self.definitions.parse("B11")
        B2 = self.definitions.parse("B2")
        BX = self.definitions.parse("BX")
        universe = self.definitions.universe
        empty = self.definitions.empty

        self.assertEqual(str(A | A), "'A'")
        self.assertEqual(str(A | B), "'A' | 'B'")
        self.assertEqual(str(A1 | A), "'A'")
        self.assertEqual(str(A | A1), "'A'")
        self.assertEqual(str(A | B1), "'A' | 'B1'")
        self.assertEqual(str(B | A), "'A' | 'B'")
        self.assertEqual(str(B | BX), "'B'")
        self.assertEqual(str(B1 | BX), "'B1' | 'BX'")
        self.assertEqual(str(B11 | BX), "'B11' | 'BX'")
        self.assertEqual(str(empty | empty), "~*")
        self.assertEqual(str(A | B11 | B2), "'A' | 'B11' | 'B2'")
        self.assertEqual(str(A | B2 | B11), "'A' | 'B11' | 'B2'")
        self.assertEqual(str(A | empty), "'A'")
        self.assertEqual(str(A | universe), "*")
        self.assertEqual(str((A | A1) | empty), "'A'")

    def test_groups_3_or_and(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A2 = self.definitions.parse("A2")
        B1 = self.definitions.parse("B1")
        B2 = self.definitions.parse("B2")
        universe = self.definitions.universe
        empty = self.definitions.empty

        self.assertEqual(str((A & B1) | B2), "('A' & 'B1') | 'B2'")
        self.assertEqual(str(A | B1 & B2), "'A' | ('B1' & 'B2')")
        self.assertEqual(str(A | A1 & universe), "'A'")
        self.assertEqual(
            str((A1 | A2) & (B1 | B2)),
            "('A1' & 'B1') | ('A1' & 'B2') | ('A2' & 'B1') | ('A2' & 'B2')",
        )
        self.assertEqual(str(A | (A1 | empty)), "'A'")
        self.assertEqual(str((A & A1) | empty), "'A1'")
        self.assertEqual(str(A & (A1 | empty)), "'A1'")

    def test_groups_4_gt_lt(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        A2 = self.definitions.parse("A2")
        A21 = self.definitions.parse("A21")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B11 = self.definitions.parse("B11")
        B2 = self.definitions.parse("B2")
        A1B1 = self.definitions.parse("A1B1")

        self.assertEqual(A == A, True)
        self.assertEqual(A == B, False)

        self.assertEqual(A >= A1, True)
        self.assertEqual(A >= A, True)
        self.assertEqual((A & B) >= B, False)
        self.assertEqual(B1 >= A1B1, True)
        self.assertEqual(B1 >= (A1 | A1B1), False)
        self.assertEqual(B >= (A & B), True)

        self.assertEqual(A > B, False)
        self.assertEqual(A > A1, True)
        self.assertEqual(A1 > A, False)
        self.assertEqual(A > A, False)
        self.assertEqual(A > A11, True)
        self.assertEqual(A > A2, True)
        self.assertEqual(A > A21, True)
        self.assertEqual(A1 > A11, True)
        self.assertEqual(A2 > A11, False)
        self.assertEqual(A2 > A21, True)
        self.assertEqual(A > B1, False)
        self.assertEqual(A > B11, False)
        self.assertEqual(A > B2, False)

        self.assertEqual(A <= A, True)
        self.assertEqual(A1 <= A, True)
        self.assertEqual((A & B) <= B, True)
        self.assertEqual((A & B) <= A, True)
        self.assertEqual(B1 <= (A1 | A1B1), False)
        self.assertEqual(B <= (A & B), False)
        self.assertEqual(A <= (A & B), False)
        self.assertEqual(A <= (A | B), True)

        self.assertEqual(A < B, False)
        self.assertEqual(A < A1, False)
        self.assertEqual(A1 < A, True)
        self.assertEqual(A < A1, False)
        self.assertEqual(A < A11, False)
        self.assertEqual(A < A2, False)
        self.assertEqual(A < A21, False)
        self.assertEqual(A < B1, False)
        self.assertEqual(A < B11, False)
        self.assertEqual(A < B2, False)
        self.assertEqual(A < (A | B), True)

    def test_groups_5_invert(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A2 = self.definitions.parse("A2")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B11 = self.definitions.parse("B11")
        B2 = self.definitions.parse("B2")
        BX = self.definitions.parse("BX")
        universe = self.definitions.universe
        empty = self.definitions.empty

        self.assertEqual(str(~A), "~'A'")
        self.assertEqual(str(~A1), "~'A1'")
        self.assertEqual(str(~B), "~'B'")
        self.assertEqual(str(~universe), "~*")
        self.assertEqual(str(~empty), "*")

        self.assertEqual(str(~(A & B)), "~'A' | ~'B'")
        self.assertEqual(str(~(A | B)), "~'A' & ~'B'")
        self.assertEqual(str(~A & ~A1), "~'A'")

        self.assertEqual(str(A | ~A), "*")
        self.assertEqual(str(~A | ~A1), "~'A1'")
        self.assertEqual(str(~(A | A1)), "~'A'")
        self.assertEqual(~(A | A1), ~A & ~A1)
        self.assertEqual(str(~(A & A1)), "~'A1'")
        self.assertEqual(~(A & A1), ~A | ~A1)
        self.assertEqual(str(~(~B1 & ~B2)), "'B1' | 'B2'")

        self.assertEqual(str(A & ~A), "~*")
        self.assertEqual(str(A & ~A1), "'A' & ~'A1'")
        self.assertEqual(str(~A & A), "~*")
        self.assertEqual(str(~A & A1), "~*")
        self.assertEqual(str(~A1 & A), "'A' & ~'A1'")
        self.assertEqual(str(B11 & ~BX), "'B11'")
        self.assertEqual(str(~B1 & BX), "'BX'")
        self.assertEqual(str(~B11 & BX), "'BX'")

        self.assertEqual(str(~((A & B1) | B2)), "(~'A' & ~'B2') | (~'B1' & ~'B2')")
        self.assertEqual(str(~(A | (B1 & B2))), "(~'A' & ~'B1') | (~'A' & ~'B2')")
        self.assertEqual(str(~(A | (B2 & B1))), "(~'A' & ~'B1') | (~'A' & ~'B2')")
        self.assertEqual(
            str(~((A1 & A2) | (B1 & B2))),
            "(~'A1' & ~'B1') | (~'A1' & ~'B2') | (~'A2' & ~'B1') | (~'A2' & ~'B2')",
        )
        self.assertEqual(str(~A & ~B2), "~'A' & ~'B2'")
        self.assertEqual(str(~(~B1 & ~B2)), "'B1' | 'B2'")
        self.assertEqual(str(~((A & B) | A1)), "~'A' | (~'A1' & ~'B')")
        self.assertEqual(str(~(~A | (~A1 & ~B))), "('A' & 'B') | 'A1'")
        self.assertEqual(str(~~((A & B) | A1)), "('A' & 'B') | 'A1'")

    def test_groups_invert_blowup_is_guarded(self):
        """Inverting a large disjunction must raise SetExpressionError fast.

        De Morgan expands ``~((A1 & A2) | ...)`` to ``2**N`` terms for N two-leaf
        disjuncts, so a pathological expression must be guarded, not materialized.
        """
        # 40 groups -> 20 two-leaf intersections; inverting = 2**20 terms.
        defs = SetDefinitions({i: {"ref": f"g{i}"} for i in range(1, 41)})
        groups = [defs.parse(f"g{i}") for i in range(1, 41)]
        expr = defs.empty
        for i in range(0, 40, 2):
            expr = expr | (groups[i] & groups[i + 1])

        with self.assertRaises(SetExpressionError):
            _ = ~expr

        # A small inversion of the same shape still succeeds.
        small = (groups[0] & groups[1]) | (groups[2] & groups[3])
        self.assertTrue(str(~small))

    def test_groups_6_invert_gt_lt(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")

        self.assertEqual(A < A1, False)
        self.assertEqual(~A < ~A1, True)
        self.assertEqual(A > A1, True)
        self.assertEqual(~A > ~A1, False)
        self.assertEqual(~A1 > ~A, True)
        self.assertEqual(A < ~A, False)
        self.assertEqual(A < ~A1, False)
        self.assertEqual(~A < ~A, False)
        self.assertEqual(~A < ~A1, True)

    def test_groups_7_various(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        B = self.definitions.parse("B")

        self.assertEqual(str(~A & (A | B)), "~'A' & 'B'")
        self.assertEqual(str(A1 & B & ~A), "~*")
        self.assertEqual(str(A1 & ~A & B), "~*")
        self.assertEqual(str(~A1 & A & B), "'A' & ~'A1' & 'B'")

    def test_groups_8_reduce(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B2 = self.definitions.parse("B2")
        universe = self.definitions.universe
        empty = self.definitions.empty

        self.assertEqual(str((A | B) & B), "'B'")
        self.assertEqual(str((A & B) | (A & ~B)), "'A'")
        self.assertEqual(str((A & B1 & B2) | (A & B1 & ~B2)), "'A' & 'B1'")
        self.assertEqual(str((A & ~B2 & B1) | (A & B1 & B2)), "'A' & 'B1'")
        self.assertEqual(
            str((A & B1 & ~B2) | (A & ~B1 & B2)),
            "('A' & 'B1' & ~'B2') | ('A' & ~'B1' & 'B2')",
        )
        self.assertEqual(
            str(
                ((B2 & A1) | (B2 & A1 & A11))
                | ((B2 & A11) | (~B2 & A1) | (~B2 & A1 & A11))
            ),
            "'A1'",
        )
        self.assertEqual(
            str(
                ~(
                    ((B2 & A1) | (B2 & A1 & A11))
                    | ((B2 & A11) | (~B2 & A1) | (~B2 & A1 & A11))
                )
            ),
            "~'A1'",
        )
        self.assertEqual(str(~((~A & B) | (A & B) | (A & ~B))), "~'A' & ~'B'")
        self.assertEqual(str((~A & ~B2) & (B1 | B2)), "~'A' & 'B1' & ~'B2'")
        self.assertEqual(str((~A & ~B2) & ~(~B1 & ~B2)), "~'A' & 'B1' & ~'B2'")
        self.assertEqual(str(~A & ~B2 & universe), "~'A' & ~'B2'")
        self.assertEqual(
            str((~A & ~B2 & universe) & ~(~B1 & ~B2)), "~'A' & 'B1' & ~'B2'"
        )
        self.assertEqual(str((~A & ~B2 & empty) & ~(~B1 & ~B2)), "~*")
        self.assertEqual(str((~A & ~B2) & ~(~B1 & ~B2 & empty)), "~'A' & ~'B2'")
        self.assertEqual(str((~A & B1 & A) & B), "~*")

    def test_groups_9_distinct(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        A1B1 = self.definitions.parse("A1B1")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B11 = self.definitions.parse("B11")
        E = self.definitions.parse("E")
        E1 = self.definitions.parse("E1")

        self.assertEqual(A <= E, False)
        self.assertEqual(A >= E, False)
        self.assertEqual(A <= ~E, True)
        self.assertEqual(A >= ~E, False)
        self.assertEqual(A11 <= ~E, True)
        self.assertEqual(A11 >= ~E, False)
        self.assertEqual(~A >= E, True)
        self.assertEqual(~A11 >= E, True)
        self.assertEqual(~A >= ~E, False)
        self.assertEqual(~A11 >= ~E, False)
        self.assertEqual(A <= E1, False)
        self.assertEqual(A >= E1, False)
        self.assertEqual(A <= ~E1, True)
        self.assertEqual(A >= ~E1, False)
        self.assertEqual(A11 <= ~E1, True)
        self.assertEqual(A11 >= ~E1, False)
        self.assertEqual(~A >= E1, True)
        self.assertEqual(~A11 >= E1, True)
        self.assertEqual(~A >= ~E1, False)
        self.assertEqual(~A <= ~E1, False)
        self.assertEqual(~A11 >= ~E1, False)

        self.assertEqual(str(B11 & ~E), "'B11'")
        self.assertEqual(str(~A11 | E), "~'A11'")
        self.assertEqual(str(~(A1 & A11 & ~E)), "~'A11'")
        self.assertEqual(str(B1 & E), "~*")
        self.assertEqual(str(B11 & E), "~*")
        self.assertEqual(str(B1 | E), "'B1' | 'E'")
        self.assertEqual(str((B1 & E) | A1B1), "'A1B1'")
        self.assertEqual(str(A1 & A11 & ~E), "'A11'")
        self.assertEqual(str(~E & (E | B)), "'B'")
        self.assertEqual(str((~E & E) | B), "'B'")

    def test_groups_10_hudge_combine(self):
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B2 = self.definitions.parse("B2")
        A1B1 = self.definitions.parse("A1B1")
        C = self.definitions.parse("C")
        D = self.definitions.parse("D")
        E = self.definitions.parse("E")

        Z1 = C | B2 | A1 | A11
        Z2 = (
            (C) | (C & B2) | (C & B2 & A1) | (C & B2 & A11) | (C & ~B2) | (C & ~B2 & A1)
        )
        Z3 = (
            (C & ~B2 & A11)
            | (C & A1)
            | (C & A1 & B1)
            | (C & A11)
            | (C & A11 & B1)
            | (C & B1)
        )
        Z4 = (B2 & A1) | (B2 & A1 & A11) | (B2 & A11) | (~B2 & A1) | (~B2 & A1 & A11)
        Z5 = (
            (~B2 & A11)
            | (A1)
            | (A1 & A11)
            | (A1 & A11 & B1)
            | (A1 & B1)
            | (A11)
            | (A11 & B1)
        )
        group1 = Z1 & (Z2 | Z3 | Z4 | Z5)

        self.assertEqual(str(group1), "'A1' | 'C'")
        self.assertEqual(str(~group1), "~'A1' & ~'C'")
        self.assertEqual(str(~~group1), "'A1' | 'C'")
        self.assertEqual(str((~group1).invert_intersect(~A1)), "~'C'")

        self.assertEqual(str(group1 & B), "('A1' & 'B') | ('B' & 'C')")
        self.assertEqual(str(~(group1 & B)), "(~'A1' & ~'C') | ~'B'")
        self.assertEqual(str(~~(group1 & B)), "('A1' & 'B') | ('B' & 'C')")
        self.assertEqual(str((group1 & B).invert_intersect(B)), "'A1' | 'C'")

        self.assertFalse((group1 & B).invert_intersect(A1))

        self.assertEqual(str(A1 & D), "~*")
        self.assertEqual(str(group1 & (C | B | D)), "('A1' & 'B') | 'C'")
        self.assertEqual(str(~(group1 & (C | B | D))), "(~'A1' & ~'C') | (~'B' & ~'C')")

        group2 = (B1 | D) & (A1B1 | (A1B1 & D) | (A1B1 & D & E) | (A1B1 & E) | E)
        self.assertEqual(str(group2), "'A1B1'")

    def test_groups_11_invert_intersect(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        A2 = self.definitions.parse("A2")
        A21 = self.definitions.parse("A21")
        A22 = self.definitions.parse("A22")
        B = self.definitions.parse("B")
        B1 = self.definitions.parse("B1")
        B2 = self.definitions.parse("B2")
        D = self.definitions.parse("D")

        self.assertEqual(str((A1 & A2).invert_intersect(A2)), "'A1'")
        self.assertEqual(str((A1 & B1 | A1 & B2).invert_intersect(A1)), "'B1' | 'B2'")
        self.assertEqual(
            str((A1 & B1 | A1 & B2 | A1 & A2).invert_intersect(A1)),
            "'A2' | 'B1' | 'B2'",
        )
        self.assertEqual(str((A1 & B1 | A2 & B1).invert_intersect(A1 | A2)), "'B1'")
        self.assertEqual(
            str((A1 & B1 | A1 & B2 | A2 & B1 | A2 & B2).invert_intersect(A1 | A2)),
            "'B1' | 'B2'",
        )
        self.assertEqual(A.invert_intersect(A | B), None)
        self.assertEqual(A.invert_intersect(A1 | A2), None)
        self.assertEqual(A.invert_intersect(A | D), None)

        tests = [
            (A2, A1),
            (B1 | B2, A1),
            (A2 | B1 | B2, A1),
            (B1, A1 | A2),
            (B1 | B2, A1 | A2),
            (B1 & B2, A1),
            (A2 & B1 & B2, A1),
            (B1 & B2, A1 | A2),
            (A1, B1 & B2),
            (A1 | A2, B1 & B2),
            (A1, A2 | B1 & B2),
            (A11 | A21, A22 | B1 & B2),
            (A11 & A21, A22 | B1 & B2),
            (A, A1 | B),
            (A1 | B, A),
        ]
        for a, b in tests:
            self.assertEqual(
                str((a & b).invert_intersect(b)),
                str(a),
                f"Should invert_intersect: {a & b}\nby: ({b})",
            )

    def test_groups_matches(self):
        A = self.definitions.parse("A")
        A1 = self.definitions.parse("A1")
        A11 = self.definitions.parse("A11")
        B = self.definitions.parse("B")
        C = self.definitions.parse("C")
        D = self.definitions.parse("D")

        matching = [
            (A, {1, 13}),
            (A, {1, 2, 3, 13}),
            (A1, {1, 2, 13}),
            (A11, {1, 2, 3, 13}),
            (A | B, {1, 13}),
            (B | C, {1, 13}),
            (A1 | B, {1, 2, 13}),
            (A11 | B, {1, 2, 3, 13}),
            ((A11 | B) & ~D, {1, 2, 3, 13}),
            (A & ~A11, {1, 13}),
            (A & ~A11, {1, 2, 13}),
        ]
        for spec, group_ids in matching:
            self.assertTrue(
                spec.matches(group_ids),
                f"user with groups {self.definitions.from_ids(group_ids, keep_subsets=True)} should match {spec}",
            )

        non_matching = [
            (A, {13}),
            (A1, {13}),
            (A11, {13}),
            (A | B, {13}),
            (A & ~C, {13}),
            (A & ~B & ~C, {13}),
            ((A11 | B) & ~C, {1, 2, 3, 13}),
            (A & ~A11, {1, 2, 3, 13}),
        ]
        for spec, group_ids in non_matching:
            self.assertFalse(
                spec.matches(group_ids),
                f"user with groups {self.definitions.from_ids(group_ids, keep_subsets=True)} should not match {spec}",
            )

    def test_groups_unknown(self):
        A = self.definitions.parse("A")
        U1 = self.definitions.parse("unknown.group1", raise_if_not_found=False)
        U2 = self.definitions.parse("unknown.group2", raise_if_not_found=False)

        self.assertEqual(U1, U1)
        self.assertNotEqual(U1, U2)

        self.assertEqual(A | U1, U1 | A)
        self.assertEqual(U1 | U2, U2 | U1)
        self.assertEqual(A & U1, U1 & A)
        self.assertEqual(U1 & U2, U2 & U1)

        self.assertEqual(A | U1 | U2, A | U1 | U2)
        self.assertEqual(A | U2 | U1, A | U1 | U2)
        self.assertEqual(U1 | A | U2, A | U1 | U2)
        self.assertEqual(U1 | A | U2, A | U1 | U2)
        self.assertEqual(U2 | A | U1, A | U1 | U2)
        self.assertEqual(U2 | U1 | A, A | U1 | U2)

        self.assertEqual(A & U1 & U2, A & U1 & U2)
        self.assertEqual(A & U2 & U1, A & U1 & U2)
        self.assertEqual(U1 & A & U2, A & U1 & U2)
        self.assertEqual(U1 & A & U2, A & U1 & U2)
        self.assertEqual(U2 & A & U1, A & U1 & U2)
        self.assertEqual(U2 & U1 & A, A & U1 & U2)

    def test_groups_key(self):
        A = self.definitions.parse("A")
        B = self.definitions.parse("B")
        C = self.definitions.parse("C")
        U = self.definitions.parse("unknown.group", raise_if_not_found=False)

        test_cases = [
            A,
            A | B,
            A & B,
            A & ~B,
            (A | B) & ~C,
            U,
            A | U | B,
        ]

        for groups in test_cases:
            self.assertIsInstance(groups.key, str)
            groups1 = self.definitions.from_key(groups.key)
            self.assertEqual(groups1, groups)
            self.assertEqual(groups1.key, groups.key)


@common.tagged("at_install", "groups")
class TestGroupsOdoo(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_group = cls.env["res.groups"].create(
            {
                "name": "test with implied user",
                "implied_ids": [Command.link(cls.env.ref("base.group_user").id)],
            }
        )
        cls.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "base_test_group",
                "model": "res.groups",
                "res_id": cls.test_group.id,
            }
        )
        cls.definitions = cls.env["res.groups"]._get_group_definitions()

    def parse_repr(self, group_repr):
        """Return the group object parsed from its repr string.

        ``group_repr`` uses ``|`` (union), ``&`` (intersection, binds tighter),
        and ``~`` (inversion), like the Python object's repr.
        """
        if not group_repr:
            return self.definitions.universe
        res = None
        for union in group_repr.split("|"):
            union = union.strip()
            intersection = None
            if union.startswith("(") and union.endswith(")"):
                union = union[1:-1]
            for xmlid in union.split("&"):
                xmlid = xmlid.strip()
                leaf = (
                    ~self.definitions.parse(xmlid[1:])
                    if xmlid.startswith("~")
                    else self.definitions.parse(xmlid)
                )
                if intersection is None:
                    intersection = leaf
                else:
                    intersection &= leaf
            if intersection is None:
                return self.definitions.universe
            elif res is None:
                res = intersection
            else:
                res |= intersection
        return self.definitions.empty if res is None else res

    def test_groups_1_base(self):
        parse = self.definitions.parse

        self.assertEqual(
            str(parse("base.group_user") & parse("base.group_user")),
            "'base.group_user'",
        )
        self.assertEqual(
            str(parse("base.group_user") & parse("base.group_system")),
            "'base.group_system'",
        )
        self.assertEqual(
            str(parse("base.group_system") & parse("base.group_user")),
            "'base.group_system'",
        )
        self.assertEqual(
            str(parse("base.group_erp_manager") & parse("base.group_system")),
            "'base.group_system'",
        )
        self.assertEqual(
            str(parse("base.group_system") & parse("base.group_multi_currency")),
            "'base.group_system' & 'base.group_multi_currency'",
        )
        self.assertEqual(
            str(parse("base.group_user") | parse("base.group_user")),
            "'base.group_user'",
        )
        self.assertEqual(
            str(parse("base.group_user") | parse("base.group_system")),
            "'base.group_user'",
        )
        self.assertEqual(
            str(parse("base.group_system") | parse("base.group_public")),
            "'base.group_system' | 'base.group_public'",
        )
        self.assertEqual(
            parse("base.group_system") < parse("base.group_erp_manager"), True
        )
        self.assertEqual(
            parse("base.group_system") < parse("base.group_sanitize_override"),
            True,
        )
        self.assertEqual(
            parse("base.group_erp_manager") < parse("base.group_user"), True
        )
        self.assertEqual(
            parse("!base.group_portal") < parse("!base.group_public"), False
        )
        self.assertEqual(
            parse("base.base_test_group") == parse("base.base_test_group"), True
        )
        self.assertEqual(parse("base.group_system") <= parse("base.group_system"), True)
        self.assertEqual(
            parse("base.group_public") <= parse("base.group_system"), False
        )  # None ?
        self.assertEqual(parse("base.group_user") <= parse("base.group_system"), False)
        self.assertEqual(parse("base.group_system") <= parse("base.group_user"), True)
        self.assertEqual(parse("base.group_user") <= parse("base.group_portal"), False)
        self.assertEqual(
            parse("!base.group_portal") <= parse("!base.group_public"), False
        )

    def test_groups_2_from_commat_separator(self):
        parse = self.definitions.parse

        self.assertEqual(
            str(
                parse("base.group_user,base.group_system") & parse("base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_erp_manager")
                & parse("base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_portal") & parse("base.group_portal")
            ),
            "'base.group_portal'",
        )
        self.assertEqual(
            str(
                parse(
                    "base.group_user,base.group_portal,base.group_public,base.group_multi_company"
                )
                & parse("base.group_portal,base.group_public")
            ),
            "'base.group_portal' | 'base.group_public'",
        )
        self.assertEqual(
            str(
                parse("base.group_system,base.base_test_group")
                & parse("base.group_user")
            ),
            "'base.group_system' | 'base.base_test_group'",
        )
        self.assertEqual(
            str(
                parse("base.group_system,base.group_portal") & parse("base.group_user")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user") & parse("!base.group_portal,base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("!base.group_portal")
                & parse("base.group_portal,base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(parse("base.group_portal,!base.group_user") & parse("base.group_user")),
            "~*",
        )
        self.assertEqual(
            str(parse("!base.group_user") & parse("base.group_portal,base.group_user")),
            "'base.group_portal'",
        )
        self.assertEqual(
            str(parse("base.group_user") & parse("base.group_portal,!base.group_user")),
            "~*",
        )
        self.assertEqual(
            str(
                parse("!base.group_user")
                & parse("base.group_portal,!base.group_system")
            ),
            "'base.group_portal'",
        )
        self.assertEqual(
            str(
                parse("!base.group_user,base.group_multi_currency")
                & parse("base.group_multi_currency,!base.group_system")
            ),
            "~'base.group_user' & 'base.group_multi_currency'",
        )
        self.assertEqual(
            str(
                parse("!base.group_user,base.group_portal")
                & parse("base.group_portal,!base.group_system")
            ),
            "'base.group_portal'",
        )
        self.assertEqual(str(parse("!*") & parse("base.group_portal")), "~*")
        self.assertEqual(
            str(parse("*") & parse("base.group_portal")), "'base.group_portal'"
        )
        self.assertEqual(
            str(
                parse("base.group_user,!base.group_system")
                & parse("base.group_erp_manager,base.group_portal")
            ),
            "'base.group_erp_manager' & ~'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,!base.group_system")
                & parse("base.group_portal,base.group_erp_manager")
            ),
            "'base.group_erp_manager' & ~'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user")
                & parse("base.group_portal,base.group_erp_manager,!base.group_system")
            ),
            "'base.group_erp_manager' & ~'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user") & parse("base.group_portal,base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_system")
                & parse("base.group_portal,base.group_system")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user")
                & parse("base.group_portal,base.group_erp_manager")
            ),
            "'base.group_erp_manager'",
        )
        self.assertEqual(
            str(
                parse("base.group_user") & parse("base.group_portal,!base.group_system")
            ),
            "~*",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_system")
                & parse("base.group_system,base.group_portal")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user") & parse("base.group_system,base.group_portal")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_system")
                & parse("base.group_multi_currency")
            ),
            "'base.group_user' & 'base.group_multi_currency'",
        )
        self.assertEqual(
            str(
                parse("base.group_user,base.group_erp_manager")
                | parse("base.group_system")
            ),
            "'base.group_user'",
        )
        self.assertEqual(
            str(
                parse("base.group_user") | parse("base.group_portal,base.group_system")
            ),
            "'base.group_user' | 'base.group_portal'",
        )
        self.assertEqual(
            str(parse("!*") | parse("base.group_user")), "'base.group_user'"
        )
        self.assertEqual(
            str(parse("base.group_user") | parse("!*")), "'base.group_user'"
        )
        self.assertEqual(
            str(parse("!*") | parse("base.group_user,base.group_portal")),
            "'base.group_user' | 'base.group_portal'",
        )
        self.assertEqual(str(parse("*") | parse("base.group_user")), "*")
        self.assertEqual(str(parse("base.group_user") | parse("*")), "*")
        self.assertEqual(
            str(
                parse("base.group_user,base.group_erp_manager")
                | parse("base.group_system,base.group_public")
            ),
            "'base.group_user' | 'base.group_public'",
        )
        self.assertEqual(
            parse("base.group_system")
            < parse("base.group_erp_manager,base.group_sanitize_override"),
            True,
        )
        self.assertEqual(
            parse("!base.group_public,!base.group_portal")
            < parse("!base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,base.base_test_group")
            == parse("base.group_system,base.base_test_group"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,base.base_test_group")
            == parse("base.base_test_group,base.group_system"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,base.base_test_group")
            == parse("base.base_test_group,base.group_public"),
            False,
        )
        self.assertEqual(
            parse("base.group_system,base.base_test_group")
            == parse("base.base_test_group"),
            False,
        )
        self.assertEqual(
            parse("base.group_user") <= parse("base.group_system,base.group_public"),
            False,
        )
        self.assertEqual(
            parse("base.group_system") <= parse("base.group_user,base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_public") <= parse("base.group_system,base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,base.group_public")
            <= parse("base.group_system,base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,base.group_public")
            <= parse("base.group_user,base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,!base.group_public") <= parse("base.group_system"),
            True,
        )
        self.assertEqual(
            parse("base.group_system,!base.group_multi_currency")
            <= parse("base.group_system"),
            True,
        )
        self.assertEqual(
            parse("base.group_system")
            <= parse("base.group_system,!base.group_multi_currency"),
            False,
        )
        self.assertEqual(
            parse("base.group_system") <= parse("base.group_system,!base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_system") == parse("base.group_system,!base.group_public"),
            True,
        )
        self.assertEqual(
            parse("!base.group_public,!base.group_portal")
            <= parse("!base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_user,!base.group_multi_currency")
            <= parse("base.group_user,!base.group_system,!base.group_multi_currency"),
            False,
        )
        self.assertEqual(
            parse("base.group_system,!base.group_portal,!base.group_public")
            <= parse("base.group_system,!base.group_public"),
            True,
        )

    def test_groups_3_from_ref(self):
        parse = self.parse_repr

        self.assertEqual(
            str(
                parse(
                    "base.group_user & base.group_portal | base.group_user & ~base.group_system"
                )
                & parse("base.group_public")
            ),
            "~*",
        )
        self.assertEqual(
            str(
                parse(
                    "base.group_user & base.group_portal | base.group_user & ~base.group_system"
                )
                & parse("~base.group_user")
            ),
            "~*",
        )
        self.assertEqual(
            str(
                parse(
                    "base.group_user & base.group_portal | base.group_user & ~base.group_system"
                )
                & parse("~base.group_user & base.group_portal")
            ),
            "~*",
        )
        self.assertEqual(
            str(
                parse(
                    "base.group_user & base.group_portal | base.group_user & base.group_system"
                )
                & parse("base.group_user & ~base.group_portal")
            ),
            "'base.group_system'",
        )
        self.assertEqual(
            str(
                parse(
                    "base.group_public & base.group_erp_manager | base.group_public & base.group_portal"
                )
                & parse("*")
            ),
            "~*",
        )
        self.assertEqual(
            str(
                parse("base.group_system & base.group_multi_currency")
                & parse("base.group_portal | base.group_system")
            ),
            "'base.group_system' & 'base.group_multi_currency'",
        )
        self.assertEqual(
            str(
                parse("base.group_portal & base.group_erp_manager")
                | parse("base.group_erp_manager")
            ),
            "'base.group_erp_manager'",
        )
        self.assertEqual(
            parse("base.group_system & base.group_multi_currency")
            < parse("base.group_system"),
            True,
        )
        self.assertEqual(
            parse("base.base_test_group")
            == parse("base.base_test_group & base.group_user"),
            True,
        )
        self.assertEqual(
            parse("base.group_system | base.base_test_group")
            == parse(
                "base.group_system & base.group_user | base.base_test_group & base.group_user"
            ),
            True,
        )
        self.assertEqual(
            parse("base.group_public & base.group_multi_currency")
            <= parse("base.group_public"),
            True,
        )
        self.assertEqual(
            parse("base.group_public")
            <= parse("base.group_public & base.group_multi_currency"),
            False,
        )
        self.assertEqual(
            parse("base.group_public & base.group_user") <= parse("base.group_portal"),
            True,
        )
        self.assertEqual(
            parse("base.group_public & base.group_user")
            <= parse("base.group_public | base.group_user"),
            True,
        )
        self.assertEqual(
            parse("base.group_public & base.group_system") <= parse("base.group_user"),
            True,
        )
        self.assertEqual(
            parse("base.group_public & base.group_system")
            <= parse("base.group_portal | base.group_user"),
            True,
        )
        self.assertEqual(
            parse("base.group_public & base.group_multi_currency")
            <= parse("~base.group_public"),
            False,
        )
        self.assertEqual(
            parse(
                "base.group_portal & base.group_public | base.group_system & base.group_public"
            )
            <= parse("base.group_public"),
            True,
        )
        self.assertEqual(
            parse(
                "base.group_portal & base.group_user | base.group_system & base.group_user"
            )
            <= parse("base.group_user"),
            True,
        )
        self.assertEqual(
            parse(
                "base.group_portal & base.group_system | base.group_user & base.group_system"
            )
            <= parse("base.group_system"),
            True,
        )
        self.assertEqual(
            parse(
                "base.group_portal & base.group_user | base.group_user & base.group_user"
            )
            <= parse("base.group_user"),
            True,
        )
        self.assertEqual(
            parse(
                "base.group_portal & base.group_user | base.group_user & base.group_user"
            )
            <= parse("base.group_user"),
            True,
        )
        self.assertEqual(
            parse("base.group_public")
            <= parse(
                "base.group_portal & base.group_public | base.group_system & base.group_public"
            ),
            False,
        )
        self.assertEqual(
            parse("base.group_user & base.group_multi_currency")
            <= parse("base.group_user & base.group_system & base.group_multi_currency"),
            False,
        )
        self.assertEqual(
            parse("base.group_system & base.group_multi_currency")
            <= parse("base.group_user & base.group_system & base.group_multi_currency"),
            True,
        )
        self.assertEqual(
            parse("base.group_system & base.group_multi_currency")
            <= parse("base.group_system"),
            True,
        )
        self.assertEqual(
            parse("base.group_public")
            >= parse(
                "base.group_portal & base.group_public | base.group_system & base.group_public"
            ),
            True,
        )
        self.assertEqual(
            parse("base.group_user & base.group_public")
            >= parse(
                "base.group_user & base.group_portal & base.group_public | base.group_user & base.group_system & base.group_public"
            ),
            True,
        )
        self.assertEqual(
            parse("base.group_system & base.group_multi_currency")
            >= parse("base.group_system"),
            False,
        )
        self.assertEqual(
            parse("base.group_system & base.group_multi_currency")
            > parse("base.group_system"),
            False,
        )

    def test_groups_4_full_empty(self):
        user_group_ids = self.env.user._get_group_ids()
        self.assertFalse(
            self.definitions.parse("base.group_public").matches(user_group_ids)
        )
        self.assertTrue(self.definitions.parse("*").matches(user_group_ids))
        self.assertFalse((~self.definitions.parse("*")).matches(user_group_ids))

    def test_groups_5_contains_user(self):
        user = self.env["res.users"].create(
            {
                "name": "A User",
                "login": "a_user",
                "email": "a@user.com",
            }
        )

        tests = [
            # group on the user, # groups access, access
            (
                "base.group_public",
                "base.group_system | base.group_public",
                True,
            ),
            (
                "base.group_public,base.group_multi_currency",
                "base.group_user | base.group_public",
                True,
            ),
            (
                "base.group_public",
                "base.group_system & base.group_public",
                False,
            ),
            (
                "base.group_public",
                "base.group_system | base.group_portal",
                False,
            ),
            (
                "base.group_public",
                "base.group_system & base.group_portal",
                False,
            ),
            (
                "base.group_system",
                "base.group_system | base.group_public",
                True,
            ),
            (
                "base.group_system",
                "base.group_system & base.group_public",
                False,
            ),
            ("base.group_system", "base.group_user | base.group_system", True),
            ("base.group_system", "base.group_user & base.group_system", True),
            ("base.group_public", "base.group_user | base.group_system", False),
            ("base.group_public", "base.group_user & base.group_system", False),
            (
                "base.group_system",
                "base.group_system & ~base.group_user",
                False,
            ),
            (
                "base.group_portal",
                "base.group_system & ~base.group_user",
                False,
            ),
            ("base.group_user", "base.group_user & ~base.group_system", True),
            ("base.group_user", "~base.group_system & base.group_user", True),
            (
                "base.group_system",
                "base.group_user & ~base.group_system",
                False,
            ),
            ("base.group_portal", "base.group_portal & ~base.group_user", True),
            (
                "base.group_system",
                "~base.group_system & base.group_user",
                False,
            ),
            (
                "base.group_system",
                "~base.group_system & ~base.group_user",
                False,
            ),
            (
                "base.group_user",
                "base.group_user & base.group_sanitize_override & base.group_multi_currency",
                False,
            ),
            (
                "base.group_system",
                "base.group_user & base.group_sanitize_override & base.group_multi_currency",
                False,
            ),
            (
                "base.group_system,base.group_multi_currency",
                "base.group_user & base.group_sanitize_override & base.group_multi_currency",
                True,
            ),
            (
                "base.group_user,base.group_sanitize_override,base.group_multi_currency",
                "base.group_user & base.group_sanitize_override & base.group_multi_currency",
                True,
            ),
            (
                "base.group_user",
                "base.group_erp_manager | base.group_multi_company",
                False,
            ),
            (
                "base.group_user,base.group_erp_manager",
                "base.group_erp_manager | base.group_multi_company",
                True,
            ),
        ]
        for user_groups, groups, result in tests:
            user.group_ids = [
                (
                    6,
                    0,
                    [self.env.ref(xmlid).id for xmlid in user_groups.split(",")],
                )
            ]
            self.assertEqual(
                self.parse_repr(groups).matches(user._get_group_ids()),
                result,
                f"User ({user_groups!r}) should {'' if result else 'not '}have access to groups: ({groups!r})",
            )

    def test_groups_6_distinct(self):
        user = self.env["res.users"].create(
            {
                "name": "A User",
                "login": "a_user",
                "email": "a@user.com",
                "group_ids": self.env.ref("base.group_user").ids,
            }
        )

        # update res.users groups with distinct groups
        with self.assertRaises(
            ValidationError,
            msg="The user cannot have more than one user types.",
        ):
            user.group_ids = [(4, self.env.ref("base.group_public").id)]
        with self.assertRaises(
            ValidationError,
            msg="The user cannot have more than one user types.",
        ):
            user.group_ids = [(4, self.env.ref("base.group_portal").id)]

        user.group_ids = self.env.ref("base.group_user") + self.test_group

        # update res.group implied_ids having the effect that users have distinct groups
        with self.assertRaises(
            ValidationError,
            msg="The user cannot have more than one user types.",
        ):
            self.test_group.implied_ids += self.env.ref("base.group_public")
        with self.assertRaises(
            ValidationError,
            msg="The user cannot have more than one user types.",
        ):
            self.env.ref("base.group_public").implied_by_ids = self.test_group

        # this works because public user is inactive
        self.env.ref("base.group_public").implied_ids += self.test_group


@common.tagged("post_install", "-at_install", "groups")
class TestGroupsCacheInvalidation(common.TransactionCase):
    """The cached `groups` family (res.groups._get_view_group_hierarchy) must be
    invalidated when group or privilege metadata feeding it changes.

    RG-L1 (group rename) / RG-L2 (privilege edit): the cache was previously
    busted only on implied_ids/implied_by_ids changes, serving a stale hierarchy.
    """

    def setUp(self):
        super().setUp()
        # The `groups` cache is registry-wide and not rolled back with the
        # transaction; clear it so rolled-back records do not linger.
        self.addCleanup(self.env.registry.clear_cache, "groups")

    def test_group_rename_invalidates_view_group_hierarchy(self):
        Groups = self.env["res.groups"]
        group = Groups.create({"name": "Audit RG-L1 Group"})
        hierarchy = Groups._get_view_group_hierarchy()
        self.assertEqual(hierarchy["groups"][group.id]["name"], "Audit RG-L1 Group")

        group.write({"name": "Audit RG-L1 Renamed"})

        hierarchy = Groups._get_view_group_hierarchy()
        self.assertEqual(
            hierarchy["groups"][group.id]["name"],
            "Audit RG-L1 Renamed",
            "view_group_hierarchy served a stale group name (cache not invalidated)",
        )

    def test_privilege_edit_invalidates_view_group_hierarchy(self):
        Groups = self.env["res.groups"]
        privilege = self.env["res.groups.privilege"].create({"name": "Audit RG-L2"})
        Groups.create({"name": "Audit RG-L2 Group", "privilege_id": privilege.id})
        hierarchy = Groups._get_view_group_hierarchy()
        self.assertEqual(hierarchy["privileges"][privilege.id]["name"], "Audit RG-L2")

        privilege.write({"name": "Audit RG-L2 Renamed"})

        hierarchy = Groups._get_view_group_hierarchy()
        self.assertEqual(
            hierarchy["privileges"][privilege.id]["name"],
            "Audit RG-L2 Renamed",
            "view_group_hierarchy served a stale privilege name (cache not invalidated)",
        )

    def test_unlink_invalidates_default_group_cache(self):
        """RG-T1: res.groups.unlink must bust the `default`-family caches
        (res.users._get_group_ids) so a deleted group's id is not left stale in
        a user who held it.
        """
        Groups = self.env["res.groups"]
        group = Groups.create({"name": "Audit RG-T1 Group"})
        user = self.env["res.users"].create(
            {
                "name": "Audit RG-T1 User",
                "login": "audit_rg_t1_user",
                "group_ids": [Command.link(self.env.ref("base.group_user").id)],
            }
        )
        user.group_ids += group

        # Warm the @ormcache (default family); the group must be present.
        self.assertIn(
            group.id,
            user._get_group_ids(),
            "precondition: warmed _get_group_ids must contain the group id",
        )

        group.unlink()

        # No intervening default-flushing op: the unlink override itself must
        # have busted the `default` family.
        self.assertNotIn(
            group.id,
            user._get_group_ids(),
            "unlink left the deleted group id stale in _get_group_ids "
            "(default-family cache not invalidated)",
        )

    def test_is_feature_enabled(self):
        """RG-T2: _is_feature_enabled is True iff the feature group is
        transitively implied by base.group_user, False for a standalone group
        and for an unknown reference.
        """
        Groups = self.env["res.groups"]

        # _is_feature_enabled checks PROPER implication by group_user (a group
        # never implies itself), so the feature needs its own external id.
        feature = Groups.create({"name": "Audit RG-T2 Feature"})
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "audit_rg_t2_feature",
                "model": "res.groups",
                "res_id": feature.id,
            }
        )
        self.env.ref("base.group_user").implied_ids += feature
        self.assertTrue(
            Groups._is_feature_enabled("base.audit_rg_t2_feature"),
            "a feature group implied by group_user is enabled for all internal users",
        )

        # A standalone group that nothing implies is not a global feature.
        standalone = Groups.create({"name": "Audit RG-T2 Standalone"})
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "audit_rg_t2_standalone",
                "model": "res.groups",
                "res_id": standalone.id,
            }
        )
        self.assertFalse(
            Groups._is_feature_enabled("base.audit_rg_t2_standalone"),
            "a standalone group not implied by group_user must be disabled",
        )

        # An unknown reference resolves to no feature id.
        self.assertFalse(
            Groups._is_feature_enabled("base.this_group_does_not_exist"),
            "an unknown group reference must return False",
        )

    def test_privilege_create_unlink_invalidates_view_group_hierarchy(self):
        """RGP-T1: privilege create and unlink must bust the `groups` family so
        the cached view_group_hierarchy reflects the privilege set.
        """
        Groups = self.env["res.groups"]
        Privilege = self.env["res.groups.privilege"]

        # Warm, then create: the privilege must appear.
        Groups._get_view_group_hierarchy()
        privilege = Privilege.create({"name": "Audit RGP-T1"})
        hierarchy = Groups._get_view_group_hierarchy()
        self.assertIn(
            privilege.id,
            hierarchy["privileges"],
            "create did not invalidate the groups-family view_group_hierarchy",
        )

        # Warm again, then unlink: the privilege must disappear.
        Groups._get_view_group_hierarchy()
        privilege_id = privilege.id
        privilege.unlink()
        hierarchy = Groups._get_view_group_hierarchy()
        self.assertNotIn(
            privilege_id,
            hierarchy["privileges"],
            "unlink did not invalidate the groups-family view_group_hierarchy",
        )


class TestAllUsersCount(common.TransactionCase):
    """all_users_count computed via search_count (RG-P2).

    The count must not materialize the whole implied-user population into the ORM
    cache, and must keep matching len(all_user_ids) under the caller's active_test
    (archived users are filtered out at access time in the default context).
    """

    def test_count_includes_implied_users(self):
        Groups = self.env["res.groups"]
        group_base = Groups.create({"name": "auc base"})
        group_implying = Groups.create(
            {
                "name": "auc implying",
                "implied_ids": [Command.link(group_base.id)],
            }
        )
        Users = self.env["res.users"]
        Users.create(
            {
                "name": "auc direct",
                "login": "auc_direct",
                "group_ids": [Command.link(group_base.id)],
            }
        )
        Users.create(
            {
                "name": "auc implied",
                "login": "auc_implied",
                "group_ids": [Command.link(group_implying.id)],
            }
        )
        Users.create(
            {
                "name": "auc archived",
                "login": "auc_archived",
                "active": False,
                "group_ids": [Command.link(group_implying.id)],
            }
        )
        # Default context: archived members excluded, like len(all_user_ids).
        self.assertEqual(group_base.all_users_count, 2)
        self.assertEqual(group_implying.all_users_count, 1)
        self.assertEqual(
            group_base.all_users_count,
            len(group_base.all_user_ids),
            "the count must match the relational field it no longer reads",
        )
        self.assertEqual(
            group_implying.all_users_count, len(group_implying.all_user_ids)
        )
        # active_test=False context: archived members included, like the
        # relational read (invalidate first: the non-stored integer cache is
        # context-independent).
        self.env.invalidate_all()
        base_no_active_test = group_base.with_context(active_test=False)
        implying_no_active_test = group_implying.with_context(active_test=False)
        self.assertEqual(base_no_active_test.all_users_count, 3)
        self.assertEqual(implying_no_active_test.all_users_count, 2)
        self.assertEqual(
            base_no_active_test.all_users_count,
            len(base_no_active_test.all_user_ids),
        )
        self.assertEqual(
            implying_no_active_test.all_users_count,
            len(implying_no_active_test.all_user_ids),
        )


class TestPrivilegeGroupSorting(common.TransactionCase):
    """_sorted_privilege_group_ids precomputes the implication counts (RG-P3).

    Order contract: by number of the privilege's groups each group implies (self
    included), then sequence, then id.
    """

    def test_sorted_by_implication_depth_then_sequence(self):
        privilege = self.env["res.groups.privilege"].create({"name": "sort priv"})
        Groups = self.env["res.groups"]
        g1 = Groups.create(
            {"name": "priv g1", "privilege_id": privilege.id, "sequence": 5}
        )
        g2 = Groups.create(
            {
                "name": "priv g2",
                "privilege_id": privilege.id,
                "sequence": 3,
                "implied_ids": [Command.link(g1.id)],
            }
        )
        g3 = Groups.create(
            {
                "name": "priv g3",
                "privilege_id": privilege.id,
                "sequence": 4,
                "implied_ids": [Command.link(g2.id)],
            }
        )
        result = Groups._sorted_privilege_group_ids(privilege)
        # implication counts (self included): g1 -> 1, g2 -> 2, g3 -> 3
        self.assertEqual(result, [g1.id, g2.id, g3.id])
        # same-count groups fall back to sequence: give g3 its own privilege
        # so g2/g1 stay, then equalize counts via a fresh pair
        ga = Groups.create(
            {"name": "priv ga", "privilege_id": privilege.id, "sequence": 9}
        )
        gb = Groups.create(
            {"name": "priv gb", "privilege_id": privilege.id, "sequence": 1}
        )
        result = Groups._sorted_privilege_group_ids(privilege)
        # ga/gb imply only themselves (count 1, like g1): sequence decides
        self.assertEqual(result, [gb.id, g1.id, ga.id, g2.id, g3.id])
        # the hierarchy consumed by the web client uses the helper's order
        hierarchy = Groups._get_view_group_hierarchy()
        self.assertEqual(hierarchy["privileges"][privilege.id]["group_ids"], result)
