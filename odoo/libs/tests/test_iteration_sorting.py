import unittest

from odoo.libs.iteration.sorting import merge_sequences, topological_sort


class TestMergeSequencesDocumentedExample(unittest.TestCase):
    def test_worked_example(self):
        self.assertEqual(
            merge_sequences(
                ["A", "B", "C"],
                ["Z"],
                ["Y", "C"],
                ["A", "X", "Y"],
            ),
            ["A", "B", "X", "Y", "C", "Z"],
        )

    def test_single_sequence_is_identity(self):
        self.assertEqual(merge_sequences(["A", "B", "C"]), ["A", "B", "C"])

    def test_no_arguments(self):
        self.assertEqual(merge_sequences(), [])


class TestMergeSequencesConflicts(unittest.TestCase):
    def test_not_first_wins(self):
        self.assertEqual(merge_sequences(["a", "b"], ["b", "a"]), ["b", "a"])

    def test_symmetric_case_confirms_it_is_not_last_wins_either(self):
        self.assertEqual(merge_sequences(["b", "a"], ["a", "b"]), ["a", "b"])

    def test_deterministic(self):
        args = (["x", "y"], ["y", "x"], ["x", "y"])
        self.assertEqual(merge_sequences(*args), merge_sequences(*args))

    def test_conflict_never_raises(self):
        merge_sequences(["a", "b", "c"], ["c", "b", "a"])

    def test_all_elements_survive(self):
        result = merge_sequences(["a", "b"], ["b", "a"], ["c"])
        self.assertEqual(sorted(result), ["a", "b", "c"])


class TestTopologicalSortStrictness(unittest.TestCase):
    def test_cycle_raises_by_default(self):
        with self.assertRaises(ValueError):
            topological_sort({"a": ["b"], "b": ["a"]})

    def test_cycle_tolerated_when_not_strict(self):
        self.assertEqual(
            sorted(topological_sort({"a": ["b"], "b": ["a"]}, strict=False)), ["a", "b"]
        )

    def test_self_edge_is_not_a_cycle(self):
        self.assertEqual(topological_sort({"base": ["base"]}), ["base"])

    def test_dependency_absent_from_elems_is_never_emitted(self):
        self.assertEqual(topological_sort({"a": ["ghost"]}), ["a"])

    def test_deep_chain_does_not_blow_the_stack(self):
        depth = 50_000
        elems = {i: [i + 1] for i in range(depth)} | {depth: []}
        self.assertEqual(len(topological_sort(elems)), depth + 1)


if __name__ == "__main__":
    unittest.main()
