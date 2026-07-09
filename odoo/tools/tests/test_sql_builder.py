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
