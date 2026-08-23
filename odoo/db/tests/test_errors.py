import logging
import unittest

import psycopg

from odoo.db.errors import (
    CURSOR_LOGGER_NAME,
    PG_RECOVERABLE_EXCEPTIONS,
    PG_RETRY_EXCEPTIONS,
    PG_RETRY_SQLSTATES,
    PG_STALE_PLAN_EXCEPTIONS,
    PG_USER_FAULT_EXCEPTIONS,
    _log_sql_error,
    is_stale_cached_plan,
    mark_stale_cached_plan,
    reached_the_server,
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


class TestStaleCachedPlanMarker(unittest.TestCase):
    """`cached plan must not change result type` is recoverable but PostgreSQL
    gives it SQLSTATE 0A000 — the same broad code as genuinely permanent
    "cannot alter type of a column used by a view".  It cannot be told apart by
    SQLSTATE, and the message text is localised (this workspace's server runs
    `lc_messages = es_ES.UTF-8`), so neither discriminator is safe.

    The cursor marks the exception instead, at the one place that knows: it saw
    the failure on a connection that had auto-prepared statements, which is the
    necessary condition for a plan-cache error.  Over-inclusion is bounded — a
    permanent 0A000 costs at most the retry loop's attempts.
    """

    def test_an_unmarked_exception_is_not_stale(self):
        self.assertFalse(is_stale_cached_plan(psycopg.errors.FeatureNotSupported("x")))
        self.assertFalse(is_stale_cached_plan(ValueError("x")))

    def test_marking_is_readable_back(self):
        exc = psycopg.errors.FeatureNotSupported("x")
        mark_stale_cached_plan(exc)
        self.assertTrue(is_stale_cached_plan(exc))

    def test_the_marker_does_not_change_the_exception_type(self):
        exc = psycopg.errors.FeatureNotSupported("x")
        mark_stale_cached_plan(exc)
        self.assertIsInstance(exc, psycopg.errors.FeatureNotSupported)
        self.assertIsInstance(exc, psycopg.NotSupportedError)

    def test_the_family_is_the_0A000_class(self):
        self.assertEqual(
            PG_STALE_PLAN_EXCEPTIONS, (psycopg.errors.FeatureNotSupported,)
        )
        for cls in PG_STALE_PLAN_EXCEPTIONS:
            self.assertEqual(getattr(cls, "sqlstate", None), "0A000")

    def test_it_is_not_in_the_sqlstate_retry_taxonomy(self):
        for cls in PG_STALE_PLAN_EXCEPTIONS:
            self.assertNotIn(
                getattr(cls, "sqlstate", None),
                PG_RETRY_SQLSTATES,
                "0A000 must NOT be blanket-retryable: it also covers permanent "
                "failures. Only a marked instance is retried.",
            )
            self.assertNotIn(cls, PG_RETRY_EXCEPTIONS)

    def test_it_is_not_an_OperationalError(self):
        for cls in PG_STALE_PLAN_EXCEPTIONS:
            self.assertFalse(
                issubclass(cls, psycopg.OperationalError),
                "this is why retrying() had to name the family explicitly in "
                "its except clause; it would not have been caught otherwise",
            )

    def test_a_marked_exception_logs_as_recoverable_not_as_a_bad_query(self):
        exc = psycopg.errors.FeatureNotSupported("cached plan must not change")
        mark_stale_cached_plan(exc)
        with self.assertLogs(CURSOR_LOGGER_NAME, level="WARNING") as cm:
            _log_sql_error(exc, "SELECT id, a FROM t")
        self.assertEqual([r.levelno for r in cm.records], [logging.WARNING])
        self.assertIn("stale cached plan", cm.records[0].getMessage())

    def test_an_unmarked_one_still_logs_as_an_error(self):
        with self.assertLogs(CURSOR_LOGGER_NAME, level="ERROR") as cm:
            _log_sql_error(
                psycopg.errors.FeatureNotSupported("cannot alter type"), "ALTER TABLE t"
            )
        self.assertEqual([r.levelno for r in cm.records], [logging.ERROR])


class TestReachedTheServer(unittest.TestCase):
    """A statement that raised still cost a round trip, and used to be counted
    as zero queries -- including by `assertQueryCount`, so any test exercising a
    constraint violation under-reported its real cost.

    Client-side rejections are the exception and must stay uncounted: psycopg
    raises before anything goes on the wire.  SQLSTATE is the discriminator --
    the server supplies one, psycopg's own errors do not.
    """

    def test_server_errors_carry_a_sqlstate(self):
        for cls in (
            psycopg.errors.SyntaxError,
            psycopg.errors.UndefinedTable,
            psycopg.errors.UniqueViolation,
            psycopg.errors.FeatureNotSupported,
        ):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(reached_the_server(cls("boom")))

    def test_client_side_errors_do_not(self):
        for exc in (
            psycopg.ProgrammingError("the query has 2 placeholders but 1 parameters"),
            psycopg.InterfaceError("connection is closed"),
            ValueError("not a psycopg error at all"),
        ):
            with self.subTest(exc=type(exc).__name__):
                self.assertFalse(reached_the_server(exc))


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
