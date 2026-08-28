import tempfile
import textwrap
import unittest
from pathlib import Path

import py_count_as_boolean as pcb


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _measure(self, body: str):
        path = self.tmp / "a.py"
        path.write_text(textwrap.dedent(body))
        return pcb.measure([path])

    def test_an_if_test_is_reported(self):
        found = self._measure("if self.search_count(domain):\n    pass\n")
        self.assertEqual([f.kind for f in found], ["if"])

    def test_not_is_reported(self):
        found = self._measure("x = not self.search_count(domain)\n")
        self.assertEqual([f.kind for f in found], ["not"])

    def test_bool_is_reported(self):
        found = self._measure("x = bool(self.search_count(domain))\n")
        self.assertEqual([f.kind for f in found], ["bool()"])

    def test_a_comparison_against_zero_is_reported_either_way_round(self):
        for source in (
            "x = self.search_count(d) == 0\n",
            "x = self.search_count(d) > 0\n",
            "x = 0 < self.search_count(d)\n",
            "x = self.search_count(d) != 0\n",
        ):
            with self.subTest(source=source.strip()):
                self.assertEqual([f.kind for f in self._measure(source)], ["vs 0"])

    def test_a_conditional_expression_is_reported(self):
        found = self._measure("x = 'y' if self.search_count(d) else 'n'\n")
        self.assertEqual(len(found), 1)

    def test_not_inside_a_larger_boolean_is_still_reported(self):
        found = self._measure("x = a and not self.search_count(d)\n")
        self.assertEqual([f.kind for f in found], ["not"])

    def test_a_boolean_expression_that_is_only_a_condition_is_reported(self):
        found = self._measure("if item and self.search_count(d):\n    pass\n")
        self.assertEqual([f.kind for f in found], ["if"])

    def test_a_chain_of_boolean_operators_is_walked_through(self):
        found = self._measure("if a and b and not self.search_count(d):\n    pass\n")
        self.assertEqual(len(found), 1)

    def test_a_limit_already_there_is_the_fixed_form(self):
        self.assertEqual(
            self._measure("if self.search_count(d, limit=1):\n    pass\n"), []
        )

    def test_a_positional_limit_counts_as_a_limit(self):
        self.assertEqual(self._measure("if self.search_count(d, 1):\n    pass\n"), [])

    def test_a_count_used_for_its_number_is_not_reported(self):
        self.assertEqual(self._measure("record.n = self.search_count(d)\n"), [])

    def test_a_comparison_against_something_other_than_zero_is_not_reported(self):
        self.assertEqual(self._measure("x = self.search_count(d) > 5\n"), [])

    def test_a_boolean_expression_whose_value_escapes_is_not_reported(self):
        self.assertEqual(self._measure("x = vals and self.search_count(d)\n"), [])
        self.assertEqual(self._measure("return vals and self.search_count(d)\n"), [])

    def test_a_test_file_is_out_of_scope(self):
        (self.tmp / "test_thing.py").write_text("if self.search_count(d):\n    pass\n")
        (self.tmp / "model.py").write_text("x = 1\n")
        self.assertEqual(pcb.measure(src=self.tmp), [])

    def test_an_empty_tree_is_refused_rather_than_reported_as_clean(self):
        with self.assertRaises(RuntimeError):
            pcb.measure(src=self.tmp / "nothing")


if __name__ == "__main__":
    unittest.main()
