import unittest

from odoo.libs.sql import SQL


class TestSqlRenderPercentEscaping(unittest.TestCase):
    def test_no_params_keeps_percent_escaped(self):
        sql = SQL("x LIKE 'a%%'")
        self.assertEqual(sql.render(), "x LIKE 'a%%'")

    def test_params_keep_percent_escaped(self):
        sql = SQL("x LIKE 'a%%' AND y = %s", 1)
        self.assertEqual(sql.render(), "x LIKE 'a%%' AND y = 1")

    def test_percent_inside_inlined_param_is_escaped(self):
        sql = SQL("y LIKE %s", "50%")
        self.assertEqual(sql.render(), "y LIKE '50%%'")

    def test_render_round_trips_through_sql(self):
        for sql in (
            SQL("x LIKE 'a%%'"),
            SQL("x LIKE 'a%%' AND y = %s", 1),
            SQL("y LIKE %s", "50%"),
            SQL("y = %s", 42),
        ):
            with self.subTest(code=sql.code):
                rendered = sql.render()
                self.assertEqual(SQL(rendered).code, rendered)

    def test_render_without_percent_is_unchanged(self):
        sql = SQL("a = %s AND b = %s", 1, "x")
        self.assertEqual(sql.render(), "a = 1 AND b = 'x'")


if __name__ == "__main__":
    unittest.main()
