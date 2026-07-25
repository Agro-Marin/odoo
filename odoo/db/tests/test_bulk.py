"""Database-free tests for :mod:`odoo.db.bulk`'s argument validation.

Every check exercised here runs *before* the mixin touches the host cursor, so
a bare ``_BulkAccessMixin()`` is a sufficient stand-in — no connection, no
server, no framework.  These are the guards that turn a caller mistake into a
named error instead of a cryptic failure deep inside the COPY protocol or a
silently-wrong statement, so they are worth pinning at the cheapest tier.

What needs a real backend — the catalog lookup, the lock-before-read ordering,
binary/text encoding of exotic column types — lives in
``odoo/addons/base/tests/test_db_cursor.py``.
"""

import unittest
from typing import Any

from odoo.db.bulk import _NUMERIC_OID, _TEXT_OID, _BulkAccessMixin


class TestCopyFromValidation(unittest.TestCase):
    """``copy_from`` rejects incoherent arguments at the boundary."""

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
    """``execute_values`` needs exactly one real ``%s`` row-list marker."""

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
    """The binary-COPY OIDs are PostgreSQL-fixed; pin them against a typo."""

    def test_constants_match_postgres(self):
        self.assertEqual(_TEXT_OID, 25)
        self.assertEqual(_NUMERIC_OID, 1700)


if __name__ == "__main__":
    unittest.main()
