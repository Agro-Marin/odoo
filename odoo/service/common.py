import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import psycopg

import odoo.api
import odoo.release
from odoo.db import PoolError
from odoo.exceptions import AccessDenied
from odoo.modules.registry import Registry

from ._db_helpers import rpc_db_exposed
from ._dispatch import dispatch_table

_logger = logging.getLogger(__name__)

_EXPECTED_CONNECT_FAILURES: tuple[type[BaseException], ...] = (
    psycopg.OperationalError,
    psycopg.errors.InvalidCatalogName,
    PoolError,
)


def _rpc_version_1() -> dict[str, Any]:
    """Build the version payload from ``odoo.release`` on every call.

    Built once at import instead, it froze whatever ``odoo.release`` happened to
    hold at that moment -- and addons patch ``odoo.release`` afterwards, so the
    payload silently disagreed with the module it claims to report.  That is why
    `enterprise/web_enterprise/version.py` had to re-apply its own edit to the
    dict by hand; building it here makes import order stop mattering.
    """
    return {
        "server_version": odoo.release.version,
        "server_version_info": odoo.release.version_info,
        "server_serie": odoo.release.serie,
        "protocol_version": 1,
    }


if TYPE_CHECKING:
    # Declared for static tooling only: the binding below is produced by the
    # module-level ``__getattr__``, which a type checker cannot see.
    RPC_VERSION_1: dict[str, Any]


def __getattr__(name: str) -> Any:
    # ``RPC_VERSION_1`` was a module-level dict and is public API, so the name
    # survives -- as a fresh, correct snapshot rather than a mutable global
    # whose contents depend on who imported what first.  Mutating the returned
    # dict no longer changes what `exp_version` answers, which is the point.
    if name == "RPC_VERSION_1":
        return _rpc_version_1()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def exp_login(db: str, login: str, password: str) -> int | bool:
    return exp_authenticate(db, login, password, None)


def exp_authenticate(
    db: str,
    login: str,
    password: str,
    user_agent_env: dict | None = None,
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
    return _rpc_version_1()


def dispatch(method: str, params: list | tuple) -> Any:
    return dispatch_table(method, params, _DISPATCH)


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
