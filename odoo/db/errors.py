from __future__ import annotations

import logging
from typing import Any

import psycopg

CURSOR_LOGGER_NAME = "odoo.db.cursor"

_logger = logging.getLogger(CURSOR_LOGGER_NAME)


PG_RETRY_EXCEPTIONS = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
)

# Derived, never spelled twice.  These were two hand-maintained encodings of one
# fact -- ("55P03", "40001", "40P01") written out beside the classes that carry
# exactly those sqlstates -- and both are exported and read by
# `service/transaction.py`, `ir_job.py` and `account_move.py`, so a drift
# between them is a silent split in the retry policy.  psycopg puts the code on
# the class, so the tuple is a projection rather than a copy.
PG_RETRY_SQLSTATES: tuple[str, ...] = tuple(e.sqlstate for e in PG_RETRY_EXCEPTIONS)

PG_RECOVERABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    *PG_RETRY_EXCEPTIONS,
    psycopg.errors.ReadOnlySqlTransaction,
)

PG_USER_FAULT_EXCEPTIONS: tuple[type[Exception], ...] = (psycopg.IntegrityError,)

_STALE_PLAN_ATTR = "_odoo_stale_cached_plan"

_SEAM_ATTR = "_odoo_handled_by_statement_seam"

PG_STALE_PLAN_EXCEPTIONS: tuple[type[Exception], ...] = (
    psycopg.errors.FeatureNotSupported,
)


def reached_the_server(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) is not None


def mark_stale_cached_plan(exc: Exception) -> None:
    setattr(exc, _STALE_PLAN_ATTR, True)


def is_stale_cached_plan(exc: BaseException) -> bool:
    return getattr(exc, _STALE_PLAN_ATTR, False) is True


def mark_handled_by_seam(exc: BaseException) -> None:
    """Record that `Cursor._statement_failed` has already handled this error.

    Named `is_`/`mark_` like the stale-plan pair beside it, and for a gate's
    reason as well as a stylistic one: `naming_vocabulary.census()` counts a
    `-> bool` function as a predicate only when its name starts `is_`, `has_`
    or `can_`, and `bool_return_is_not_a_predicate` in `coding_guidelines.rst`
    is a restated figure that `doc_restated_counts` fails on. A first draft
    called this `seen_by_seam` and moved that count 381 -> 382.

    The seam has one non-idempotent job -- `_log_sql_error` -- and, since
    pipeline mode defers a statement's error to the next sync, it has two
    possible call sites for the same exception: the entry point that issued
    the statement, and `Cursor.pipeline`'s exit, where psycopg finally raises
    it. Exactly one of them is reached for any given error, but both must be
    armed and neither can know which. The mark makes the second call a no-op
    instead of a second log line.
    """
    setattr(exc, _SEAM_ATTR, True)


def is_handled_by_seam(exc: BaseException) -> bool:
    return getattr(exc, _SEAM_ATTR, False) is True


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    if is_stale_cached_plan(exc):
        _logger.warning(
            "stale cached plan discarded (caller may retry): %s: %s",
            type(exc).__name__,
            query,
        )
    elif isinstance(exc, PG_RECOVERABLE_EXCEPTIONS):
        _logger.warning(
            "recoverable SQL error (caller may retry): %s: %s",
            type(exc).__name__,
            query,
        )
    elif isinstance(exc, PG_USER_FAULT_EXCEPTIONS):
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
        _logger.warning(
            "constraint violation (surfaced to the user): %s%s: %s",
            type(exc).__name__,
            f" on {constraint}" if constraint else "",
            query,
        )
    else:
        _logger.error("bad %s: %s\nERROR: %s", label, query, exc)
