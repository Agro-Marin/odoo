import logging
import unittest

import psycopg

from odoo.db.errors import (
    CURSOR_LOGGER_NAME,
    PG_RECOVERABLE_EXCEPTIONS,
    PG_RETRY_EXCEPTIONS,
    PG_RETRY_SQLSTATES,
    PG_USER_FAULT_EXCEPTIONS,
    _log_sql_error,
)


class TestRetryTaxonomyCoherence(unittest.TestCase):
    def test_sqlstates_match_exception_classes(self):
        self.assertEqual(
            sorted(PG_RETRY_SQLSTATES),
            sorted(cls.sqlstate for cls in PG_RETRY_EXCEPTIONS),
        )

    def test_recoverable_is_retry_plus_readonly(self):
        self.assertEqual(
            set(PG_RECOVERABLE_EXCEPTIONS),
            set(PG_RETRY_EXCEPTIONS) | {psycopg.errors.ReadOnlySqlTransaction},
        )


class TestLogSqlErrorLevels(unittest.TestCase):
    def test_recoverable_logs_warning(self):
        for cls in PG_RECOVERABLE_EXCEPTIONS:
            with self.assertLogs(CURSOR_LOGGER_NAME, level="WARNING") as cm:
                _log_sql_error(cls("boom"), "SELECT 1")
            self.assertEqual([r.levelno for r in cm.records], [logging.WARNING])
            self.assertIn("caller may retry", cm.records[0].getMessage())

    def test_genuine_fault_logs_error(self):
        with self.assertLogs(CURSOR_LOGGER_NAME, level="ERROR") as cm:
            _log_sql_error(psycopg.errors.UndefinedTable("boom"), "SELECT 1")
        self.assertEqual([r.levelno for r in cm.records], [logging.ERROR])
        self.assertIn("bad query", cm.records[0].getMessage())

    def test_constraint_violations_log_warning_not_error(self):
        for cls in (
            psycopg.errors.UniqueViolation,
            psycopg.errors.ForeignKeyViolation,
            psycopg.errors.NotNullViolation,
            psycopg.errors.CheckViolation,
        ):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, PG_USER_FAULT_EXCEPTIONS))
                with self.assertLogs(CURSOR_LOGGER_NAME, level="WARNING") as cm:
                    _log_sql_error(cls("boom"), "INSERT INTO t VALUES (1)")
                self.assertEqual([r.levelno for r in cm.records], [logging.WARNING])
                self.assertIn("constraint violation", cm.records[0].getMessage())

    def test_user_fault_tier_is_separable_from_the_retry_tier(self):
        with self.assertLogs(CURSOR_LOGGER_NAME, level="WARNING") as retry:
            _log_sql_error(psycopg.errors.DeadlockDetected("x"), "SELECT 1")
        with self.assertLogs(CURSOR_LOGGER_NAME, level="WARNING") as fault:
            _log_sql_error(psycopg.errors.UniqueViolation("x"), "SELECT 1")
        self.assertNotEqual(
            retry.records[0].getMessage().split(":")[0],
            fault.records[0].getMessage().split(":")[0],
        )

    def test_retry_tier_wins_over_the_user_fault_tier(self):
        self.assertFalse(
            any(issubclass(c, PG_USER_FAULT_EXCEPTIONS) for c in PG_RETRY_EXCEPTIONS),
            "the two tiers must not overlap, or the first check silently wins",
        )

    def test_copy_label_used_in_error_message(self):
        with self.assertLogs(CURSOR_LOGGER_NAME, level="ERROR") as cm:
            _log_sql_error(ValueError("boom"), "COPY t FROM STDIN", label="COPY")
        self.assertIn("bad COPY", cm.records[0].getMessage())


if __name__ == "__main__":
    unittest.main()
