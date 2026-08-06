"""Correctness and safety preconditions of the Rust ``rows_to_dicts``.

``rows_to_dicts`` (``odoo_rust``) backs ``Cursor.dictfetchall`` /
``dictfetchmany`` and ``Environment.execute_query_dict`` — it replaces
``[dict(zip(cols, row)) for row in rows]`` with a tight loop that uses the
*unchecked* ``PyTuple_GET_ITEM``. That unsafe access is sound only because the
function validates, per row, that the row **is a tuple** and that its **length
matches** the column count; a non-tuple or a wrong-length row would otherwise
read past the object and is undefined behaviour. The audit noted those
preconditions had no test at all — so a refactor could drop a guard and the
suite would stay green while the accelerator segfaulted on malformed input.

These pin both halves: parity with the Python expression for well-formed input,
and the two guards for malformed input. Imports ``odoo_rust`` directly; no DB.
"""

import unittest

from odoo_rust import rows_to_dicts


def _python_equivalent(names, rows):
    return [dict(zip(names, row, strict=True)) for row in rows]


class TestRowsToDictsCorrectness(unittest.TestCase):
    def test_matches_the_python_expression(self):
        names = ("id", "name", "active")
        rows = [(1, "a", True), (2, "b", False), (3, None, None)]
        self.assertEqual(rows_to_dicts(names, rows), _python_equivalent(names, rows))

    def test_empty_rows(self):
        self.assertEqual(rows_to_dicts(("a", "b"), []), [])

    def test_no_columns(self):
        self.assertEqual(rows_to_dicts((), [(), ()]), [{}, {}])

    def test_single_column(self):
        self.assertEqual(rows_to_dicts(("x",), [(1,), (2,)]), [{"x": 1}, {"x": 2}])

    def test_duplicate_column_names_last_wins(self):
        # dict semantics: the Python expression collapses to the last value too.
        names = ("k", "k")
        rows = [(1, 2)]
        self.assertEqual(rows_to_dicts(names, rows), _python_equivalent(names, rows))
        self.assertEqual(rows_to_dicts(names, rows), [{"k": 2}])

    def test_mixed_value_types_are_passed_through_by_reference(self):
        obj = object()
        names = ("i", "f", "s", "n", "o", "lst")
        rows = [(1, 1.5, "x", None, obj, [1, 2])]
        result = rows_to_dicts(names, rows)
        self.assertIs(result[0]["o"], obj)
        self.assertIs(result[0]["lst"], rows[0][5])  # shared, not copied

    def test_many_rows_and_columns(self):
        names = tuple(f"c{j}" for j in range(20))
        rows = [tuple(range(i, i + 20)) for i in range(200)]
        self.assertEqual(rows_to_dicts(names, rows), _python_equivalent(names, rows))


class TestRowsToDictsSafetyPreconditions(unittest.TestCase):
    """The guards that make the unchecked ``PyTuple_GET_ITEM`` sound."""

    def test_a_non_tuple_row_raises_type_error(self):
        with self.assertRaises(TypeError):
            rows_to_dicts(("a", "b"), [[1, 2]])  # a list, not a tuple

    def test_a_short_row_raises_value_error(self):
        with self.assertRaises(ValueError):
            rows_to_dicts(("a", "b", "c"), [(1, 2)])

    def test_a_long_row_raises_value_error(self):
        with self.assertRaises(ValueError):
            rows_to_dicts(("a", "b"), [(1, 2, 3)])

    def test_a_malformed_row_after_good_ones_still_raises(self):
        with self.assertRaises(ValueError):
            rows_to_dicts(("a", "b"), [(1, 2), (3, 4), (5,)])

    def test_the_error_names_the_offending_row_index(self):
        with self.assertRaises(ValueError) as ctx:
            rows_to_dicts(("a", "b"), [(1, 2), (3,)])
        self.assertIn("1", str(ctx.exception))  # row index 1 is the bad one


if __name__ == "__main__":
    unittest.main()
