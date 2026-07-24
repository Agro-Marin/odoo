"""Contract tests for ``topological_sort`` / ``merge_sequences``.

The two share an implementation but not a contract, and the difference is the
whole point of the ``strict`` flag: a dependency graph with a cycle is bad data
and should say so, while merging partial orders is best-effort and a conflict is
routine. Pinning both directions here because collapsing them is an easy and
very expensive mistake -- ``merge_sequences`` runs during registry build.
"""

import unittest

from odoo.libs.iteration.sorting import merge_sequences, topological_sort


class TestTopologicalSort(unittest.TestCase):
    def _assert_ordered(self, elems, result):
        pos = {v: i for i, v in enumerate(result)}
        self.assertEqual(set(result), set(elems))
        for node, deps in elems.items():
            for dep in deps:
                if dep in pos and dep != node:
                    self.assertLess(pos[dep], pos[node], f"{dep} must precede {node}")

    def test_dependencies_precede(self):
        elems = {"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}
        self._assert_ordered(elems, topological_sort(elems))

    def test_dependency_absent_from_elems_is_not_emitted(self):
        self.assertEqual(topological_sort({"a": ["ghost"]}), ["a"])

    def test_self_edge_is_ignored(self):
        # a manifest without "depends" defaults to ["base"], so base depends on
        # itself; that is degenerate, not a cycle
        self.assertEqual(topological_sort({"base": ["base"]}), ["base"])

    def test_cycle_raises_by_default(self):
        with self.assertRaises(ValueError):
            topological_sort({"a": ["b"], "b": ["a"]})
        with self.assertRaises(ValueError):
            topological_sort({"a": ["b"], "b": ["c"], "c": ["a"]})

    def test_cycle_tolerated_when_not_strict(self):
        # back-edge dropped, every element still emitted exactly once
        for elems in ({"a": ["b"], "b": ["a"]}, {"a": ["b"], "b": ["c"], "c": ["a"]}):
            result = topological_sort(elems, strict=False)
            self.assertCountEqual(result, elems)

    def test_deep_chain_does_not_exhaust_the_stack(self):
        # the recursive implementation this replaced died with RecursionError
        # well before this depth; a dependency chain is data-shaped, not bounded
        depth = 10_000
        elems = {i: [i + 1] for i in range(depth)}
        elems[depth] = []
        self.assertEqual(topological_sort(elems)[0], depth)


class TestMergeSequences(unittest.TestCase):
    def test_documented_example(self):
        seq = merge_sequences(
            ["A", "B", "C"],
            ["Z"],
            ["Y", "C"],
            ["A", "X", "Y"],
        )
        self.assertEqual(seq, ["A", "B", "X", "Y", "C", "Z"])

    def test_single_sequence_is_preserved(self):
        self.assertEqual(merge_sequences(["A", "B", "C"]), ["A", "B", "C"])

    def test_contradictory_orders_do_not_raise(self):
        """A module reordering existing selection values must not kill the registry.

        ``Selection._setup`` merges ``selection`` with ``selection_add`` through
        here while the registry is being built, so raising on a conflict would
        turn a cosmetic manifest quirk into a server that will not start.
        """
        seq = merge_sequences(["a", "b", "c"], ["c", "b"])
        self.assertCountEqual(seq, ["a", "b", "c"])

    def test_duplicate_sequences_are_idempotent(self):
        self.assertEqual(merge_sequences(["a", "b"], ["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
