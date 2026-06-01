import logging
from collections.abc import Callable
from typing import Any

import psycopg

import odoo.release
from odoo.db import PoolError
from odoo.exceptions import AccessDenied
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

RPC_VERSION_1: dict[str, Any] = {
    "server_version": odoo.release.version,
    "server_version_info": odoo.release.version_info,
    "server_serie": odoo.release.serie,
    "protocol_version": 1,
}


def exp_login(db: str, login: str, password: str) -> int | bool:
    """Authenticate via login/password and return the user id or False."""
    return exp_authenticate(db, login, password, None)


def exp_authenticate(
    db: str,
    login: str,
    password: str,
    user_agent_env: dict | None,
) -> int | bool:
    """Authenticate a user and return the uid, or False on failure.

    Every failure path collapses into the same ``False`` return so that an
    unauthenticated caller cannot enumerate which databases exist or which
    of them are Odoo-initialized via the exception type.  The leaks the
    earlier implementation produced and that this version closes:

    * **Missing DB** — ``Registry(db)`` raises ``PoolError`` (or
      ``psycopg.OperationalError`` for code paths bypassing the pool).
      Always returned False, but only after commit ``02a118d`` widened the
      catch beyond the original psycopg-only form.
    * **Existing-but-not-Odoo DB** — accessing ``env["res.users"]`` raises
      ``KeyError`` because ``res.users`` isn't in the registry.  The earlier
      catch missed it; the DB's existence leaked via an exception type
      distinct from ``AccessDenied``.
    * **Empty / non-string DB name** — ``odoo.db.db_connect`` asserts the
      name is non-empty and raises ``AssertionError`` otherwise.  The
      earlier catch propagated it.
    * **Malformed ``user_agent_env``** — non-dict, non-None values
      (lists-of-tuples from a misbehaving client, etc.) raised ``TypeError``
      from ``{**user_agent_env, ...}``.  Same leak class.

    The pool layer (``odoo.db.pool.borrow``) wraps every ``getconn`` failure
    in ``PoolError``: missing DB, dead PG, bad credentials, semaphore
    saturation.  ``psycopg.OperationalError`` is kept for direct-connect
    paths used by ``neutralize`` and migrate scripts.
    """
    # Reject malformed inputs upfront so the no-leak invariant holds without
    # a blanket ``except Exception`` (which would mask programming errors).
    # Each rejected case maps to a leak that the previous implementation
    # produced:
    #   * empty/non-string ``db``       — leaked AssertionError from db_connect
    #   * non-dict ``user_agent_env``   — leaked TypeError from {**env, ...}
    if not isinstance(db, str) or not db:
        return False
    if user_agent_env is None:
        user_agent_env = {}
    elif not isinstance(user_agent_env, dict):
        return False
    try:
        registry = Registry(db)
    except psycopg.OperationalError, PoolError:
        _logger.debug(
            "exp_authenticate: registry unavailable for %r", db, exc_info=True
        )
        return False
    # ``Registry(db)`` succeeds for any PG database that opens — including
    # non-Odoo databases (``postgres``, ``template1``, a Rails app's DB).
    # Without an explicit membership check, ``env["res.users"]`` would raise
    # ``KeyError`` on those, distinguishing "DB exists but isn't Odoo" from
    # "DB doesn't exist" via exception type.  Collapse both to ``False``.
    if "res.users" not in registry.models:
        _logger.debug(
            "exp_authenticate: %r is reachable but not an Odoo database", db
        )
        return False
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, None, {})
        env.transaction.default_env = env  # force default_env
        try:
            credential = {
                "login": login,
                "password": password,
                "type": "password",
            }
            # ``interactive=False`` MUST come AFTER the ``**user_agent_env``
            # unpack so a malicious caller cannot pass ``interactive=True``
            # and trigger interactive MFA prompts that have no client to
            # satisfy them. Python dict-merge order: later keys win.
            return env["res.users"].authenticate(
                credential, {**user_agent_env, "interactive": False}
            )["uid"]
        except AccessDenied:
            return False


def exp_version() -> dict[str, Any]:
    """Return the RPC version information dict."""
    return RPC_VERSION_1


def dispatch(method: str, params: list | tuple) -> Any:
    """Dispatch a common-service RPC call to the matching exposed function.

    Only methods present in ``_DISPATCH`` are reachable. A module-level helper
    named ``exp_foo`` is NOT automatically an RPC endpoint: the allowlist is
    the single source of truth, which prevents a future maintainer from
    accidentally exposing a debug helper (or any other ``exp_``-prefixed
    function) to unauthenticated XML-RPC clients.

    Unknown methods raise ``AttributeError`` — matching the exception type
    raised by ``odoo.service.db.dispatch`` and ``odoo.service.model.dispatch``.
    """
    handler = _DISPATCH.get(method)
    if handler is None:
        raise AttributeError(f"Method not found: {method}")
    return handler(*params)


# Public allowlist: explicit is safer than reflection.
# `db.py` uses the same pattern (``_DISPATCH_PUBLIC``/``_DISPATCH_ADMIN``).
_DISPATCH: dict[str, Callable] = {
    "login": exp_login,
    "authenticate": exp_authenticate,
    "version": exp_version,
}


__all__ = (
    "RPC_VERSION_1",
    "dispatch",
    "exp_authenticate",
    "exp_login",
    "exp_version",
)
