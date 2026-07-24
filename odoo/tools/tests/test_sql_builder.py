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

    def test_sql_element_in_tuple_is_spliced_not_leaked(self):
        # a nested SQL object inside a tuple must splice into the code, not leak
        # into params where psycopg cannot adapt it (fails at execute otherwise)
        sql = SQL("x IN %s", (SQL("SELECT 1"), 2))
        self.assertEqual(sql.code, "x IN (SELECT 1, %s)")
        self.assertEqual(tuple(sql.params), (2,))
        self.assertFalse(any(isinstance(p, SQL) for p in sql.params))

    def test_sql_element_in_tuple_carries_params_and_flush(self):
        field = object()
        inner = SQL("col = %s", 7, to_flush=field)
        sql = SQL("(%s)", (inner, 8))
        self.assertEqual(sql.code, "((col = %s, %s))")
        self.assertEqual(tuple(sql.params), (7, 8))
        self.assertEqual(tuple(sql.to_flush), (field,))

    def test_single_element_tuple(self):
        sql = SQL("x IN %s", (7,))
        self.assertEqual(sql.code, "x IN (%s)")
        self.assertEqual(tuple(sql.params), (7,))


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


class TestSqlInlined(unittest.TestCase):
    """``SQL.inlined()`` embeds bound params as literals."""

    class _Cursor:
        _cnx = None  # psycopg's Literal.as_string accepts a None context

    def test_preserves_to_flush(self):
        field = object()
        sql = SQL('"t"."name"->>%s', "fr_FR", to_flush=field)
        inlined = sql.inlined(self._Cursor())
        self.assertEqual(inlined.code, '"t"."name"->>\'fr_FR\'')
        self.assertEqual(inlined.params, ())
        self.assertEqual(tuple(inlined.to_flush), (field,))

    def test_percent_escape_survives(self):
        # Pre-escaped ``%%`` is kept verbatim; a raw ``code % params`` would
        # collapse the escape or crash on it.
        sql = SQL("x LIKE 'a%%' AND y = %s", 5)
        inlined = sql.inlined(self._Cursor())
        self.assertEqual(inlined.code, "x LIKE 'a%%' AND y = 5")
        self.assertEqual(inlined.params, ())

    def test_literal_containing_percent_is_reescaped(self):
        sql = SQL("y = %s", "50% 'off'")
        inlined = sql.inlined(self._Cursor())
        # The quoted literal's own % is re-escaped so the result stays a valid
        # printf-style code string (collapses to a single % at execution).
        self.assertEqual(inlined.code, "y = '50%% ''off'''")
        self.assertEqual(inlined.params, ())

    def test_no_params_returns_self(self):
        sql = SQL("x LIKE 'a%%'")
        self.assertIs(sql.inlined(self._Cursor()), sql)

    def test_composes_as_sql(self):
        inner = SQL("a = %s", 1).inlined(self._Cursor())
        outer = SQL("%s AND b = %s", inner, 2)
        self.assertEqual(outer.code, "a = 1 AND b = %s")
        self.assertEqual(outer.params, (2,))


if __name__ == "__main__":
    unittest.main()
