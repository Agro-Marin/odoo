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

    Every failure path collapses to the same ``False`` so an unauthenticated
    caller cannot use the exception type to enumerate which databases exist or
    are Odoo-initialized:

    * **Missing DB** — ``Registry(db)`` raises ``PoolError`` (or
      ``psycopg.OperationalError`` on pool-bypassing paths).
    * **Existing-but-not-Odoo DB** — ``res.users`` absent from the registry, so
      ``env["res.users"]`` would raise a telltale ``KeyError``.
    * **Empty / non-string DB name** — ``db_connect`` does not validate it; a
      blank name surfaces as a ``PoolError`` from the pool.
    * **Malformed ``user_agent_env``** — non-dict raises ``TypeError`` from
      ``{**user_agent_env, ...}``.

    The pool (``odoo.db.pool.borrow``) wraps every ``getconn`` failure in
    ``PoolError``; ``psycopg.OperationalError`` covers the direct-connect paths
    used by ``neutralize`` and migrate scripts.
    """
    # Reject malformed inputs upfront so the no-leak invariant holds without a
    # blanket ``except Exception`` (which would mask programming errors): a
    # non-str ``db`` / ``user_agent_env`` would otherwise leak an
    # AssertionError / TypeError distinguishable from AccessDenied.
    if not isinstance(db, str) or not db:
        return False
    if not isinstance(login, str) or not isinstance(password, str):
        # Left unchecked, a non-str login/password can raise a non-AccessDenied
        # type from deep inside ``authenticate``, breaking the invariant above.
        return False
    if user_agent_env is None:
        user_agent_env = {}
    elif not isinstance(user_agent_env, dict):
        return False
    try:
        registry = Registry(db)
    except (psycopg.OperationalError, PoolError):
        _logger.debug(
            "exp_authenticate: registry unavailable for %r", db, exc_info=True
        )
        return False
    # ``Registry(db)`` succeeds for any PG database that opens, including
    # non-Odoo ones (``postgres``, ``template1``, ...).  The explicit membership
    # check keeps ``env["res.users"]`` from raising a telltale ``KeyError`` that
    # would distinguish "exists but not Odoo" from "doesn't exist".
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
            # ``interactive=False`` MUST come after the ``**user_agent_env``
            # unpack (later keys win) so a caller cannot pass ``interactive=True``
            # and trigger MFA prompts with no client to satisfy them.
            return env["res.users"].authenticate(
                credential, {**user_agent_env, "interactive": False}
            )["uid"]
        except AccessDenied:
            return False


def exp_version() -> dict[str, Any]:
    """Return the RPC version information dict.

    A fresh shallow copy, since ``RPC_VERSION_1`` is a mutable module global a
    downstream serializer/middleware could otherwise corrupt for later callers.
    """
    return dict(RPC_VERSION_1)


def dispatch(method: str, params: list | tuple) -> Any:
    """Dispatch a common-service RPC call to the matching exposed function.

    Only methods in the ``_DISPATCH`` allowlist are reachable — an ``exp_``
    helper is not automatically an RPC endpoint, so a debug helper can't be
    exposed to unauthenticated clients by accident.

    Unknown methods raise ``AttributeError``, matching
    ``odoo.service.db.dispatch`` and ``odoo.service.model.dispatch``.
    """
    handler = _DISPATCH.get(method)
    if handler is None:
        raise AttributeError(f"Method not found: {method}")
    return handler(*params)


# Public allowlist: explicit is safer than reflection.  ``db.py`` uses the same
# pattern (plus ``_REQUIRES_MASTER_PASSWORD`` for its admin-only methods).
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
