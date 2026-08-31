import atexit
import logging

from .budget import ConnectionBudget
from .cursor import BaseCursor, Cursor, Savepoint
from .endpoints import EndpointRegistry, endpoint_key
from .pool import Connection, ConnectionPool, PoolError
from .savepoint import insert_or_existing
from .schema import FunctionStatus, has_trigram, has_unaccent
from .utils import (
    SYSTEM_DBS,
    categorize_query,
    get_connection_info_for,
    is_maintenance_db,
)

__all__ = [
    "SYSTEM_DBS",
    "BaseCursor",
    "Connection",
    "ConnectionBudget",
    "ConnectionPool",
    "Cursor",
    "EndpointRegistry",
    "FunctionStatus",
    "PoolError",
    "Savepoint",
    "categorize_query",
    "close_all",
    "close_db",
    "db_connect",
    "drain_all",
    "drain_db",
    "get_connection_info_for",
    "has_trigram",
    "has_unaccent",
    "insert_or_existing",
    "is_maintenance_db",
    "is_pooled",
    "pool_health",
    "sql_counter",  # noqa: F822  served by the module-level __getattr__ below
]

_logger = logging.getLogger(__name__)

registry = EndpointRegistry()


def db_connect(to: str, allow_uri: bool = False, readonly: bool = False) -> Connection:
    db, info = get_connection_info_for(to, readonly)
    if not allow_uri and db != to:
        msg = "URI connections not allowed"
        raise ValueError(msg)
    return Connection(registry.get_pool_at(endpoint_key(info), readonly), db, info)


def is_pooled(db_name: str) -> bool:
    return registry.is_pooled(db_name)


def pool_health() -> dict:
    return registry.health()


def close_db(db_name: str) -> None:
    registry.close_db(db_name)


def close_all() -> None:
    registry.close_all()


def drain_db(db_name: str) -> None:
    registry.drain_db(db_name)


def drain_all() -> None:
    registry.drain_all()


atexit.register(close_all)


def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import metrics

        return metrics.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
