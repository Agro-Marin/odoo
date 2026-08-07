from odoo.tests import common
from odoo.tools import SQL


class TestSqlLiteral(common.TransactionCase):
    def test_returns_quoted_value(self):
        self.assertEqual(SQL.literal("UTC").code, "'UTC'")

    def test_pytz_with_slash(self):
        self.assertEqual(SQL.literal("America/New_York").code, "'America/New_York'")

    def test_pytz_with_plus(self):
        self.assertEqual(SQL.literal("Etc/GMT+0").code, "'Etc/GMT+0'")
        self.assertEqual(SQL.literal("Etc/GMT-12").code, "'Etc/GMT-12'")

    def test_time_granularity_keys(self):
        from odoo.orm.constants import READ_GROUP_TIME_GRANULARITY

        for key in READ_GROUP_TIME_GRANULARITY:
            self.assertEqual(SQL.literal(key).code, f"'{key}'")

    def test_pg_granularity_values(self):
        from odoo.orm.constants import READ_GROUP_NUMBER_GRANULARITY

        for value in READ_GROUP_NUMBER_GRANULARITY.values():
            self.assertEqual(SQL.literal(value).code, f"'{value}'")

    def test_rejects_single_quote(self):
        with self.assertRaises(ValueError):
            SQL.literal("a'b")
        with self.assertRaises(ValueError):
            SQL.literal("'; DROP TABLE foo; --")

    def test_rejects_backslash(self):
        with self.assertRaises(ValueError):
            SQL.literal("a\\b")

    def test_rejects_percent(self):
        with self.assertRaises(ValueError):
            SQL.literal("100%")

    def test_rejects_non_str(self):
        with self.assertRaises(TypeError):
            SQL.literal(123)
        with self.assertRaises(TypeError):
            SQL.literal(None)
        with self.assertRaises(TypeError):
            SQL.literal(["a"])

    def test_empty_string(self):
        self.assertEqual(SQL.literal("").code, "''")

    def test_composes_into_code_not_params(self):
        expr = SQL("date_trunc(%s, %s::timestamp)", SQL.literal("month"), SQL("col"))
        self.assertEqual(expr.code, "date_trunc('month', col::timestamp)")
        self.assertEqual(expr.params, ())

    def test_two_uses_of_one_literal_render_identically(self):
        interval = SQL.literal("-2 DAY")
        expr = SQL("(%s - INTERVAL %s + INTERVAL %s)", SQL("c"), interval, interval)
        self.assertEqual(expr.code, "(c - INTERVAL '-2 DAY' + INTERVAL '-2 DAY')")
        self.assertEqual(expr.params, ())
