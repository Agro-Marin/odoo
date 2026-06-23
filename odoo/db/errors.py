"""Shared SQL-error logging for the cursor and bulk-access layers.

Lives in its own module so :mod:`odoo.db.bulk` can import it at module load
time.  :mod:`odoo.db.cursor` imports ``bulk`` at top (the ``Cursor`` mixin), so
``bulk`` cannot import from ``cursor`` at top without a circular import — which
is why ``copy_from`` previously imported ``_log_sql_error`` *lazily* on every
COPY-error path.  Both ``cursor`` and ``bulk`` now import these names from here
at module top, and the lazy import is gone.

All names here are pure (a constant tuple and one logging helper) with no cursor
or connection state.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

# The single source of truth for the cursor layer's logger name.  These are
# SQL-execution faults operators already filter under "odoo.db.cursor", and the
# test suite (TestRecoverableErrorLogLevel / TestCopyFromRecoverableErrorLogLevel)
# asserts records arrive on it.  ``bulk.py`` imports this constant rather than
# re-hardcoding the string; ``cursor.py`` resolves the identical name via its own
# ``__name__``.  Routing every execute()/copy_from() failure through here keeps
# all SQL errors on one logger name, defined once.
CURSOR_LOGGER_NAME = "odoo.db.cursor"

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

# Recoverable transaction errors: the request/retry machinery (http._serve's
# read-only retry, the ORM's optimistic-concurrency retry loop) catches these
# and retries, so they are an EXPECTED part of normal operation under
# contention.  Logging them at ERROR ("bad query") floods the log with false
# faults on every retry.  Demote to WARNING — observable, but not masquerading
# as a defect.  Anything genuinely fatal still hits the ERROR branch.
_RECOVERABLE_SQL_ERRORS: tuple[type[BaseException], ...] = (
    psycopg.errors.ReadOnlySqlTransaction,  # 25006 — caller retries r/w
    psycopg.errors.SerializationFailure,  # 40001 — MVCC, caller retries
    psycopg.errors.DeadlockDetected,  # 40P01 — caller retries
    psycopg.errors.LockNotAvailable,  # 55P03 — NOWAIT/timeout, caller handles
)


def _log_sql_error(exc: Exception, query: Any, *, label: str = "query") -> None:
    """Log a failed SQL statement at a level that matches its recoverability.

    Recoverable errors (read-only retry, MVCC serialization, deadlock,
    lock-not-available) are expected under contention and retried by the
    caller, so they log at WARNING — observable without masquerading as a
    fault.  Everything else is a genuine defect and logs at ERROR.

    Shared by :meth:`Cursor.execute`, :meth:`Cursor.executemany` and
    :meth:`Cursor.copy_from`.  ``copy_from`` previously hand-rolled an
    unconditional ``_logger.error("bad COPY: …")``, so a serialization
    failure / deadlock during a bulk ``create()`` — which the request's
    ``retrying`` loop catches and retries — logged a false ERROR on every
    attempt.  Routing it here demotes those to WARNING like every other path.

    :param exc: the exception raised by the psycopg call.
    :param query: the executed query string (for the log message).
    :param label: noun describing the statement kind for the ERROR message
        (``"query"`` for execute/executemany, ``"COPY"`` for copy_from).
    """
    if isinstance(exc, _RECOVERABLE_SQL_ERRORS):
        _logger.warning(
            "recoverable SQL error (caller may retry): %s: %s",
            type(exc).__name__,
            query,
        )
    else:
        _logger.error("bad %s: %s\nERROR: %s", label, query, exc)
