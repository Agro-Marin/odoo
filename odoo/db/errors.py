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

CURSOR_LOGGER_NAME = "odoo.db.cursor"

_logger = logging.getLogger(CURSOR_LOGGER_NAME)


PG_RETRY_SQLSTATES: tuple[str, ...] = ("55P03", "40001", "40P01")

PG_RETRY_EXCEPTIONS = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
)

PG_RECOVERABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    *PG_RETRY_EXCEPTIONS,
    psycopg.errors.ReadOnlySqlTransaction,
)

PG_USER_FAULT_EXCEPTIONS: tuple[type[BaseException], ...] = (psycopg.IntegrityError,)


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    """Log a failed SQL statement at a level that matches what it means.

    Three tiers, because "the statement raised" covers three unrelated
    situations and only one of them is an operator's problem:

    * **recoverable** (:data:`PG_RECOVERABLE_EXCEPTIONS`) — read-only retry,
      MVCC serialization, deadlock, lock-not-available.  The caller re-runs the
      transaction, so WARNING; ERROR here floods the log on every retry.
    * **expected user fault** (:data:`PG_USER_FAULT_EXCEPTIONS`) — a constraint
      violation the service layer turns into a ``ValidationError`` shown to the
      user.  WARNING, for the reasons above that constant.
    * **everything else** — a genuine defect (bad SQL, missing relation, type
      error).  ERROR, with the statement, which is what ERROR should mean.

    Shared by :meth:`Cursor.execute`, :meth:`Cursor.executemany`,
    :meth:`Cursor.execute_values` and :meth:`Cursor.copy_from`.

    :param exc: the exception raised by the psycopg call.
    :param query: the executed query string (for the log message).
    :param label: statement kind for the ERROR message (``"query"`` or ``"COPY"``).
    """
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
