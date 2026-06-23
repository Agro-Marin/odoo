"""SQL serialization-retry primitive.

``retrying()`` was historically defined in ``service.model`` because it
was used internally by ``execute_cr``.  But seven call sites across the
codebase reach for it — six of them HTTP- or websocket-related — so the
``service.model`` location both understated the function's reach and
made the import path misleading (``from odoo.service.model import retrying``
suggested a model-dispatch concern, when the function is the project-wide
SQL-retry primitive).

The function is HTTP-aware (it rewinds uploaded files and refreshes
the session/dbname when called from inside a request) but the core
mechanism — exponential-backoff retry on PostgreSQL serialization
failures and lock-not-available errors — is general.

Callers:

* ``odoo.service.model.execute_cr`` (RPC dispatch, the historical caller)
* ``odoo.http.__init__`` (root WSGI dispatch and ir.http fallback)
* ``odoo.http._serve`` (Request.serve)
* ``odoo.addons.bus.websocket`` (websocket message + dispatch wrappers)

``service.model`` re-exports ``retrying`` so existing
``from odoo.service.model import retrying`` keeps working.
"""

from __future__ import annotations

import logging
import random
import time
import typing
from contextlib import suppress

from psycopg import IntegrityError, OperationalError, errors

from odoo.exceptions import ConcurrencyError, ValidationError

# ``odoo.http`` is imported LAZILY inside ``retrying`` (not at module top)
# because ``odoo.http._serve`` imports ``retrying`` from this module — a
# top-level ``from odoo import http`` here would form a circular import
# during ``odoo.http`` package initialisation:
#   http/__init__ → http.routing → http.dispatcher → http.request_class
#       → http._serve → service.transaction → odoo.http (partial!) → fail.
# The lazy import is fine — ``retrying`` is only called at request time,
# long after all packages have loaded.

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")  # preserve operator log filters

# PG SQLSTATEs that warrant a retry. Documented at
# https://www.postgresql.org/docs/current/errcodes-appendix.html
#   55P03 lock_not_available
#   40001 serialization_failure
#   40P01 deadlock_detected
PG_CONCURRENCY_ERRORS_TO_RETRY = ("55P03", "40001", "40P01")
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = (
    errors.LockNotAvailable,
    errors.SerializationFailure,
    errors.DeadlockDetected,
)
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5


def _integrity_error_to_validation(env: Environment, exc: IntegrityError) -> ValidationError:
    """Map a psycopg ``IntegrityError`` to a user-facing ``ValidationError``.

    Names the offending model by matching ``exc.diag.table_name`` against the
    registry, then formats the message via that model's
    ``_sql_error_to_message``.  Shared by the in-loop handler and the
    commit-time handler so the two translations cannot drift (a deferred
    constraint fires at COMMIT, outside the loop — see :func:`retrying`).
    """
    model = env["base"]
    for rclass in env.registry.values():
        if exc.diag.table_name == rclass._table:
            model = env[rclass._name]
            break
    message = env._(
        "The operation cannot be completed: %s",
        model._sql_error_to_message(exc),
    )
    return ValidationError(message)


def _rewind_request_for_retry(request: typing.Any, exc: BaseException) -> None:
    """Prepare an in-flight HTTP request for a transaction retry.

    A retry re-runs the handler from the top, so the session is re-fetched
    (the rolled-back attempt may have invalidated it) and every uploaded file
    is rewound to offset 0 — otherwise the replay reads a partially-consumed
    stream.  A non-seekable upload cannot be replayed, so this raises.

    Kept out of :func:`retrying`'s loop body so the SQL-retry primitive is not
    cluttered with HTTP-request knowledge.
    """
    request.session = request._get_session_and_dbname()[0]
    for filename, file in request.httprequest.files.items():
        if hasattr(file, "seekable") and file.seekable():
            file.seek(0)
        else:
            raise RuntimeError(
                f"Cannot retry request on input file {filename!r} after serialization failure"
            ) from exc


