from __future__ import annotations

import logging
import time
import typing
from contextlib import suppress

from psycopg import IntegrityError, OperationalError

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

_RECOVERY_EXCEPTIONS: tuple[type[Exception], ...] = (
    IntegrityError,
    OperationalError,
    ConcurrencyError,
    *PG_STALE_PLAN_EXCEPTIONS,
)


def _integrity_error_to_validation_error(
    env: Environment, exc: IntegrityError
) -> ValidationError:
    table_name = exc.diag.table_name
    rclass = env.registry.models_by_table.get(table_name) if table_name else None
    model = env[rclass._name] if rclass is not None else env["base"]
    message = env._(
        "The operation cannot be completed: %s",
        model._sql_error_to_message(exc),
    )
    return ValidationError(message)


class RetryParticipant(typing.Protocol):
    def on_rollback(self, exc: BaseException) -> None: ...

    def on_retry(self, exc: BaseException) -> None: ...

    def is_uncommitted_warning_suppressed(self) -> bool: ...


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
    if participant is not None and participant.is_uncommitted_warning_suppressed():
        return
    _logger.warning(
        "retrying(): the cursor was closed before commit; %s's work was "
        "NOT committed and no registry signal was sent. The handler closed "
        "its own cursor, or something else did.",
        getattr(func, "__qualname__", func),
    )


def _commit_and_signal_changes(env: Environment) -> None:
    commits_before = env.cr.commit_count
    try:
        env.cr.commit()
    except Exception:
        if env.cr.commit_count > commits_before:
            with suppress(Exception):
                env.registry.signal_changes()
        raise
    if not env.cr.closed:
        env.registry.signal_changes()
    elif env.cr.commit_count > commits_before:
        with suppress(Exception):
            env.registry.signal_changes()


def _rollback_transaction(env: Environment, exc: Exception) -> None:
    """Require successful recovery before allowing another attempt."""
    try:
        env.cr.rollback()
    except Exception as rollback_error:
        raise exc from rollback_error
    if env.cr.closed:
        raise exc
    env.transaction.reset()
    env.registry.reset_changes()


def _retry_error_name(exc: Exception) -> str | None:
    if isinstance(exc, PG_RETRY_EXCEPTIONS):
        return type(exc).__name__
    if isinstance(exc, ConcurrencyError):
        return repr(exc)
    if is_stale_cached_plan(exc):
        return "StaleCachedPlan"
    return None


def retrying[T](
    func: Callable[[], T],
    env: Environment,
    participant: RetryParticipant | None = None,
) -> T:
    commits_before = env.cr.commit_count
    try:
        for tryno in range(1, MAX_TRIES_ON_CONCURRENCY_FAILURE + 1):
            tryleft = MAX_TRIES_ON_CONCURRENCY_FAILURE - tryno
            try:
                result = func()
                if env.cr.closed:
                    _warn_cursor_closed_before_commit(func, participant)
                    break
                env.cr.flush()
                _commit_and_signal_changes(env)
                break
            except _RECOVERY_EXCEPTIONS as exc:
                if env.cr.closed or env.cr.commit_count > commits_before:
                    raise
                _rollback_transaction(env, exc)
                if participant is not None:
                    participant.on_rollback(exc)
                if isinstance(exc, IntegrityError):
                    if env.cr.closed:
                        raise
                    translated = None
                    with suppress(Exception):
                        translated = _integrity_error_to_validation_error(env, exc)
                    if translated is not None:
                        raise translated from exc
                    raise

                error = _retry_error_name(exc)
                if error is None:
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
        if env.cr.commit_count == commits_before:
            _reset_env_state(env)
        raise
    return result


__all__ = (
    "BASE_CONCURRENCY_BACKOFF_SECONDS",
    "MAX_CONCURRENCY_BACKOFF_SECONDS",
    "MAX_TRIES_ON_CONCURRENCY_FAILURE",
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "RetryParticipant",
    "retrying",
)
