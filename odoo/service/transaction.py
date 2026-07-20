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

# ``odoo.http`` is imported lazily inside ``retrying`` (not at module top):
# ``odoo.http._serve`` imports ``retrying`` from here, so a top-level import
# would cycle during ``odoo.http`` package init.  ``retrying`` only runs at
# request time, so the per-call lookup is free.

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")  # preserve operator log filters

# The retry vocabulary is defined once in ``odoo.db.errors`` (the lowest layer
# the cursor and this loop share) so the SQLSTATE list and the exception list
# cannot drift apart.  These public aliases are kept because addons catch the
# same set, importing them via ``odoo.service.model``.
PG_CONCURRENCY_ERRORS_TO_RETRY = PG_RETRY_SQLSTATES
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = PG_RETRY_EXCEPTIONS
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5

# Upper bound (seconds) on any single inter-retry sleep.  The backoff stays
# exponential — ``random.uniform(0, 2 ** tryno)`` — but the range is capped so a
# late retry cannot pin its connection for the full ``2 ** 4 == 16`` s.  In the
# RPC path ``env.cr`` is a connection borrowed from the pool for the whole
# ``retrying`` call (``service.model.dispatch``'s ``with registry.cursor()``);
# the rollback between attempts frees the transaction's *locks* but not the pool
# *slot*.  Under a serialization-failure storm — precisely when retries fire —
# many workers sleeping on the uncapped tail saturate the pool and turn transient
# contention into a cluster-wide stall.  A 2 s ceiling keeps meaningful jitter
# (still decorrelates the thundering herd) while bounding the hold.
MAX_CONCURRENCY_BACKOFF_SECONDS = 2.0


def _integrity_error_to_validation(
    env: Environment, exc: IntegrityError
) -> ValidationError:
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


def _refresh_request_session(request: typing.Any) -> None:
    """Re-fetch the session of an in-flight HTTP request after a failed attempt.

    Runs on EVERY failure path — retry or raise — because the rolled-back
    attempt may have mutated the in-memory session (e.g. a login handler that
    set ``session.uid`` before the failing write): the http layer persists a
    modified session even when the response is an error, so without this
    re-fetch those transaction-coupled mutations would outlive the rollback.
    """
    request.session = request._get_session_and_dbname()[0]


def _rewind_request_files_for_retry(request: typing.Any, exc: BaseException) -> None:
    """Rewind every uploaded file to offset 0 before replaying the handler.

    Retry-path only: a retry re-runs the handler from the top, which re-reads
    the request body — without the rewind the replay reads a partially-consumed
    stream.  A non-seekable upload cannot be replayed, so this raises; that is
    why it must NOT run on the raise paths (IntegrityError → ValidationError,
    non-retryable OperationalError, retries exhausted), where it would mask the
    real error with a spurious ``RuntimeError`` for no benefit — nothing
    re-reads the files there.

    Delegates to :func:`odoo.http.helpers.rewind_uploaded_files` — the single
    primitive also used by the RO→RW cursor-upgrade path
    (``_serve._rewind_input_files``), so the ``multi=True`` handling of
    same-field-name multi-file uploads cannot diverge between the two.  Imported
    lazily for the same reason ``retrying`` imports ``http`` lazily: ``odoo.http``
    pulls in this module, so a top-level import would cycle.
    """
    from odoo.http.helpers import rewind_uploaded_files

    rewind_uploaded_files(request.httprequest, cause=exc)


def _reset_env_state(env: Environment) -> None:
    """Roll back the process-global registry/transaction bookkeeping after a
    failed attempt, so its stale invalidation flags don't leak into the next
    request.

    No-op when the cursor is closed: a dead connection (e.g. after the DB was
    dropped) can't open the fresh cursor ``transaction.reset`` /
    ``registry.reset_changes`` need — attempting it would block on a 30s
    ``PoolTimeout`` against a non-existent database.  Each reset is suppressed
    independently so a failure in one still runs the other and neither masks
    the exception being handled.

    Single source of truth: :func:`retrying` resets on the in-loop failure, the
    outer failure, and the commit-time failure, and the three must not drift.
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
                    # ``closed`` (the property) covers both wrapper close and
                    # underlying connection death — ``_closed`` is the wrapper
                    # flag only and would silently retry on a dead PG conn,
                    # burning the random-backoff budget for no benefit. See
                    # ``BaseCursor.closed`` for the property definition.
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
        _reset_env_state(env)
        if not env.cr.closed and isinstance(exc, IntegrityError):
            # Best-effort: build the translation under ``suppress`` so a
            # failure inside it (dead cursor, missing diag) falls through
            # to the raw error instead of masking it with a second crash.
            translated = None
            with suppress(Exception):
                translated = _integrity_error_to_validation(env, exc)
            if translated is not None:
                raise translated from exc
        raise
    # Same ``if not env.cr.closed`` guard the commit (and the in-loop
    # rollback/reset) carry: when the cursor is closed the commit above was
    # skipped, so the transaction never landed.  Signalling cache/registry
    # invalidation here would broadcast a cluster-wide reload for a change that
    # was never committed — spurious work, and an inconsistency with the very
    # guard this function applies everywhere else.
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
