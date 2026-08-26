import unittest
from datetime import datetime
from typing import cast

from odoo.libs.intervals import Intervals, intervals_overlap, invert_intervals


class Recordset:
    def __init__(self, model, ids):
        self.model = model
        self.ids = frozenset(ids)

    def _compare(self, other, op):
        if not isinstance(other, Recordset) or self.model != other.model:
            return NotImplemented
        return op(self.ids, other.ids)

    def __lt__(self, other):
        return self._compare(other, lambda a, b: a < b)

    def __gt__(self, other):
        return self._compare(other, lambda a, b: a > b)

    def union(self, other):
        if self.model != other.model:
            raise TypeError(f"inconsistent models: {self.model} | {other.model}")
        return Recordset(self.model, self.ids | other.ids)

    def __repr__(self):
        return f"{self.model}{sorted(self.ids)}"


class TestIntervalsSemantics(unittest.TestCase):
    def _plain(self, triples, **kw):
        return [
            (s, e, sorted(cast("set[str]", r))) for s, e, r in Intervals(triples, **kw)
        ]

    def test_adjacent_merged_by_default(self):
        self.assertEqual(
            self._plain([(1, 3, {"a"}), (3, 5, {"b"})]),
            [(1, 5, ["a", "b"])],
        )

    def test_overlapping_merged_and_records_unioned(self):
        self.assertEqual(
            self._plain([(0, 5, {"a"}), (2, 8, {"b"})]),
            [(0, 8, ["a", "b"])],
        )

    def test_disjoint_kept_apart(self):
        self.assertEqual(
            self._plain([(0, 2, {"a"}), (5, 7, {"b"})]),
            [(0, 2, ["a"]), (5, 7, ["b"])],
        )

    def test_adjacent_kept_when_distinct(self):
        self.assertEqual(
            self._plain([(1, 3, {"a"}), (3, 5, {"b"})], keep_distinct=True),
            [(1, 3, ["a"]), (3, 5, ["b"])],
        )

    def test_degenerate_intervals_dropped(self):
        self.assertEqual(self._plain([(4, 4, {"a"}), (1, 2, {"b"})]), [(1, 2, ["b"])])

    def test_inverted_interval_dropped(self):
        self.assertEqual(self._plain([(9, 1, {"a"})]), [])

    def test_result_is_independent_of_input_order(self):
        triples = [(0, 5, {"a"}), (7, 9, {"b"}), (2, 8, {"c"})]
        expected = self._plain(triples)
        for rotation in range(len(triples)):
            rotated = triples[rotation:] + triples[:rotation]
            self.assertEqual(self._plain(rotated), expected)

    def test_union_intersection_difference(self):
        left = Intervals([(0, 10, {"a"})])
        right = Intervals([(5, 15, {"b"})])
        self.assertEqual([(s, e) for s, e, _ in left | right], [(0, 15)])
        self.assertEqual([(s, e) for s, e, _ in left & right], [(5, 10)])
        self.assertEqual([(s, e) for s, e, _ in left - right], [(0, 5)])

    def test_difference_can_split_an_interval(self):
        left = Intervals([(0, 10, {"a"})])
        self.assertEqual(
            [(s, e) for s, e, _ in left - Intervals([(4, 6, {"b"})])],
            [(0, 4), (6, 10)],
        )

    def test_operations_preserve_keep_distinct(self):
        left = Intervals([(0, 3, {"a"})], keep_distinct=True)
        merged = left | Intervals([(3, 6, {"b"})], keep_distinct=True)
        self.assertEqual([(s, e) for s, e, _ in merged], [(0, 3), (3, 6)])

    def test_empty(self):
        self.assertFalse(Intervals())
        self.assertEqual(len(Intervals()), 0)
        self.assertEqual(list(Intervals(None)), [])

    def test_bool_len_iter_reversed(self):
        intervals = Intervals([(0, 1, {"a"}), (2, 3, {"b"})])
        self.assertTrue(intervals)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(
            [s for s, _, _ in reversed(intervals)],
            [s for s, _, _ in reversed(list(intervals))],
        )

    def test_constructor_accepts_an_iterator(self):
        self.assertEqual(
            [(s, e) for s, e, _ in Intervals(iter([(0, 2, {"a"})]))], [(0, 2)]
        )


