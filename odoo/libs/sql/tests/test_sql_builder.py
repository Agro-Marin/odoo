import unittest

from odoo.libs.sql import SQL


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
        sql = SQL("x IN %s", (SQL("SELECT 1"), 2))
        self.assertEqual(sql.code, "x IN (SELECT 1, %s)")
        self.assertEqual(tuple(sql.params), (2,))
        self.assertFalse(any(isinstance(p, SQL) for p in sql.params))

    def test_sql_element_in_tuple_carries_params_and_flush(self):
        field = object()
        inner = SQL("col = %s", 7, to_flush=field)  # type: ignore[arg-type]
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
        with self.assertRaises(ValueError):
            SQL.identifier("col\n")

    def test_identifier_accepts_plain_name(self):
        self.assertEqual(SQL.identifier("col").code, '"col"')


class TestColumnIndexExistsReturnBool(unittest.TestCase):
    class _Cursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

        def execute(self, *args, **kwargs):
            pass

    def test_true_is_bool(self):
        from odoo.db.schema import column_exists, index_exists

        cr = self._Cursor(1)
        self.assertIs(column_exists(cr, "t", "c"), True)  # type: ignore[arg-type]
        self.assertIs(index_exists(cr, "i"), True)  # type: ignore[arg-type]

    def test_false_is_bool(self):
        from odoo.db.schema import column_exists, index_exists

        cr = self._Cursor(0)
        self.assertIs(column_exists(cr, "t", "c"), False)  # type: ignore[arg-type]
        self.assertIs(index_exists(cr, "i"), False)  # type: ignore[arg-type]


class TestSqlInlined(unittest.TestCase):
    class _Cursor:
        _cnx = None

    def test_preserves_to_flush(self):
        field = object()
        sql = SQL('"t"."name"->>%s', "fr_FR", to_flush=field)  # type: ignore[arg-type]
        inlined = sql.inlined(self._Cursor())  # type: ignore[arg-type]
        self.assertEqual(inlined.code, '"t"."name"->>\'fr_FR\'')
        self.assertEqual(inlined.params, ())
        self.assertEqual(tuple(inlined.to_flush), (field,))

    def test_percent_escape_survives(self):
        sql = SQL("x LIKE 'a%%' AND y = %s", 5)
        inlined = sql.inlined(self._Cursor())  # type: ignore[arg-type]
        self.assertEqual(inlined.code, "x LIKE 'a%%' AND y = 5")
        self.assertEqual(inlined.params, ())

    def test_literal_containing_percent_is_reescaped(self):
        sql = SQL("y = %s", "50% 'off'")
        inlined = sql.inlined(self._Cursor())  # type: ignore[arg-type]
        self.assertEqual(inlined.code, "y = '50%% ''off'''")
        self.assertEqual(inlined.params, ())

    def test_no_params_returns_self(self):
        sql = SQL("x LIKE 'a%%'")
        self.assertIs(sql.inlined(self._Cursor()), sql)  # type: ignore[arg-type]

    def test_composes_as_sql(self):
        inner = SQL("a = %s", 1).inlined(self._Cursor())  # type: ignore[arg-type]
        outer = SQL("%s AND b = %s", inner, 2)
        self.assertEqual(outer.code, "a = 1 AND b = %s")
        self.assertEqual(outer.params, (2,))


if __name__ == "__main__":
    unittest.main()
