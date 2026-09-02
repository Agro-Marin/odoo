from __future__ import annotations

import threading

from .budget import ConnectionBudget
from .dsn import _expand_conninfo
from .pool import ConnectionPool
from .settings import PoolSettings, current
from .utils import get_connection_info_for_database

DEFAULT_PG_PORT = 5432


def _coerce_port(port: object) -> int:
    try:
        return int(port)  # type: ignore[call-overload]
    except TypeError, ValueError:
        return DEFAULT_PG_PORT


def _resolve(settings: PoolSettings | None) -> PoolSettings:
    return settings if settings is not None else current()


def get_endpoint_key(
    info: dict, settings: PoolSettings | None = None
) -> tuple[str | None, int]:
    if not info.get("dsn"):
        return (info.get("host") or None, _coerce_port(info.get("port")))
    settings = _resolve(settings)
    expanded = _expand_conninfo(info)
    host = expanded.get("host") or settings.host or None
    port = expanded.get("port") or settings.port
    return (host, _coerce_port(port))


class EndpointRegistry:
    def __init__(self) -> None:
        self._pools: dict[tuple, ConnectionPool] = {}
        self._budgets: dict[tuple, ConnectionBudget] = {}
        self._lock = threading.RLock()

    def get_endpoint_for_readonly(
        self, readonly: bool, settings: PoolSettings | None = None
    ) -> tuple:
        settings = _resolve(settings)
        _, info = get_connection_info_for_database("", readonly, settings)
        return get_endpoint_key(info, settings)

    def get_maxconn_at_endpoint(
        self, endpoint: tuple, settings: PoolSettings | None = None
    ) -> int:
        settings = _resolve(settings)
        base = settings.maxconn
        if endpoint != self.get_endpoint_for_readonly(
            False, settings
        ) and endpoint == self.get_endpoint_for_readonly(True, settings):
            return settings.maxconn_replica or base
        return base

    def get_maxconn_for_readonly(
        self, readonly: bool, settings: PoolSettings | None = None
    ) -> int:
        settings = _resolve(settings)
        return self.get_maxconn_at_endpoint(
            self.get_endpoint_for_readonly(readonly, settings), settings
        )

    def get_budget_at_endpoint(
        self, endpoint: tuple, settings: PoolSettings | None = None
    ) -> ConnectionBudget:
        with self._lock:
            budget = self._budgets.get(endpoint)
            if budget is None:
                budget = self._budgets[endpoint] = ConnectionBudget(
                    self.get_maxconn_at_endpoint(endpoint, settings)
                )
            return budget

    def get_budget_for_readonly(
        self, readonly: bool, settings: PoolSettings | None = None
    ) -> ConnectionBudget:
        settings = _resolve(settings)
        return self.get_budget_at_endpoint(
            self.get_endpoint_for_readonly(readonly, settings), settings
        )

    def get_pool_at_endpoint(
        self, endpoint: tuple, readonly: bool, settings: PoolSettings | None = None
    ) -> ConnectionPool:
        key = (endpoint, readonly)
        pool = self._pools.get(key)
        if pool is not None:
            return pool
        settings = _resolve(settings)
        with self._lock:
            pool = self._pools.get(key)
            if pool is None:
                budget = self.get_budget_at_endpoint(endpoint, settings)
                pool = self._pools[key] = ConnectionPool(
                    budget.maxconn,
                    readonly=readonly,
                    minconn=settings.minconn,
                    borrow_timeout=settings.borrow_timeout,
                    max_lifetime=settings.conn_max_lifetime,
                    max_idle=settings.conn_max_idle,
                    reap_idle_ttl=settings.pool_reap_idle,
                    budget=budget,
                    pool_workers=settings.pool_workers,
                    settings=settings,
                )
            return pool

    def get_pool_for_readonly(
        self, readonly: bool, settings: PoolSettings | None = None
    ) -> ConnectionPool:
        settings = _resolve(settings)
        return self.get_pool_at_endpoint(
            self.get_endpoint_for_readonly(readonly, settings), readonly, settings
        )

    def get_all_pools(self) -> list[ConnectionPool]:
        with self._lock:
            return list(self._pools.values())

    def is_pooled(self, db_name: str) -> bool:
        return any(pool.has_database(db_name) for pool in self.get_all_pools())

    def get_health(self, settings: PoolSettings | None = None) -> dict:
        settings = _resolve(settings)
        configured = {
            False: self.get_endpoint_for_readonly(False, settings),
            True: self.get_endpoint_for_readonly(True, settings),
        }
        health: dict = {"read_write": None, "read_only": None}
        with self._lock:
            items = list(self._pools.items())
        for (endpoint, readonly), pool in items:
            mode = "read_only" if readonly else "read_write"
            if endpoint == configured[readonly]:
                health[mode] = pool.get_health()
            else:
                host, port = endpoint
                health[f"uri:{host}:{port}:{mode}"] = pool.get_health()
        return health

    def close_db(self, db_name: str) -> None:
        for pool in self.get_all_pools():
            pool.close_database(db_name)

    def close_all(self) -> None:
        for pool in self.get_all_pools():
            pool.close_all()

    def drain_db(self, db_name: str) -> None:
        for pool in self.get_all_pools():
            pool.drain_database(db_name)

    def drain_all(self) -> None:
        for pool in self.get_all_pools():
            pool.drain_all()