class TestPayloadParticipatesInOrdering(unittest.TestCase):
    def test_cross_model_payload_is_rejected(self):
        with self.assertRaises(TypeError):
            Intervals(
                [(0, 10, Recordset("a", [1])), (0, 5, Recordset("b", [2]))],
            )

    def test_cross_model_union_is_rejected(self):
        left = Intervals([(0, 10, Recordset("a", [1]))])
        right = Intervals([(5, 15, Recordset("b", [2]))])
        with self.assertRaises(TypeError):
            left | right

    def test_single_model_tied_boundaries_are_fine(self):
        result = Intervals(
            [(0, 10, Recordset("a", [1])), (0, 5, Recordset("a", [2]))],
        )
        self.assertEqual([(s, e) for s, e, _ in result], [(0, 10)])
        payload = cast("Recordset", next(iter(result))[2])
        self.assertEqual(payload.ids, frozenset({1, 2}))

    def test_merge_never_compares_payloads(self):

        class Exploding(Recordset):
            def __lt__(self, other):
                raise AssertionError("payload compared during _merge")

            __gt__ = __lt__

        left = Intervals([(0, 10, Exploding("a", [1]))])
        right = [(2, 4, Exploding("a", [2])), (6, 8, Exploding("a", [3]))]
        self.assertEqual(
            [(s, e) for s, e, _ in left - right], [(0, 2), (4, 6), (8, 10)]
        )


class TestHelpers(unittest.TestCase):
    def test_overlap(self):
        self.assertTrue(intervals_overlap((0, 5), (4, 9)))
        self.assertFalse(intervals_overlap((0, 5), (5, 9)))
        self.assertFalse(intervals_overlap((0, 5), (6, 9)))

    def test_invert(self):
        self.assertEqual(
            invert_intervals([(1, 2), (4, 5)], 0, 10),
            [(0, 1), (2, 4), (5, 10)],
        )

    def test_invert_with_overlapping_input(self):
        self.assertEqual(invert_intervals([(1, 4), (2, 6)], 0, 10), [(0, 1), (6, 10)])

    def test_invert_empty(self):
        self.assertEqual(invert_intervals([], 0, 10), [(0, 10)])

    def test_invert_full_cover(self):
        self.assertEqual(invert_intervals([(0, 10)], 0, 10), [])

    def test_invert_merges_gaps_a_zero_length_interval_splits(self):
        """A degenerate input must not split one gap into two touching ones.

        `(4, 4)` moves nothing, so the accumulator emits `(0, 4)` and then
        `(4, 10)`.  They are adjacent, and the result has to be `(0, 10)`.
        This is the case the `Intervals` round trip used to cover; it is why
        the replacement merges rather than just filtering empties.
        """
        self.assertEqual(invert_intervals([(4, 4)], 0, 10), [(0, 10)])
        self.assertEqual(invert_intervals([(2, 2), (5, 5)], 0, 10), [(0, 10)])

    def test_invert_drops_empty_gaps(self):
        self.assertEqual(invert_intervals([(0, 5), (5, 10)], 0, 10), [])

    def test_invert_with_touching_inputs_keeps_the_outer_gaps(self):
        self.assertEqual(invert_intervals([(2, 4), (4, 6)], 0, 10), [(0, 2), (6, 10)])

    def test_invert_empty_range(self):
        self.assertEqual(invert_intervals([], 5, 5), [])
        self.assertEqual(invert_intervals([(1, 2)], 5, 5), [])


