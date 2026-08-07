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
    return exp_authenticate(db, login, password, None)


def exp_authenticate(
    db: str,
    login: str,
    password: str,
    user_agent_env: dict | None,
) -> int | bool:
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
    return dict(RPC_VERSION_1)


def dispatch(method: str, params: list | tuple) -> Any:
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
