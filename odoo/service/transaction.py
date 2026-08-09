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
    current_sid = getattr(request.session, "sid", None)
    request.session = request._get_session_and_dbname(sid=current_sid)[0]


def _rewind_request_files_for_retry(request: typing.Any, exc: BaseException) -> None:
    from odoo.http.helpers import rewind_uploaded_files

    rewind_uploaded_files(request.httprequest, cause=exc)


def _reset_request_for_retry(request: typing.Any) -> None:
    reset = getattr(request, "_reset_for_replay", None)
    if reset is not None:
        reset()


def _reset_env_state(env: Environment) -> None:
    if env.cr.closed:
        return
    with suppress(Exception):
        env.transaction.reset()
    with suppress(Exception):
        env.registry.reset_changes()


def _warn_cursor_closed_before_commit(func: Callable[..., object]) -> None:
    """Warn that ``func`` closed its own cursor, so nothing was committed."""
    from odoo import http

    # `getattr` rather than attribute access: this runs on the tail of every
    # served request, and `request` is not always a real `Request` (tests
    # patch it, `borrow_request` swaps it). Missing the warning on such a
    # stand-in is a far smaller failure than raising from here.
    current_request = http.request
    if current_request and getattr(current_request, "database_detached", False):
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

                if request:
                    _rewind_request_files_for_retry(request, exc)
                    _reset_request_for_retry(request)
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
        _warn_cursor_closed_before_commit(func)
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