class _IntervalAlgebra:
    """The exhaustive union/intersection/difference tables, ported from
    `odoo/addons/base/tests/test_intervals.py`.

    They lived in a `TransactionCase` whose only use of the database was
    `self.env["base"]` as an inert payload -- a `createdb` plus a full `base`
    install to obtain an empty recordset that the algebra never inspects. A
    payload only has to supply `.union`, so a `frozenset` does the same job here
    in the DB-free tier.

    `keep_distinct` used to be a second class holding a second copy of these
    tables. `test_intersection` and `test_difference` were byte-identical
    between the two -- 26 rows where 13 and a parameter do.
    """

    keep_distinct = False

    def ints(self, pairs):
        return [(a, b, frozenset()) for a, b in pairs]

    def _intervals(self, pairs):
        return Intervals(self.ints(pairs), keep_distinct=self.keep_distinct)

    def test_intersection(self):
        def check(a, b, c):
            with self.subTest(a=a, b=b, keep_distinct=self.keep_distinct):
                self.assertEqual(
                    list(self._intervals(a) & self._intervals(b)), self.ints(c)
                )

        check([(10, 20)], [(5, 8)], [])
        check([(10, 20)], [(5, 10)], [])
        check([(10, 20)], [(5, 15)], [(10, 15)])
        check([(10, 20)], [(5, 20)], [(10, 20)])
        check([(10, 20)], [(5, 25)], [(10, 20)])
        check([(10, 20)], [(10, 15)], [(10, 15)])
        check([(10, 20)], [(10, 20)], [(10, 20)])
        check([(10, 20)], [(10, 25)], [(10, 20)])
        check([(10, 20)], [(15, 18)], [(15, 18)])
        check([(10, 20)], [(15, 20)], [(15, 20)])
        check([(10, 20)], [(15, 25)], [(15, 20)])
        check([(10, 20)], [(20, 25)], [])
        check(
            [(0, 5), (10, 15), (20, 25), (30, 35)],
            [(6, 7), (9, 12), (13, 17), (22, 23), (24, 40)],
            [(10, 12), (13, 15), (22, 23), (24, 25), (30, 35)],
        )

    def test_difference(self):
        def check(a, b, c):
            with self.subTest(a=a, b=b, keep_distinct=self.keep_distinct):
                self.assertEqual(
                    list(self._intervals(a) - self._intervals(b)), self.ints(c)
                )

        check([(10, 20)], [(5, 8)], [(10, 20)])
        check([(10, 20)], [(5, 10)], [(10, 20)])
        check([(10, 20)], [(5, 15)], [(15, 20)])
        check([(10, 20)], [(5, 20)], [])
        check([(10, 20)], [(5, 25)], [])
        check([(10, 20)], [(10, 15)], [(15, 20)])
        check([(10, 20)], [(10, 20)], [])
        check([(10, 20)], [(10, 25)], [])
        check([(10, 20)], [(15, 18)], [(10, 15), (18, 20)])
        check([(10, 20)], [(15, 20)], [(10, 15)])
        check([(10, 20)], [(15, 25)], [(10, 15)])
        check([(10, 20)], [(20, 25)], [(10, 20)])
        check(
            [(0, 5), (10, 15), (20, 25), (30, 35)],
            [(6, 7), (9, 12), (13, 17), (22, 23), (24, 40)],
            [(0, 5), (12, 13), (20, 22), (23, 24)],
        )


class TestIntervalAlgebraMerging(_IntervalAlgebra, unittest.TestCase):
    keep_distinct = False

    def test_union(self):
        def check(a, b):
            with self.subTest(a=a):
                self.assertEqual(list(self._intervals(a)), self.ints(b))

        check([(1, 2), (3, 4)], [(1, 2), (3, 4)])
        check([(1, 2), (2, 4)], [(1, 4)])
        check([(1, 3), (2, 4)], [(1, 4)])
        check([(1, 4), (2, 3)], [(1, 4)])
        check([(3, 4), (1, 2)], [(1, 2), (3, 4)])
        check([(2, 4), (1, 2)], [(1, 4)])
        check([(2, 4), (1, 3)], [(1, 4)])
        check([(2, 3), (1, 4)], [(1, 4)])


class TestIntervalAlgebraKeepDistinct(_IntervalAlgebra, unittest.TestCase):
    keep_distinct = True

    def test_union(self):
        def check(a, b):
            with self.subTest(a=a):
                self.assertEqual(list(self._intervals(a)), self.ints(b))

        check([(1, 2), (3, 4)], [(1, 2), (3, 4)])
        check([(1, 2), (2, 4)], [(1, 2), (2, 4)])
        check([(1, 3), (2, 4)], [(1, 4)])
        check([(1, 4), (2, 3)], [(1, 4)])
        check([(1, 4), (1, 4)], [(1, 4)])
        check([(3, 4), (1, 2)], [(1, 2), (3, 4)])
        check([(2, 4), (1, 2)], [(1, 2), (2, 4)])
        check([(2, 4), (1, 3)], [(1, 4)])
        check([(2, 3), (1, 4)], [(1, 4)])

    def test_an_operand_that_keeps_distinct_does_not_infect_one_that_merges(self):
        merging = Intervals(self.ints([(0, 10)]), keep_distinct=False)
        distinct = Intervals(self.ints([(-5, 5), (5, 15)]), keep_distinct=True)

        intersection = merging & distinct
        self.assertFalse(intersection._keep_distinct)
        self.assertEqual(len(intersection), 1)
        self.assertEqual(list(intersection), self.ints([(0, 10)]))

        intersection -= Intervals()
        self.assertFalse(intersection._keep_distinct)
        self.assertEqual(intersection._items, self.ints([(0, 10)]))


