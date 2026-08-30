from __future__ import annotations

import threading

import odoo
from odoo import tools

from .budget import ConnectionBudget
from .dsn import _expand_conninfo
from .pool import ConnectionPool
from .utils import connection_info_for

DEFAULT_PG_PORT = 5432


def _port(port: object) -> int:
    try:
        return int(port)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return DEFAULT_PG_PORT


def endpoint_key(info: dict) -> tuple[str | None, int]:
    if not info.get("dsn"):
        return (info.get("host") or None, _port(info.get("port")))
    expanded = _expand_conninfo(info)
    host = expanded.get("host") or tools.config["db_host"] or None
    port = expanded.get("port") or tools.config["db_port"]
    return (host, _port(port))


def base_maxconn() -> int:
    return int(
        (
            tools.config["db_maxconn_gevent"]
            if hasattr(odoo, "evented") and odoo.evented
            else 0
        )
        or tools.config["db_maxconn"]
    )


class EndpointRegistry:
    def __init__(self) -> None:
        self._pools: dict[tuple, ConnectionPool] = {}
        self._budgets: dict[tuple, ConnectionBudget] = {}
        self._lock = threading.RLock()

    def endpoint_of(self, readonly: bool) -> tuple:
        _, info = connection_info_for("", readonly)
        return endpoint_key(info)

    def maxconn_at(self, endpoint: tuple) -> int:
        base = base_maxconn()
        if endpoint != self.endpoint_of(False) and endpoint == self.endpoint_of(True):
            return int(tools.config["db_maxconn_replica"] or base)
        return base

    def maxconn_for(self, readonly: bool) -> int:
        return self.maxconn_at(self.endpoint_of(readonly))

    def budget_at(self, endpoint: tuple) -> ConnectionBudget:
        with self._lock:
            budget = self._budgets.get(endpoint)
            if budget is None:
                budget = self._budgets[endpoint] = ConnectionBudget(
                    self.maxconn_at(endpoint)
                )
            return budget

    def budget_for(self, readonly: bool) -> ConnectionBudget:
        return self.budget_at(self.endpoint_of(readonly))

    def pool_at(self, endpoint: tuple, readonly: bool) -> ConnectionPool:
        key = (endpoint, readonly)
        pool = self._pools.get(key)
        if pool is not None:
            return pool
        with self._lock:
            pool = self._pools.get(key)
            if pool is None:
                budget = self.budget_at(endpoint)
                pool = self._pools[key] = ConnectionPool(
                    budget.maxconn,
                    readonly=readonly,
                    minconn=int(tools.config["db_minconn"] or 0),
                    borrow_timeout=tools.config["db_borrow_timeout"],
                    max_lifetime=tools.config["db_conn_max_lifetime"],
                    max_idle=tools.config["db_conn_max_idle"],
                    reap_idle_ttl=tools.config["db_pool_reap_idle"],
                    budget=budget,
                    pool_workers=int(tools.config["db_pool_workers"] or 1),
                )
            return pool

    def pool_for(self, readonly: bool) -> ConnectionPool:
        return self.pool_at(self.endpoint_of(readonly), readonly)

    def all_pools(self) -> list[ConnectionPool]:
        with self._lock:
            return list(self._pools.values())

    def is_pooled(self, db_name: str) -> bool:
        return any(pool.has_database(db_name) for pool in self.all_pools())

    def health(self) -> dict:
        configured = {False: self.endpoint_of(False), True: self.endpoint_of(True)}
        health: dict = {"read_write": None, "read_only": None}
        with self._lock:
            items = list(self._pools.items())
        for (endpoint, readonly), pool in items:
            mode = "read_only" if readonly else "read_write"
            if endpoint == configured[readonly]:
                health[mode] = pool.health()
            else:
                host, port = endpoint
                health[f"uri:{host}:{port}:{mode}"] = pool.health()
        return health

    def close_db(self, db_name: str) -> None:
        for pool in self.all_pools():
            pool.close_database(db_name)

    def close_all(self) -> None:
        for pool in self.all_pools():
            pool.close_all()

    def drain_db(self, db_name: str) -> None:
        for pool in self.all_pools():
            pool.drain_database(db_name)

    def drain_all(self) -> None:
        for pool in self.all_pools():
            pool.drain()
