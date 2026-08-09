from __future__ import annotations

import logging
import time
import typing
from contextlib import suppress

from psycopg import IntegrityError, OperationalError, errors

from odoo.db.errors import PG_RETRY_EXCEPTIONS, PG_RETRY_SQLSTATES
from odoo.exceptions import ConcurrencyError, ValidationError
from odoo.libs import backoff

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")

#: Addon-facing aliases for the canonical vocabulary in ``odoo.db.errors``.
#: Not dead re-exports: ``addons/mail`` reads both, and three ``enterprise``
#: modules import the exception tuple through ``odoo.service.model``, which
#: re-exports them in turn. ``test_db_cursor`` pins them as the same objects.
PG_CONCURRENCY_ERRORS_TO_RETRY = PG_RETRY_SQLSTATES
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = PG_RETRY_EXCEPTIONS
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5

BASE_CONCURRENCY_BACKOFF_SECONDS = 0.2
"""Ceiling for the first retry's wait; doubled per attempt up to the cap below.

Without a base term the cap wins from attempt 1 (``2 ** 1 >= 2.0``) and every
retry draws from the same interval, which is what this loop did until 2026-08-08.
See :mod:`odoo.libs.backoff`.
"""

MAX_CONCURRENCY_BACKOFF_SECONDS = 2.0


def _integrity_error_to_validation(
    env: Environment, exc: IntegrityError
) -> ValidationError:
    # Indexed lookup, not a scan over every model in the registry: this runs
    # while a user waits for an error message, and the registry holds 154
    # models with `base` alone -- thousands with a real addon set.
    rclass = env.registry.models_by_table.get(exc.diag.table_name)
    model = env[rclass._name] if rclass is not None else env["base"]
    message = env._(
        "The operation cannot be completed: %s",
        model._sql_error_to_message(exc),
    )
    return ValidationError(message)


@typing.runtime_checkable
class RetryParticipant(typing.Protocol):
    """Transport state that must be restored when a handler is replayed.

    ``retrying()`` is a *transaction* primitive, but a handler it re-runs may
    have consumed transport-level state that a second run needs back: an HTTP
    request has a session to refresh and uploaded file streams to rewind, and
    knows whether an uncommitted-cursor warning would be noise.

    Until 2026-08-09 this module did those three things itself, reaching
    ``odoo.http`` through two function-level imports and a thread-local. That
    was the ENTIRE ``service`` -> ``http`` coupling outside
    ``service/lifecycle.py``, concentrated in the one primitive
    ``ARCHITECTURE.md`` holds up as transport-independent, and it made the RPC
    path opt out only implicitly -- by ``http.request`` being falsy.

    The transport now supplies its own participant through
    :data:`current_retry_participant`, the same injection shape ``db/`` uses
    for the flushing savepoint (ADR-0003).
    """

    def on_rollback(self, exc: BaseException) -> None:
        """After the transaction is rolled back, for *every* caught error.

        Runs even when the error will not be retried -- an IntegrityError still
        needs a usable session to render its response.
        """

    def on_retry(self, exc: BaseException) -> None:
        """Just before the backoff sleep, only when the handler will re-run."""

    def suppresses_uncommitted_warning(self) -> bool:
        """Whether "cursor closed before commit" is expected rather than a bug."""


def _no_participant() -> RetryParticipant | None:
    return None


#: Resolves the participant for the work in flight, or ``None``.
#:
#: ``odoo.http`` overwrites this at import time. Anything that is not served
#: over a transport -- ``service/model.py``'s RPC dispatch, a cron job -- leaves
#: it returning ``None`` and gets a pure transaction retry, which is what it
#: always got, now by declaration rather than by a falsy thread-local.
current_retry_participant: Callable[[], RetryParticipant | None] = _no_participant


def _reset_env_state(env: Environment) -> None:
    if env.cr.closed:
        return
    with suppress(Exception):
        env.transaction.reset()
    with suppress(Exception):
        env.registry.reset_changes()


def _warn_cursor_closed_before_commit(
    func: Callable[..., object], participant: RetryParticipant | None
) -> None:
    """Warn that ``func`` closed its own cursor, so nothing was committed."""
    if participant is not None and participant.suppresses_uncommitted_warning():
        return
    _logger.warning(
        "retrying(): the cursor was closed before commit; %s's work was "
        "NOT committed and no registry signal was sent. The handler closed "
        "its own cursor, or something else did.",
        getattr(func, "__qualname__", func),
    )


def _commit_and_signal(env: Environment) -> None:
    """Commit the transaction and signal the registry.

    A commit that raises may still have been durable -- the failure can come
    from the signalling that follows it -- so the two cases are told apart by
    the cursor's commit counter rather than by the exception alone. When the
    work did not land, an IntegrityError is translated to the ValidationError a
    user can act on, exactly as the retry loop does.
    """
    commits_before = env.cr.commit_count
    try:
        env.cr.commit()
    except Exception as exc:
        if env.cr.commit_count > commits_before:
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
    elif env.cr.commit_count > commits_before:
        with suppress(Exception):
            env.registry.signal_changes()


def retrying[T](func: Callable[[], T], env: Environment) -> T:
    participant = current_retry_participant()

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
                if participant is not None:
                    participant.on_rollback(exc)
                if isinstance(exc, IntegrityError):
                    if env.cr.closed:
                        raise
                    raise _integrity_error_to_validation(env, exc) from exc

                if isinstance(exc, PG_RETRY_EXCEPTIONS):
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

                if participant is not None:
                    participant.on_retry(exc)
                wait_time = backoff.delay(
                    tryno,
                    base=BASE_CONCURRENCY_BACKOFF_SECONDS,
                    cap=MAX_CONCURRENCY_BACKOFF_SECONDS,
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
        _warn_cursor_closed_before_commit(func, participant)
        return result

    _commit_and_signal(env)
    return result


__all__ = (
    "BASE_CONCURRENCY_BACKOFF_SECONDS",
    "MAX_CONCURRENCY_BACKOFF_SECONDS",
    "MAX_TRIES_ON_CONCURRENCY_FAILURE",
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "retrying",
)