class TestHelperMatrices(unittest.TestCase):
    """The datetime tables from `base/tests/test_intervals.py::TestUtils`.

    `TestHelpers` above covers the same two helpers qualitatively; these are the
    exhaustive cases, and they never needed a database either.
    """

    def test_intervals_intersections(self):
        test_data = [
            (
                (datetime(2023, 2, 14), datetime(2023, 2, 15)),
                (datetime(2023, 2, 15), datetime(2023, 2, 16)),
                False,
            ),
            (
                (datetime(2023, 2, 14), datetime(2023, 2, 15)),
                (datetime(2023, 2, 13), datetime(2023, 2, 16)),
                True,
            ),
            (
                (datetime(2023, 2, 13), datetime(2023, 2, 16)),
                (datetime(2023, 2, 14), datetime(2023, 2, 15)),
                True,
            ),
            (
                (datetime(2023, 2, 13), datetime(2023, 2, 16)),
                (datetime(2023, 2, 15), datetime(2023, 2, 17)),
                True,
            ),
        ]
        for interval_a, interval_b, overlaps in test_data:
            with self.subTest(interval_a=interval_a, interval_b=interval_b):
                self.assertEqual(intervals_overlap(interval_a, interval_b), overlaps)

    def test_intervals_inversion(self):
        test_intervals = [
            (datetime(2023, 2, 5), datetime(2023, 2, 6)),
            (datetime(2023, 2, 7), datetime(2023, 2, 7)),
            (datetime(2023, 2, 9), datetime(2023, 2, 10)),
            (datetime(2023, 2, 10), datetime(2023, 2, 11)),
            (datetime(2023, 2, 11), datetime(2023, 2, 12)),
            (datetime(2023, 2, 13), datetime(2023, 2, 15)),
            (datetime(2023, 2, 14), datetime(2023, 2, 18)),
            (
                datetime(2023, 2, 15),
                datetime(2023, 2, 16),
            ),
            (
                datetime(2023, 2, 25),
                datetime(2023, 3, 10),
            ),
            (datetime(2023, 2, 20), datetime(2023, 2, 22)),
        ]
        test_limits = [
            (datetime(2023, 1, 1), datetime(2023, 4, 1)),
            (
                datetime(2023, 2, 5),
                datetime(2023, 3, 10),
            ),
            (
                datetime(2023, 2, 9),
                datetime(2023, 2, 12),
            ),
            (
                datetime(2023, 2, 6),
                datetime(2023, 2, 9),
            ),
            (datetime(2023, 2, 8), datetime(2023, 2, 11)),
        ]
        test_results = [
            [
                (datetime(2023, 1, 1), datetime(2023, 2, 5)),
                (datetime(2023, 2, 6), datetime(2023, 2, 9)),
                (datetime(2023, 2, 12), datetime(2023, 2, 13)),
                (datetime(2023, 2, 18), datetime(2023, 2, 20)),
                (datetime(2023, 2, 22), datetime(2023, 2, 25)),
                (datetime(2023, 3, 10), datetime(2023, 4, 1)),
            ],
            [
                (datetime(2023, 2, 6), datetime(2023, 2, 9)),
                (datetime(2023, 2, 12), datetime(2023, 2, 13)),
                (datetime(2023, 2, 18), datetime(2023, 2, 20)),
                (datetime(2023, 2, 22), datetime(2023, 2, 25)),
            ],
            [],
            [
                (datetime(2023, 2, 6), datetime(2023, 2, 9)),
            ],
            [
                (datetime(2023, 2, 8), datetime(2023, 2, 9)),
            ],
        ]
        for limits, expected_result in zip(test_limits, test_results, strict=False):
            start, end = limits
            with self.subTest(start=start, end=end):
                self.assertListEqual(
                    invert_intervals(test_intervals, start, end),
                    expected_result,
                )


if __name__ == "__main__":
    unittest.main()
