from __future__ import annotations

import logging
from typing import Any

import psycopg

CURSOR_LOGGER_NAME = "odoo.db.cursor"

_logger = logging.getLogger(CURSOR_LOGGER_NAME)


PG_RETRY_SQLSTATES: tuple[str, ...] = ("55P03", "40001", "40P01")

PG_RETRY_EXCEPTIONS = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
)

# `Exception`, not `BaseException`: every member is a psycopg error, and the
# only consumer (_log_sql_error) takes an Exception. Declared wider, a caller
# holding one of these could not pass it on without the type not matching.
PG_RECOVERABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    *PG_RETRY_EXCEPTIONS,
    psycopg.errors.ReadOnlySqlTransaction,
)

PG_USER_FAULT_EXCEPTIONS: tuple[type[Exception], ...] = (psycopg.IntegrityError,)


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    if isinstance(exc, PG_RECOVERABLE_EXCEPTIONS):
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
