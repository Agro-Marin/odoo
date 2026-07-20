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

# ``odoo.http`` is imported lazily inside ``retrying`` (``odoo.http._serve``
# imports ``retrying``, so a top-level import would cycle).

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")  # preserve operator log filters

# The retry vocabulary lives in ``odoo.db.errors`` (the lowest layer the cursor
# and this loop share) so the SQLSTATE and exception lists can't drift.  Aliased
# here because addons catch the same set via ``odoo.service.model``.
PG_CONCURRENCY_ERRORS_TO_RETRY = PG_RETRY_SQLSTATES
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = PG_RETRY_EXCEPTIONS
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5

# Ceiling (seconds) on any single inter-retry sleep.  The backoff stays
# exponential (``random.uniform(0, 2 ** tryno)``) but is capped so a late retry
# can't pin its pooled connection for the full 16 s.  ``env.cr`` holds a pool
# slot across the whole ``retrying`` call; under a serialization storm — exactly
# when retries fire — many workers sleeping on the uncapped tail saturate the
# pool and turn transient contention into a cluster-wide stall.  2 s keeps
# meaningful jitter while bounding the hold.
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
    """
    request.session = request._get_session_and_dbname()[0]


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
                    # ``closed`` (the property) covers both wrapper close and a
                    # dead underlying connection; retrying either would just burn
                    # the backoff budget.
                    raise
                with suppress(Exception):
                    env.cr.rollback()
                _reset_env_state(env)
                request = http.request
                if request:
                    # Session re-fetch on EVERY failure path; the upload rewind
                    # waits until a retry is certain (see both helpers).
                    _refresh_request_session(request)
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

                if request:
                    _rewind_request_files_for_retry(request, exc)
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

    # The commit runs in its OWN guarded block, NOT inside the retry loop: a
    # failure here (deferred-constraint ``IntegrityError`` at COMMIT, a failing
    # post-commit hook, a dropped connection) must not re-run ``func`` — the
    # statements/hooks already ran, so a retry would double their side effects.
    # It still gets the same rollback/reset cleanup and ``ValidationError``
    # translation an in-loop failure would.
    try:
        if not env.cr.closed:
            env.cr.commit()  # effectively commits and execute post-commits
    except Exception as exc:
        _reset_env_state(env)
        if not env.cr.closed and isinstance(exc, IntegrityError):
            # Build the translation under ``suppress`` so a failure inside it
            # (dead cursor, missing diag) falls through to the raw error.
            translated = None
            with suppress(Exception):
                translated = _integrity_error_to_validation(env, exc)
            if translated is not None:
                raise translated from exc
        raise
    # When the cursor is closed the commit above was skipped, so the transaction
    # never landed; signalling invalidation would broadcast a cluster-wide
    # reload for a change that was never committed.
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
