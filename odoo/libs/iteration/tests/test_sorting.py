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
        self.assertEqual(topological_sort({"base": ["base"]}), ["base"])

    def test_cycle_raises_by_default(self):
        with self.assertRaises(ValueError):
            topological_sort({"a": ["b"], "b": ["a"]})
        with self.assertRaises(ValueError):
            topological_sort({"a": ["b"], "b": ["c"], "c": ["a"]})

    def test_cycle_tolerated_when_not_strict(self):
        for elems in ({"a": ["b"], "b": ["a"]}, {"a": ["b"], "b": ["c"], "c": ["a"]}):
            result = topological_sort(elems, strict=False)
            self.assertCountEqual(result, elems)

    def test_deep_chain_does_not_exhaust_the_stack(self):
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
        seq = merge_sequences(["a", "b", "c"], ["c", "b"])
        self.assertCountEqual(seq, ["a", "b", "c"])

    def test_duplicate_sequences_are_idempotent(self):
        self.assertEqual(merge_sequences(["a", "b"], ["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
