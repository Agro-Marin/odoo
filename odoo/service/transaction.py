"""Project-wide SQL serialization-retry primitive.

``retrying()`` runs a callable in a loop, retrying on PostgreSQL serialization
/ lock-not-available failures with exponential backoff.  It is HTTP-aware
(rewinds uploaded files and refreshes the session/dbname when called inside a
request) but the core mechanism is general; callers live in ``service.model``
(RPC dispatch), ``odoo.http``, and ``bus.websocket``.
"""

from __future__ import annotations

import logging
import random
import time
import typing
from contextlib import suppress

from psycopg import IntegrityError, OperationalError, errors

from odoo.db.errors import PG_RETRY_EXCEPTIONS, PG_RETRY_SQLSTATES
from odoo.exceptions import ConcurrencyError, ValidationError

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")

PG_CONCURRENCY_ERRORS_TO_RETRY = PG_RETRY_SQLSTATES
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = PG_RETRY_EXCEPTIONS
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5

MAX_CONCURRENCY_BACKOFF_SECONDS = 2.0


def _integrity_error_to_validation(
    env: Environment, exc: IntegrityError
) -> ValidationError:
    """Map a psycopg ``IntegrityError`` to a user-facing ``ValidationError``.

    Names the offending model by matching ``exc.diag.table_name`` in the
    registry, then formats via its ``_sql_error_to_message``.  Shared by the
    in-loop and commit-time handlers so the two translations can't drift (a
    deferred constraint fires at COMMIT, outside the loop).
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


def _refresh_request_session(request: typing.Any) -> None:
    """Re-fetch the session of an in-flight HTTP request after a failed attempt.

    Runs on EVERY failure path (retry or raise): the rolled-back attempt may
    have mutated the in-memory session (e.g. set ``session.uid`` before the
    failing write), and the http layer persists a modified session even on an
    error response — so without this re-fetch those mutations outlive the
    rollback.

    Keyed on the session's *current* sid rather than the request cookie's.  The
    handler runs to completion before ``env.cr.flush()`` issues its buffered
    writes, so a login/MFA/logout has already rotated and persisted the session
    by the time a serialization failure lands here — and a hard rotation unlinks
    the file the cookie still names.  Re-reading by the cookie would find
    nothing, mint a fresh anonymous session, and log out a user who had just
    authenticated successfully.
    """
    current_sid = getattr(request.session, "sid", None)
    request.session = request._get_session_and_dbname(sid=current_sid)[0]


def _rewind_request_files_for_retry(request: typing.Any, exc: BaseException) -> None:
    """Rewind every uploaded file to offset 0 before replaying the handler.

    Retry-path only: a retry re-runs the handler, which re-reads the request
    body, so the uploads must be rewound first.  A non-seekable upload can't be
    replayed and raises here — which is why this must NOT run on the raise paths
    (nothing re-reads the files there, and it would mask the real error).

    Delegates to :func:`odoo.http.helpers.rewind_uploaded_files`, shared with the
    RO→RW cursor-upgrade path so multi-file handling can't diverge.  Imported
    lazily (``odoo.http`` pulls in this module — top-level import would cycle).
    """
    from odoo.http.helpers import rewind_uploaded_files

    rewind_uploaded_files(request.httprequest, cause=exc)


def _reset_request_for_retry(request: typing.Any) -> None:
    """Undo the aborted attempt's in-request side effects before replaying it.

    Retry-path only, and for the same reason as the rewind above: the handler is
    about to run a *second* time and must start where the first one did.  The
    rolled-back attempt may have escalated the environment
    (``request.update_env(su=True)`` survives every ``ir.http._auth_method_*``)
    or staged response headers — ``Set-Cookie`` accumulates, so a cookie set
    before the failing write would be emitted once per attempt.

    Delegates to :meth:`odoo.http.Request._reset_for_replay`, the same primitive
    the RO→RW cursor upgrade uses, so the two replay paths cannot drift.  Guarded
    because ``retrying`` also serves non-HTTP callers (``bus.websocket`` passes a
    websocket request object that has no such method).
    """
    reset = getattr(request, "_reset_for_replay", None)
    if reset is not None:
        reset()


def _reset_env_state(env: Environment) -> None:
    """Roll back the process-global registry/transaction bookkeeping after a
    failed attempt, so stale invalidation flags don't leak into the next request.

    No-op on a closed cursor: a dead connection (e.g. dropped DB) can't open the
    fresh cursor the resets need, and would block on a 30 s ``PoolTimeout``.
    Each reset is suppressed independently so one failure doesn't skip the other
    or mask the exception being handled.  Shared by :func:`retrying`'s three
    failure paths (in-loop, outer, commit-time) so they can't drift.
    """
    if env.cr.closed:
        return
    with suppress(Exception):
        env.transaction.reset()
    with suppress(Exception):
        env.registry.reset_changes()


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
    exponential backoff: ``random.uniform(0.0, min(2 ** i,
    MAX_CONCURRENCY_BACKOFF_SECONDS))`` (a 2.0 s ceiling) where ``i``
    is the number of the current attempt and starts at 1.

    :param func: The function to call; pass arguments using
        :func:`functools.partial`.
    :param env: The environment where the registry and the cursor
        are taken.
    """
    from odoo import http

    try:
        for tryno in range(1, MAX_TRIES_ON_CONCURRENCY_FAILURE + 1):
            tryleft = MAX_TRIES_ON_CONCURRENCY_FAILURE - tryno
            try:
                result = func()
                if not env.cr.closed:
                    env.cr.flush()
                break
            except (IntegrityError, OperationalError, ConcurrencyError) as exc:
                if env.cr.closed:
                    raise
                with suppress(Exception):
                    env.cr.rollback()
                _reset_env_state(env)
                request = http.request
                if request:
                    _refresh_request_session(request)
                if isinstance(exc, IntegrityError):
                    if env.cr.closed:
                        raise
                    raise _integrity_error_to_validation(env, exc) from exc

                if isinstance(exc, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY):
                    error = errors.lookup(exc.sqlstate).__name__
                elif isinstance(exc, ConcurrencyError):
                    error = repr(exc)
                else:
                    _logger.info(
                        "OperationalError not retryable: %s (sqlstate=%s)",
                        type(exc).__name__,
                        getattr(exc, "sqlstate", None),
                    )
                    raise
                if not tryleft:
                    _logger.info("%s, maximum number of tries reached!", error)
                    raise

                if request:
                    _rewind_request_files_for_retry(request, exc)
                    _reset_request_for_retry(request)
                wait_time = random.uniform(
                    0.0, min(2**tryno, MAX_CONCURRENCY_BACKOFF_SECONDS)
                )
                _logger.info(
                    "%s, %s tries left, try again in %.04f sec...",
                    error,
                    tryleft,
                    wait_time,
                )
                time.sleep(wait_time)
    except Exception:
        _reset_env_state(env)
        raise

    if env.cr.closed:
        # Nothing to commit — the connection is already back in the pool, so
        # skipping is right and committing would raise. Saying so is the point:
        # the handler ran, whatever it wrote is gone, and this returns its
        # result normally, so without this line the caller sees an ordinary
        # success and an uncommitted transaction with nothing to distinguish it.
        _logger.warning(
            "retrying(): the cursor was closed before commit; %s's work was "
            "NOT committed and no registry signal was sent. The handler closed "
            "its own cursor, or something else did.",
            getattr(func, "__qualname__", func),
        )
        return result

    commits_before = env.cr.commit_count
    try:
        env.cr.commit()
    except Exception as exc:
        # Distinguish "the COMMIT failed" from "the COMMIT succeeded and a
        # post-commit hook raised": Cursor.commit does both behind one call.
        # Treating the second as the first rolls the local registry back to a
        # pre-change state the database has already accepted, AND skips
        # signal_changes() — so every *other* worker keeps serving a stale
        # registry and ormcache for a committed change, with nothing recording
        # that it happened.
        durable = env.cr.commit_count > commits_before
        if durable:
            with suppress(Exception):
                env.registry.signal_changes()
        else:
            _reset_env_state(env)
            if not env.cr.closed and isinstance(exc, IntegrityError):
                translated = None
                with suppress(Exception):
                    translated = _integrity_error_to_validation(env, exc)
                if translated is not None:
                    raise translated from exc
        raise
    if not env.cr.closed:
        env.registry.signal_changes()
    return result


__all__ = (
    "MAX_CONCURRENCY_BACKOFF_SECONDS",
    "MAX_TRIES_ON_CONCURRENCY_FAILURE",
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "retrying",
)
