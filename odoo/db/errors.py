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

# ---------------------------------------------------------------------------
# Canonical PostgreSQL concurrency-error taxonomy — single source of truth.
#
# https://www.postgresql.org/docs/current/errcodes-appendix.html
#   55P03 lock_not_available · 40001 serialization_failure · 40P01 deadlock_detected
#
# ``db`` is the lowest layer the cursor (this module) and the retry loop
# (``service.transaction``) share, so the retry vocabulary lives here and is
# imported by both — the SQLSTATE list and the exception list cannot drift apart.
# ---------------------------------------------------------------------------

# RETRY: re-running the transaction from the top may succeed.
# ``service.transaction.retrying`` retries on exactly these (and re-exports them
# as ``PG_CONCURRENCY_*`` for addons that catch the same set).
PG_RETRY_SQLSTATES: tuple[str, ...] = ("55P03", "40001", "40P01")

# Unannotated on purpose: mypy infers the precise element types, so callers'
# ``isinstance(exc, PG_RETRY_EXCEPTIONS)`` narrows ``exc`` to these exact classes
# and can read ``exc.sqlstate`` (a ``tuple[type[BaseException], ...]`` annotation
# would widen the narrowing to bare ``BaseException`` and lose ``.sqlstate``).
PG_RETRY_EXCEPTIONS = (
    psycopg.errors.LockNotAvailable,  # 55P03 — NOWAIT / lock_timeout
    psycopg.errors.SerializationFailure,  # 40001 — MVCC serialization
    psycopg.errors.DeadlockDetected,  # 40P01 — deadlock victim
)

# RECOVERABLE = retryable + read-only-transaction.  25006 is *not* retried in the
# same loop (the HTTP request loop re-dispatches on a read/write cursor) but it
# is still an expected, non-defect fault, so the cursor layer demotes the whole
# RECOVERABLE set from ERROR to WARNING: logging at ERROR would flood the log
# with false faults on every retry.  Genuinely fatal errors still hit ERROR.
PG_RECOVERABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    *PG_RETRY_EXCEPTIONS,
    psycopg.errors.ReadOnlySqlTransaction,  # 25006 — request loop retries r/w
)


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    """Log a failed SQL statement at a level that matches its recoverability.

    Recoverable errors (read-only retry, MVCC serialization, deadlock,
    lock-not-available) are retried by the caller, so they log at WARNING;
    everything else is a genuine defect and logs at ERROR.  Shared by
    :meth:`Cursor.execute`, :meth:`Cursor.executemany`, :meth:`Cursor.execute_values`
    and :meth:`Cursor.copy_from`.

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
    else:
        _logger.error("bad %s: %s\nERROR: %s", label, query, exc)
