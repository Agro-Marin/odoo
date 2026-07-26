"""PostgreSQL connectivity layer for Odoo.

- Connection pooling (ConnectionPool, Connection)
- Cursor management (BaseCursor, Cursor, Savepoint)
- Utilities (connection_info_for, categorize_query)

Usage::

    from odoo.db import db_connect

    conn = db_connect("mydb")
    with conn.cursor() as cr:
        cr.execute("SELECT * FROM res_users")
        rows = cr.fetchall()
"""

import atexit
import logging
import threading

import odoo
from odoo import tools

from .cursor import BaseCursor, Cursor, Savepoint
from .pool import Connection, ConnectionBudget, ConnectionPool, PoolError
from .utils import categorize_query, connection_info_for

__all__ = [
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
    "is_pooled",
    "sql_counter",
]

_logger = logging.getLogger(__name__)

_Pool: ConnectionPool | None = None
_Pool_readonly: ConnectionPool | None = None
_budget: ConnectionBudget | None = None
_pool_lock = threading.Lock()


def _get_pool(readonly: bool) -> ConnectionPool:
    """Return the process-wide pool, creating it lazily.

    Double-checked locking: the fast path is a plain read; only the first
    caller per pool pays for the lock.  Config is immutable post-startup,
    so no lock is needed around the maxconn reads.
    """
    global _Pool, _Pool_readonly, _budget
    pool = _Pool_readonly if readonly else _Pool
    if pool is None:
        with _pool_lock:
            pool = _Pool_readonly if readonly else _Pool
            if pool is None:
                maxconn = (
                    tools.config["db_maxconn_gevent"]
                    if hasattr(odoo, "evented") and odoo.evented
                    else 0
                ) or tools.config["db_maxconn"]
                minconn = tools.config["db_minconn"] or 0
                if _budget is None:
                    _budget = ConnectionBudget(int(maxconn))
                pool = ConnectionPool(
                    int(maxconn),
                    readonly=readonly,
                    minconn=int(minconn),
                    borrow_timeout=tools.config["db_borrow_timeout"],
                    max_lifetime=tools.config["db_conn_max_lifetime"],
                    max_idle=tools.config["db_conn_max_idle"],
                    reap_idle_ttl=tools.config["db_pool_reap_idle"],
                    budget=_budget,
                )
                if readonly:
                    _Pool_readonly = pool
                else:
                    _Pool = pool
    return pool


def db_connect(to: str, allow_uri: bool = False, readonly: bool = False) -> Connection:
    """Connect to a PostgreSQL database.

    :param to: Database name or PostgreSQL URI
    :param allow_uri: If True, allows PostgreSQL URI connections
    :param readonly: If True, use the read-only replica pool
    :return: Connection object
    :raises ValueError: If URI provided but allow_uri is False
    """
    db, info = connection_info_for(to, readonly)
    if not allow_uri and db != to:
        msg = "URI connections not allowed"
        raise ValueError(msg)
    return Connection(_get_pool(readonly), db, info)


def is_pooled(db_name: str) -> bool:
    """Whether a connection pool for ``db_name`` currently exists.

    Read-only: asking never creates a pool.  Intended for callers that connect
    to a database only to inspect it and then want to leave the process exactly
    as they found it — close the pool if they opened it, keep it if the database
    was already being served.  See :meth:`ConnectionPool.has_database`.

    :param db_name: Name of the database to test
    """
    return bool(
        (_Pool and _Pool.has_database(db_name))
        or (_Pool_readonly and _Pool_readonly.has_database(db_name))
    )


def close_db(db_name: str) -> None:
    """Close all connections to a specific database.

    No schema-cache invalidation is needed here: the ``copy_from`` catalog
    facts live on the cursor for one transaction only (see
    :mod:`odoo.db.schema_cache`), so a drop/recreate cycle cannot leave
    process-global state behind to poison binary COPY on the new schema.

    You might want to call odoo.modules.registry.Registry.delete(db_name)
    along with this function.

    :param db_name: Name of the database to close connections for
    """
    if _Pool:
        _Pool.close_database(db_name)
    if _Pool_readonly:
        _Pool_readonly.close_database(db_name)


def close_all() -> None:
    """Close all database connections in all pools."""
    if _Pool:
        _Pool.close_all()
    if _Pool_readonly:
        _Pool_readonly.close_all()


atexit.register(close_all)


def drain_db(db_name: str) -> None:
    """Drain the pools for one database.

    Called when this worker learns (via registry signaling) that another
    worker changed *db_name*'s schema: idle pooled connections hold
    auto-prepared statements from before the change.  The ``copy_from``
    catalog facts need no draining — they are transaction-scoped and read
    under a lock that blocks such a change (see
    :mod:`odoo.db.schema_cache`).  Unlike :func:`drain_all`, other databases
    served by this process are left untouched.
    """
    if _Pool:
        _Pool.drain_database(db_name)
    if _Pool_readonly:
        _Pool_readonly.drain_database(db_name)


def drain_all() -> None:
    """Drain all pools — replace idle connections with fresh ones.

    Call after module upgrades to discard connections with stale
    prepared statement caches from before the schema change.  The binary-COPY
    column types need no clearing here: they are transaction-scoped, so no
    connection returned to a pool carries any (see
    :mod:`odoo.db.schema_cache`).
    """
    if _Pool:
        _Pool.drain()
    if _Pool_readonly:
        _Pool_readonly.drain()


def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import metrics

        return metrics.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
