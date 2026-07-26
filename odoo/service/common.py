import logging
from collections.abc import Callable
from typing import Any

import psycopg

import odoo.release
from odoo.db import PoolError
from odoo.exceptions import AccessDenied
from odoo.modules.registry import Registry

from ._db_helpers import rpc_db_exposed

_logger = logging.getLogger(__name__)

_EXPECTED_CONNECT_FAILURES: tuple[type[BaseException], ...] = (
    psycopg.OperationalError,
    psycopg.errors.InvalidCatalogName,
    PoolError,
)

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

    * **Missing DB** — ``Registry(db)`` raises from the pool's connect path.
    * **Existing-but-not-Odoo DB** — ``res.users`` absent from the registry, so
      ``env["res.users"]`` would raise a telltale ``KeyError``.
    * **Empty / non-string DB name** — ``db_connect`` does not validate it; a
      blank name surfaces as a ``PoolError`` from the pool.
    * **Malformed ``user_agent_env``** — non-dict raises ``TypeError`` from
      ``{**user_agent_env, ...}``.

    The connect-failure arm catches ``psycopg.Error``, NOT the narrower
    ``psycopg.OperationalError`` it once did.  ``odoo.db.pool`` deliberately
    *translates* a connect-phase failure into the precise SQLSTATE class
    (``_probe_connectable`` / ``_database_absent``), and the one that matters
    here — ``InvalidCatalogName``, "database does not exist" — is a
    ``ProgrammingError``, not an ``OperationalError``.  So an absent database
    used to propagate out of this function as an RPC Fault while an existing one
    returned ``False``: a per-name existence oracle on an ``auth="none"`` verb
    (``/jsonrpc``, ``/xmlrpc/common``), which is exactly the invariant above.
    Measured before this change: absent -> ``InvalidCatalogName``; existing
    non-Odoo -> ``False``; existing Odoo -> ``False``.  Catching the whole
    ``psycopg.Error`` tree keeps the invariant from silently regressing again
    the next time the pool classifies an error more precisely.
    """
    if not isinstance(db, str) or not db:
        return False
    if not isinstance(login, str) or not isinstance(password, str):
        return False
    if user_agent_env is None:
        user_agent_env = {}
    elif not isinstance(user_agent_env, dict):
        return False
    if not rpc_db_exposed(db):
        return False
    try:
        registry = Registry(db)
    except (psycopg.Error, PoolError) as exc:
        if isinstance(exc, _EXPECTED_CONNECT_FAILURES):
            _logger.debug(
                "exp_authenticate: registry unavailable for %r", db, exc_info=True
            )
        else:
            _logger.warning(
                "exp_authenticate: unexpected database error for %r; answering "
                "False to keep the RPC response uniform",
                db,
                exc_info=True,
            )
        return False
    if "res.users" not in registry.models:
        _logger.debug("exp_authenticate: %r is reachable but not an Odoo database", db)
        return False
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, None, {})
        env.transaction.default_env = env
        try:
            credential = {
                "login": login,
                "password": password,
                "type": "password",
            }
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
