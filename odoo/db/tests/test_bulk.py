import unittest
from typing import Any

from odoo.db.bulk import (
    _NUMERIC_OID,
    _TEXT_OID,
    _BulkAccessMixin,
    _table_identifier,
)


class TestCopyFromValidation(unittest.TestCase):
    def setUp(self):
        self.bulk: Any = _BulkAccessMixin()

    def test_empty_columns_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.copy_from("t", [], [(1,)])
        self.assertIn("non-empty", str(ctx.exception))

    def test_unknown_on_error_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.copy_from("t", ["a"], [(1,)], on_error="drop table")
        self.assertIn("invalid on_error", str(ctx.exception))

    def test_on_error_with_binary_is_rejected(self):
        with self.assertRaises(ValueError):
            self.bulk.copy_from("t", ["a"], [(1,)], on_error="ignore", binary=True)

    def test_on_error_ignore_with_returning_ids_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.copy_from(
                "t", ["a"], [(1,)], on_error="ignore", returning_ids=True
            )
        self.assertIn("returning_ids", str(ctx.exception))

    def test_on_error_stop_is_accepted_by_the_whitelist(self):
        with self.assertRaises(Exception) as ctx:
            self.bulk.copy_from("t", ["a"], [(1,)], on_error="stop")
        self.assertNotIsInstance(ctx.exception, ValueError)


class TestExecuteValuesValidation(unittest.TestCase):
    def setUp(self):
        self.bulk: Any = _BulkAccessMixin()

    def test_non_positive_page_size_is_rejected(self):
        for size in (0, -1):
            with self.subTest(page_size=size), self.assertRaises(ValueError):
                self.bulk.execute_values(
                    "INSERT INTO t VALUES %s", [(1,)], page_size=size
                )

    def test_missing_marker_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.execute_values("INSERT INTO t VALUES (1)", [(1,)])
        self.assertIn("got 0", str(ctx.exception))

    def test_two_markers_are_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.execute_values("INSERT INTO t VALUES %s, %s", [(1,)])
        self.assertIn("got 2", str(ctx.exception))

    def test_escaped_percent_is_not_a_marker(self):
        with self.assertRaises(ValueError) as ctx:
            self.bulk.execute_values("SELECT '100%%s' FROM t", [(1,)])
        self.assertIn("got 0", str(ctx.exception))

    def test_marker_validation_precedes_the_empty_short_circuit(self):
        with self.assertRaises(ValueError):
            self.bulk.execute_values("INSERT INTO t VALUES (1)", [])

    def test_empty_argslist_short_circuits_on_a_valid_query(self):
        self.assertIsNone(self.bulk.execute_values("INSERT INTO t VALUES %s", []))
        self.assertEqual(
            self.bulk.execute_values("INSERT INTO t VALUES %s", [], fetch=True), []
        )


class TestTypeOidConstants(unittest.TestCase):
    def test_constants_match_postgres(self):
        self.assertEqual(_TEXT_OID, 25)
        self.assertEqual(_NUMERIC_OID, 1700)


class TestTableIdentifier(unittest.TestCase):
    def _rendered(self, table):
        return _table_identifier(table).as_string(None)

    def test_plain_name_is_quoted(self):
        self.assertEqual(self._rendered("res_partner"), '"res_partner"')

    def test_mixed_case_is_preserved_not_folded(self):
        self.assertEqual(self._rendered("MyTable"), '"MyTable"')

    def test_schema_qualified_name_becomes_two_identifiers(self):
        self.assertEqual(self._rendered("s1.t"), '"s1"."t"')

    def test_quotes_in_a_name_cannot_break_out(self):
        self.assertEqual(self._rendered('ev"il'), '"ev""il"')


class _FractionOnly(_BulkAccessMixin):
    def _can_dump_binary(self, oids):
        return True


class TestBinaryPaysOff(unittest.TestCase):
    def setUp(self):
        self.bulk: Any = _FractionOnly()

    def _oids(self, numeric, total=20):
        return [_NUMERIC_OID] * numeric + [_TEXT_OID] * (total - numeric)

    def test_no_numeric_columns_uses_binary(self):
        self.assertTrue(self.bulk._binary_pays_off(self._oids(0)))

    def test_a_few_numeric_columns_still_uses_binary(self):
        for n in (1, 2, 3, 4, 5):
            with self.subTest(numeric=n):
                self.assertTrue(self.bulk._binary_pays_off(self._oids(n)))

    def test_numeric_heavy_rows_fall_back_to_text(self):
        for n in (6, 8, 20):
            with self.subTest(numeric=n):
                self.assertFalse(self.bulk._binary_pays_off(self._oids(n)))

    def test_all_numeric_falls_back_however_narrow_the_row(self):
        self.assertFalse(self.bulk._binary_pays_off([_NUMERIC_OID]))

    def test_an_undumpable_column_vetoes_binary_regardless_of_fraction(self):
        class _NoDumper(_BulkAccessMixin):
            def _can_dump_binary(self, oids):
                return False

        self.assertFalse(_NoDumper()._binary_pays_off([_TEXT_OID] * 20))


if __name__ == "__main__":
    unittest.main()
