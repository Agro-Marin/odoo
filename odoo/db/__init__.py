import atexit
import logging
import os
import threading

import odoo
from odoo import tools

from .budget import ConnectionBudget
from .cursor import BaseCursor, Cursor, Savepoint
from .dsn import _expand_conninfo
from .schema import FunctionStatus, has_trigram, has_unaccent
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
    "ConnectionPool",
    "Cursor",
    "FunctionStatus",
    "PoolError",
    "Savepoint",
    "categorize_query",
    "close_all",
    "close_db",
    "connection_info_for",
    "db_connect",
    "drain_all",
    "drain_db",
    "has_trigram",
    "has_unaccent",
    "insert_or_existing",
    "is_maintenance_db",
    "is_pooled",
    "pool_health",
    "sql_counter",  # noqa: F822  served by the module-level __getattr__ below
]

_logger = logging.getLogger(__name__)

_DEFAULT_PG_PORT = 5432

_pools: dict[tuple, ConnectionPool] = {}
_budgets: dict[tuple, ConnectionBudget] = {}
_pool_lock = threading.RLock()


def _endpoint_key(info: dict) -> tuple[str | None, int]:
    if not info.get("dsn"):
        # The ordinary path: `connection_info_for` already put `db_host` and
        # `db_port` here when they have values, and omits them when they do
        # not -- which is the same "unset" the configured endpoint resolves to.
        # Nothing to default, so nothing to look up.
        return (info.get("host") or None, _port(info.get("port")))
    expanded = _expand_conninfo(info)
    # A URI supplies only what it spells. Default the rest from the config
    # rather than from `os.environ`: `db_host`/`db_port` are registered with
    # `env_name="PGHOST"`/`"PGPORT"` (tools/config.py), so the config has
    # already folded the environment in, and reading it again here would be a
    # second source of truth that misses a `db_host` set in the conf file --
    # the URI would resolve to `(None, …)` against the configured
    # `(thathost, …)` and be filed as a different server. Two `config[...]`
    # reads cost ~700 ns, which is why this branch is the URI's alone.
    host = expanded.get("host") or tools.config["db_host"] or None
    port = expanded.get("port") or tools.config["db_port"]
    return (host, _port(port))


def _port(port: object) -> int:
    try:
        return int(port)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return _DEFAULT_PG_PORT


def _endpoint_of(readonly: bool) -> tuple:
    _, info = connection_info_for("", readonly)
    return _endpoint_key(info)


def _base_maxconn() -> int:
    return int(
        (
            tools.config["db_maxconn_gevent"]
            if hasattr(odoo, "evented") and odoo.evented
            else 0
        )
        or tools.config["db_maxconn"]
    )


def _maxconn_at(endpoint: tuple) -> int:
    base = _base_maxconn()
    if endpoint != _endpoint_of(False) and endpoint == _endpoint_of(True):
        return int(tools.config["db_maxconn_replica"] or base)
    return base


def _maxconn_for(readonly: bool) -> int:
    return _maxconn_at(_endpoint_of(readonly))


def _budget_at(endpoint: tuple) -> ConnectionBudget:
    with _pool_lock:
        budget = _budgets.get(endpoint)
        if budget is None:
            budget = _budgets[endpoint] = ConnectionBudget(_maxconn_at(endpoint))
        return budget


def _budget_for(readonly: bool) -> ConnectionBudget:
    return _budget_at(_endpoint_of(readonly))


def _pool_at(endpoint: tuple, readonly: bool) -> ConnectionPool:
    key = (endpoint, readonly)
    pool = _pools.get(key)
    if pool is not None:
        return pool
    with _pool_lock:
        pool = _pools.get(key)
        if pool is None:
            budget = _budget_at(endpoint)
            pool = _pools[key] = ConnectionPool(
                budget.maxconn,
                readonly=readonly,
                minconn=int(tools.config["db_minconn"] or 0),
                borrow_timeout=tools.config["db_borrow_timeout"],
                max_lifetime=tools.config["db_conn_max_lifetime"],
                max_idle=tools.config["db_conn_max_idle"],
                reap_idle_ttl=tools.config["db_pool_reap_idle"],
                budget=budget,
            )
        return pool


def _get_pool(readonly: bool) -> ConnectionPool:
    return _pool_at(_endpoint_of(readonly), readonly)


def _all_pools() -> list[ConnectionPool]:
    with _pool_lock:
        return list(_pools.values())


def db_connect(to: str, allow_uri: bool = False, readonly: bool = False) -> Connection:
    db, info = connection_info_for(to, readonly)
    if not allow_uri and db != to:
        msg = "URI connections not allowed"
        raise ValueError(msg)
    return Connection(_pool_at(_endpoint_key(info), readonly), db, info)


def is_pooled(db_name: str) -> bool:
    return any(pool.has_database(db_name) for pool in _all_pools())


def pool_health() -> dict:
    configured = {False: _endpoint_of(False), True: _endpoint_of(True)}
    health: dict = {"read_write": None, "read_only": None}
    with _pool_lock:
        items = list(_pools.items())
    for (endpoint, readonly), pool in items:
        mode = "read_only" if readonly else "read_write"
        if endpoint == configured[readonly]:
            health[mode] = pool.health()
        else:
            host, port = endpoint
            health[f"uri:{host}:{port}:{mode}"] = pool.health()
    return health


def close_db(db_name: str) -> None:
    for pool in _all_pools():
        pool.close_database(db_name)


def close_all() -> None:
    for pool in _all_pools():
        pool.close_all()


atexit.register(close_all)


def drain_db(db_name: str) -> None:
    for pool in _all_pools():
        pool.drain_database(db_name)


def drain_all() -> None:
    for pool in _all_pools():
        pool.drain()


def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import metrics

        return metrics.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