def retrying[T](func: Callable[[], T], env: Environment) -> T:
    """Call ``func`` in a loop until the SQL transaction commits with no
    serialisation error. Rolls back the transaction in between calls.

    A serialisation error occurs when two independent transactions
    attempt to commit incompatible changes such as writing different
    values on the same record. The first transaction to commit works,
    the second is canceled with a
    :class:`psycopg.errors.SerializationFailure`.

    This function intercepts those serialization errors, rolls back
    the transaction, resets things that might have been modified,
    waits a random bit, and then calls the function again.

    It calls the function up to ``MAX_TRIES_ON_CONCURRENCY_FAILURE``
    (5) times. The time it waits between calls is random with an
    exponential backoff: ``random.uniform(0.0, 2 ** i)`` where ``i``
    is the number of the current attempt and starts at 1.

    :param func: The function to call; pass arguments using
        :func:`functools.partial`.
    :param env: The environment where the registry and the cursor
        are taken.
    """
    # Lazy import — see module docstring for the circular-import rationale.
    from odoo import http
    try:
        for tryno in range(1, MAX_TRIES_ON_CONCURRENCY_FAILURE + 1):
            tryleft = MAX_TRIES_ON_CONCURRENCY_FAILURE - tryno
            try:
                result = func()
                if not env.cr.closed:
                    env.cr.flush()  # submit the changes to the database
                break
            except (IntegrityError, OperationalError, ConcurrencyError) as exc:
                if env.cr.closed:
                    # ``closed`` (the property) covers both wrapper close and
                    # underlying connection death — ``_closed`` is the wrapper
                    # flag only and would silently retry on a dead PG conn,
                    # burning the random-backoff budget for no benefit. See
                    # ``BaseCursor.closed`` for the property definition.
                    raise
                with suppress(Exception):
                    env.cr.rollback()
                # Skip expensive reset if the connection is dead (e.g. after
                # DB drop): transaction.reset() would try to create a new
                # Registry which opens a cursor → 30s PoolTimeout on a
                # non-existent database.
                if not env.cr.closed:
                    with suppress(Exception):
                        env.transaction.reset()
                    with suppress(Exception):
                        env.registry.reset_changes()
                request = http.request
                if request:
                    _rewind_request_for_retry(request, exc)
                if isinstance(exc, IntegrityError):
                    if env.cr.closed:
                        # Connection died between the integrity error and
                        # rollback — can't query constraint details.
                        raise
                    raise _integrity_error_to_validation(env, exc) from exc

                if isinstance(exc, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY):
                    error = errors.lookup(exc.sqlstate).__name__
                elif isinstance(exc, ConcurrencyError):
                    error = repr(exc)
                else:
                    # Non-concurrency OperationalError: connection reset,
                    # statement timeout, disk full, etc. Log the class and
                    # sqlstate (if any) so operators can act on the raw cause
                    # instead of a bare psycopg traceback.
                    _logger.info(
                        "OperationalError not retryable: %s (sqlstate=%s)",
                        type(exc).__name__,
                        getattr(exc, "sqlstate", None),
                    )
                    raise
                if not tryleft:
                    _logger.info("%s, maximum number of tries reached!", error)
                    raise

                wait_time = random.uniform(0.0, 2**tryno)
                _logger.info(
                    "%s, %s tries left, try again in %.04f sec...",
                    error,
                    tryleft,
                    wait_time,
                )
                time.sleep(wait_time)
        else:
            # handled in the "if not tryleft" case
            msg = "unreachable"
            raise RuntimeError(msg)

    except Exception:
        if not env.cr.closed:
            with suppress(Exception):
                env.transaction.reset()
            with suppress(Exception):
                env.registry.reset_changes()
        raise

    # The commit runs in its OWN guarded block, deliberately NOT inside the
    # retry loop.  A failure here (a DEFERRED-constraint ``IntegrityError`` that
    # fires at COMMIT, a failing post-commit hook, a dropped connection) must
    # NOT re-run ``func``: the statements already committed — or post-commit
    # hooks already ran — so a retry would double their side effects.  But it
    # MUST still get the same rollback/reset cleanup as an in-loop failure
    # (otherwise the process-global registry keeps stale invalidation flags
    # that leak into the next request), and a commit-time ``IntegrityError``
    # gets the same friendly ``ValidationError`` translation the loop applies.
    try:
        if not env.cr.closed:
            env.cr.commit()  # effectively commits and execute post-commits
    except Exception as exc:
        if not env.cr.closed:
            with suppress(Exception):
                env.transaction.reset()
            with suppress(Exception):
                env.registry.reset_changes()
            if isinstance(exc, IntegrityError):
                # Best-effort: build the translation under ``suppress`` so a
                # failure inside it (dead cursor, missing diag) falls through
                # to the raw error instead of masking it with a second crash.
                translated = None
                with suppress(Exception):
                    translated = _integrity_error_to_validation(env, exc)
                if translated is not None:
                    raise translated from exc
        raise
    env.registry.signal_changes()
    return result


__all__ = (
    "MAX_TRIES_ON_CONCURRENCY_FAILURE",
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "retrying",
)
