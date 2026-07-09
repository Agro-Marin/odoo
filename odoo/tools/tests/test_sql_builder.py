"""Regression tests for the ``odoo.tools.sql.SQL`` composition primitive.

Focus: tuple expansion.  An empty tuple must not render the invalid ``()``
(a PostgreSQL syntax error) — it renders ``(NULL)`` so ``x IN (NULL)`` parses
and matches nothing.
"""

import unittest

from odoo.tools.sql import SQL


class TestSqlTupleExpansion(unittest.TestCase):
    def test_empty_tuple_renders_null(self):
        sql = SQL("x IN %s", ())
        self.assertEqual(sql.code, "x IN (NULL)")
        self.assertEqual(tuple(sql.params), ())

    def test_non_empty_tuple_expands_placeholders(self):
        sql = SQL("x IN %s", (1, 2, 3))
        self.assertEqual(sql.code, "x IN (%s, %s, %s)")
        self.assertEqual(tuple(sql.params), (1, 2, 3))

    def test_single_element_tuple(self):
        sql = SQL("x IN %s", (7,))
        self.assertEqual(sql.code, "x IN (%s)")
        self.assertEqual(tuple(sql.params), (7,))


if __name__ == "__main__":
    unittest.main()


class TestSqlIdentifierValidation(unittest.TestCase):
    def test_identifier_rejects_trailing_newline(self):
        # IDENT_RE is ``\Z``-anchored: ``$`` would also match before a trailing
        # newline, letting ``"col\n"`` validate and reach SQL unquoted.
        with self.assertRaises(ValueError):
            SQL.identifier("col\n")

    def test_identifier_accepts_plain_name(self):
        self.assertEqual(SQL.identifier("col").code, '"col"')


class TestColumnIndexExistsReturnBool(unittest.TestCase):
    """``column_exists``/``index_exists`` are annotated ``-> bool``; they must
    return an actual bool, not the ``int`` ``cr.rowcount``."""

    class _Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

        def execute(self, *args, **kwargs):
            pass

    def test_true_is_bool(self):
        from odoo.tools.sql import column_exists, index_exists

        cr = self._Cursor(1)
        self.assertIs(column_exists(cr, "t", "c"), True)
        self.assertIs(index_exists(cr, "i"), True)

    def test_false_is_bool(self):
        from odoo.tools.sql import column_exists, index_exists

        cr = self._Cursor(0)
        self.assertIs(column_exists(cr, "t", "c"), False)
        self.assertIs(index_exists(cr, "i"), False)
