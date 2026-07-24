"""Regression tests for ``odoo.tools.sql.SQL.render``.

``render()`` produces a ``%``-format *template*, not a finished query: literal
``%`` stays escaped as ``%%`` so the result round-trips through ``SQL(...)``.
The parameter-less and parameterised branches used to disagree about this.
"""

import unittest

from odoo.tools.sql import SQL


class TestSqlRenderPercentEscaping(unittest.TestCase):
    def test_no_params_keeps_percent_escaped(self):
        sql = SQL("x LIKE 'a%%'")
        self.assertEqual(sql.render(), "x LIKE 'a%%'")

    def test_params_keep_percent_escaped(self):
        # The bug: this used to render "x LIKE 'a%' AND y = 1", disagreeing
        # with the parameter-less branch above.
        sql = SQL("x LIKE 'a%%' AND y = %s", 1)
        self.assertEqual(sql.render(), "x LIKE 'a%%' AND y = 1")

    def test_percent_inside_inlined_param_is_escaped(self):
        # A '%' arriving through a *value* needs the same escaping as one
        # written in the code, else the round-trip below breaks.
        sql = SQL("y LIKE %s", "50%")
        self.assertEqual(sql.render(), "y LIKE '50%%'")

    def test_render_round_trips_through_sql(self):
        """render() output must be re-wrappable in SQL() -- what both in-tree
        callers (project burndown / CFD reports) actually do."""
        for sql in (
            SQL("x LIKE 'a%%'"),
            SQL("x LIKE 'a%%' AND y = %s", 1),
            SQL("y LIKE %s", "50%"),
            SQL("y = %s", 42),
        ):
            with self.subTest(code=sql.code):
                rendered = sql.render()
                # Must not raise "not enough arguments for format string".
                self.assertEqual(SQL(rendered).code, rendered)

    def test_render_without_percent_is_unchanged(self):
        sql = SQL("a = %s AND b = %s", 1, "x")
        self.assertEqual(sql.render(), "a = 1 AND b = 'x'")


if __name__ == "__main__":
    unittest.main()
