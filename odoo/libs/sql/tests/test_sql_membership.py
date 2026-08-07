import unittest

from odoo.libs.sql import SQL


class TestSqlMembership(unittest.TestCase):
    def setUp(self):
        self.col = SQL.identifier("x")

    def test_in_empty_renders_false(self):
        sql = SQL.in_(self.col, [])
        self.assertEqual(sql.code, "FALSE")
        self.assertEqual(sql.params, ())

    def test_not_in_empty_renders_true(self):
        sql = SQL.not_in(self.col, [])
        self.assertEqual(sql.code, "TRUE")
        self.assertEqual(sql.params, ())

    def test_in_nonempty_uses_any_array(self):
        sql = SQL.in_(self.col, [1, 2, 3])
        self.assertEqual(sql.code, '"x" = ANY(%s)')
        self.assertEqual(sql.params, ([1, 2, 3],))

    def test_not_in_nonempty_uses_all_array(self):
        sql = SQL.not_in(self.col, [1, 2])
        self.assertEqual(sql.code, '"x" <> ALL(%s)')
        self.assertEqual(sql.params, ([1, 2],))

    def test_accepts_any_iterable_not_just_list(self):
        self.assertEqual(SQL.in_(self.col, (1, 2)).params, ([1, 2],))
        self.assertEqual(SQL.in_(self.col, {1}).params, ([1],))
        self.assertEqual(SQL.in_(self.col, (i for i in [3, 4])).params, ([3, 4],))

    def test_composes_with_a_general_sql_lhs(self):
        sql = SQL.not_in(SQL("lower(%s)", SQL.identifier("name")), ["a"])
        self.assertEqual(sql.code, 'lower("name") <> ALL(%s)')
        self.assertEqual(sql.params, (["a"],))


if __name__ == "__main__":
    unittest.main()
