"""Shared SQL-error logging for the cursor and bulk-access layers.

In its own module so :mod:`odoo.db.bulk` can import it at load time: ``cursor``
imports ``bulk`` (the ``Cursor`` mixin), so ``bulk`` cannot import from
``cursor`` without a cycle.  Both import these names from here instead.

Pure (a constant tuple and one logging helper); no cursor or connection state.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

# Single source of truth for the cursor layer's logger name.  Operators filter
# SQL faults under "odoo.db.cursor" and the test suite asserts on it; ``bulk.py``
# imports this constant rather than re-hardcoding the string, so every
# execute()/copy_from() failure logs on one name.
CURSOR_LOGGER_NAME = "odoo.db.cursor"

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

# Recoverable transaction errors: the request/ORM retry loops catch and retry
# these, so they're expected under contention.  Logging at ERROR would flood the
# log with false faults on every retry, so demote to WARNING (observable, not a
# defect).  Genuinely fatal errors still hit the ERROR branch.
_RECOVERABLE_SQL_ERRORS: tuple[type[BaseException], ...] = (
    psycopg.errors.ReadOnlySqlTransaction,  # 25006 — caller retries r/w
    psycopg.errors.SerializationFailure,  # 40001 — MVCC, caller retries
    psycopg.errors.DeadlockDetected,  # 40P01 — caller retries
    psycopg.errors.LockNotAvailable,  # 55P03 — NOWAIT/timeout, caller handles
)


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    """Log a failed SQL statement at a level that matches its recoverability.

    Recoverable errors (read-only retry, MVCC serialization, deadlock,
    lock-not-available) are retried by the caller, so they log at WARNING;
    everything else is a genuine defect and logs at ERROR.  Shared by
    :meth:`Cursor.execute`, :meth:`Cursor.executemany` and :meth:`Cursor.copy_from`.

    :param exc: the exception raised by the psycopg call.
    :param query: the executed query string (for the log message).
    :param label: statement kind for the ERROR message (``"query"`` or ``"COPY"``).
    """
    if isinstance(exc, _RECOVERABLE_SQL_ERRORS):
        _logger.warning(
            "recoverable SQL error (caller may retry): %s: %s",
            type(exc).__name__,
            query,
        )
    else:
        _logger.error("bad %s: %s\nERROR: %s", label, query, exc)
