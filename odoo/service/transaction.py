from __future__ import annotations

import logging
import time
import typing
from contextlib import suppress

from psycopg import IntegrityError, OperationalError, errors

from odoo.db.errors import (
    PG_RETRY_EXCEPTIONS,
    PG_RETRY_SQLSTATES,
    PG_STALE_PLAN_EXCEPTIONS,
    is_stale_cached_plan,
)
from odoo.exceptions import ConcurrencyError, ValidationError
from odoo.libs import backoff

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment

_logger = logging.getLogger("odoo.service.model")

PG_CONCURRENCY_ERRORS_TO_RETRY = PG_RETRY_SQLSTATES
PG_CONCURRENCY_EXCEPTIONS_TO_RETRY = PG_RETRY_EXCEPTIONS
MAX_TRIES_ON_CONCURRENCY_FAILURE = 5

BASE_CONCURRENCY_BACKOFF_SECONDS = 0.2

MAX_CONCURRENCY_BACKOFF_SECONDS = 2.0


def _integrity_error_to_validation(
    env: Environment, exc: IntegrityError
) -> ValidationError:
    rclass = env.registry.models_by_table.get(exc.diag.table_name)
    model = env[rclass._name] if rclass is not None else env["base"]
    message = env._(
        "The operation cannot be completed: %s",
        model._sql_error_to_message(exc),
    )
    return ValidationError(message)


class RetryParticipant(typing.Protocol):
    """Structural type only: nothing in the tree does ``isinstance`` against it.

    ``current_retry_participant()`` returns either a participant or ``None``, and
    both call sites (`retrying`, `_warn_cursor_closed_before_commit`) branch on
    ``is not None``.  The one real implementer, ``odoo.http._retry``'s
    ``RequestRetryParticipant``, does not inherit from this Protocol either.
    """

    def on_rollback(self, exc: BaseException) -> None: ...

    def on_retry(self, exc: BaseException) -> None: ...

    def suppresses_uncommitted_warning(self) -> bool: ...


def _no_participant() -> RetryParticipant | None:
    return None


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
    if participant is not None and participant.suppresses_uncommitted_warning():
        return
    _logger.warning(
        "retrying(): the cursor was closed before commit; %s's work was "
        "NOT committed and no registry signal was sent. The handler closed "
        "its own cursor, or something else did.",
        getattr(func, "__qualname__", func),
    )


def _commit_and_signal(env: Environment) -> None:
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
            except (
                IntegrityError,
                OperationalError,
                ConcurrencyError,
                *PG_STALE_PLAN_EXCEPTIONS,
            ) as exc:
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
                elif is_stale_cached_plan(exc):
                    error = "StaleCachedPlan"
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
