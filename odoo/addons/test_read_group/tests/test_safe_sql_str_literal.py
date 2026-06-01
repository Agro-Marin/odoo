"""Unit tests for ``_safe_sql_str_literal`` and SQL-literal embedding sites.

The helper validates that a value can be embedded as a SQL string literal
directly into a format string (rather than parameter-bound), which is
required at four sites in :mod:`odoo.orm.models.mixins.read_group.sql`
because the resulting expression must be byte-identical in ``SELECT`` and
``GROUP BY`` clauses.

These tests are pure-Python: they import the helper and check its
contract (allow-list of safe characters, rejection of quotes/backslashes,
type strictness) without exercising the read_group machinery.
"""

from odoo.orm.models.mixins.read_group.sql import _safe_sql_str_literal
from odoo.tests import common


class TestSafeSqlStrLiteral(common.TransactionCase):
    """Contract tests for the SQL-string-literal embedding helper."""

    def test_returns_quoted_value(self):
        self.assertEqual(_safe_sql_str_literal("UTC"), "'UTC'")

    def test_pytz_with_slash(self):
        # canonical pytz names contain forward slashes
        self.assertEqual(
            _safe_sql_str_literal("America/New_York"),
            "'America/New_York'",
        )

    def test_pytz_with_plus(self):
        # Etc/GMT zones have signed offsets
        self.assertEqual(_safe_sql_str_literal("Etc/GMT+0"), "'Etc/GMT+0'")
        self.assertEqual(_safe_sql_str_literal("Etc/GMT-12"), "'Etc/GMT-12'")

    def test_time_granularity_keys(self):
        # all keys of READ_GROUP_TIME_GRANULARITY must be embeddable
        from odoo.orm.constants import READ_GROUP_TIME_GRANULARITY
        for key in READ_GROUP_TIME_GRANULARITY:
            self.assertEqual(_safe_sql_str_literal(key), f"'{key}'")

    def test_pg_granularity_values(self):
        # all values of READ_GROUP_NUMBER_GRANULARITY must be embeddable
        from odoo.orm.constants import READ_GROUP_NUMBER_GRANULARITY
        for value in READ_GROUP_NUMBER_GRANULARITY.values():
            self.assertEqual(_safe_sql_str_literal(value), f"'{value}'")

    def test_rejects_single_quote(self):
        with self.assertRaises(ValueError):
            _safe_sql_str_literal("a'b")
        with self.assertRaises(ValueError):
            _safe_sql_str_literal("'; DROP TABLE foo; --")

    def test_rejects_backslash(self):
        with self.assertRaises(ValueError):
            _safe_sql_str_literal("a\\b")

    def test_rejects_non_str(self):
        with self.assertRaises(TypeError):
            _safe_sql_str_literal(123)
        with self.assertRaises(TypeError):
            _safe_sql_str_literal(None)
        with self.assertRaises(TypeError):
            _safe_sql_str_literal(["a"])

    def test_empty_string(self):
        # empty string is allowed — produces the empty SQL literal ''
        self.assertEqual(_safe_sql_str_literal(""), "''")
