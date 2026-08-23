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

PG_RECOVERABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    *PG_RETRY_EXCEPTIONS,
    psycopg.errors.ReadOnlySqlTransaction,
)

PG_USER_FAULT_EXCEPTIONS: tuple[type[Exception], ...] = (psycopg.IntegrityError,)

_STALE_PLAN_ATTR = "_odoo_stale_cached_plan"

PG_STALE_PLAN_EXCEPTIONS: tuple[type[Exception], ...] = (
    psycopg.errors.FeatureNotSupported,
)


def reached_the_server(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) is not None


def mark_stale_cached_plan(exc: Exception) -> None:
    setattr(exc, _STALE_PLAN_ATTR, True)


def is_stale_cached_plan(exc: BaseException) -> bool:
    return getattr(exc, _STALE_PLAN_ATTR, False) is True


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
