"""Tier-1 (database-free) tests for :mod:`odoo.db.errors`.

The concurrency-retry taxonomy is the contract between the cursor layer's log
demotion and the service-layer retry loop; pin it here so drift fails in
milliseconds.  ``_log_sql_error``'s level selection (WARNING for recoverable,
ERROR otherwise) is what keeps retried faults out of the error log.
"""

import logging
import unittest

import psycopg

from odoo.db.errors import (
    CURSOR_LOGGER_NAME,
    PG_RECOVERABLE_EXCEPTIONS,
    PG_RETRY_EXCEPTIONS,
    PG_RETRY_SQLSTATES,
    _log_sql_error,
)


class TestRetryTaxonomyCoherence(unittest.TestCase):
    def test_sqlstates_match_exception_classes(self):
        # The SQLSTATE list and the exception list must describe the same set —
        # service.transaction retries on the classes, addons may match on codes.
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

    def test_copy_label_used_in_error_message(self):
        with self.assertLogs(CURSOR_LOGGER_NAME, level="ERROR") as cm:
            _log_sql_error(ValueError("boom"), "COPY t FROM STDIN", label="COPY")
        self.assertIn("bad COPY", cm.records[0].getMessage())


if __name__ == "__main__":
    unittest.main()
