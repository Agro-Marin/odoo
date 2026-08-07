import atexit
import logging
import threading

import odoo
from odoo import tools

from .budget import ConnectionBudget
from .cursor import BaseCursor, Cursor, Savepoint
from .savepoint import insert_or_existing
from .pool import Connection, ConnectionPool, PoolError
from .utils import (
    SYSTEM_DBS,
    categorize_query,
    connection_info_for,
    is_maintenance_db,
)

__all__ = [
    "SYSTEM_DBS",
    "BaseCursor",
    "Connection",
    "ConnectionBudget",
    "ConnectionPool",
    "Cursor",
    "PoolError",
    "Savepoint",
    "categorize_query",
    "close_all",
    "close_db",
    "connection_info_for",
    "db_connect",
    "drain_all",
    "drain_db",
    "insert_or_existing",
    "is_maintenance_db",
    "is_pooled",
    "pool_health",
    "sql_counter",  # noqa: F822  served by the module-level __getattr__ below
]

_logger = logging.getLogger(__name__)

_Pool: ConnectionPool | None = None
_Pool_readonly: ConnectionPool | None = None
_budgets: dict[tuple, ConnectionBudget] = {}
_pool_lock = threading.Lock()


def _endpoint_of(readonly: bool) -> tuple:
    _, info = connection_info_for("", readonly)
    return (info.get("host"), info.get("port"))


def _base_maxconn() -> int:
    return int(
        (
            tools.config["db_maxconn_gevent"]
            if hasattr(odoo, "evented") and odoo.evented
            else 0
        )
        or tools.config["db_maxconn"]
    )


def _maxconn_for(readonly: bool) -> int:
    base = _base_maxconn()
    if readonly and _endpoint_of(True) != _endpoint_of(False):
        return int(tools.config["db_maxconn_replica"] or base)
    return base


def _budget_for(readonly: bool) -> ConnectionBudget:
    key = _endpoint_of(readonly)
    budget = _budgets.get(key)
    if budget is None:
        budget = _budgets[key] = ConnectionBudget(_maxconn_for(readonly))
    return budget


def _get_pool(readonly: bool) -> ConnectionPool:
    global _Pool, _Pool_readonly  # noqa: PLW0603  the connection pools are process singletons by design
    pool = _Pool_readonly if readonly else _Pool
    if pool is None:
        with _pool_lock:
            pool = _Pool_readonly if readonly else _Pool
            if pool is None:
                minconn = tools.config["db_minconn"] or 0
                budget = _budget_for(readonly)
                pool = ConnectionPool(
                    budget.maxconn,
                    readonly=readonly,
                    minconn=int(minconn),
                    borrow_timeout=tools.config["db_borrow_timeout"],
                    max_lifetime=tools.config["db_conn_max_lifetime"],
                    max_idle=tools.config["db_conn_max_idle"],
                    reap_idle_ttl=tools.config["db_pool_reap_idle"],
                    budget=budget,
                )
                if readonly:
                    _Pool_readonly = pool
                else:
                    _Pool = pool
    return pool


def db_connect(to: str, allow_uri: bool = False, readonly: bool = False) -> Connection:
    db, info = connection_info_for(to, readonly)
    if not allow_uri and db != to:
        msg = "URI connections not allowed"
        raise ValueError(msg)
    return Connection(_get_pool(readonly), db, info)


def is_pooled(db_name: str) -> bool:
    return bool(
        (_Pool and _Pool.has_database(db_name))
        or (_Pool_readonly and _Pool_readonly.has_database(db_name))
    )


def pool_health() -> dict:
    return {
        "read_write": _Pool.health() if _Pool else None,
        "read_only": _Pool_readonly.health() if _Pool_readonly else None,
    }


def close_db(db_name: str) -> None:
    if _Pool:
        _Pool.close_database(db_name)
    if _Pool_readonly:
        _Pool_readonly.close_database(db_name)


def close_all() -> None:
    if _Pool:
        _Pool.close_all()
    if _Pool_readonly:
        _Pool_readonly.close_all()


atexit.register(close_all)


def drain_db(db_name: str) -> None:
    if _Pool:
        _Pool.drain_database(db_name)
    if _Pool_readonly:
        _Pool_readonly.drain_database(db_name)


def drain_all() -> None:
    if _Pool:
        _Pool.drain()
    if _Pool_readonly:
        _Pool_readonly.drain()


def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import metrics

        return metrics.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
