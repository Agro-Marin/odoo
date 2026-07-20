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

from .cursor import BaseCursor, Cursor, Savepoint, _clear_schema_caches
from .pool import Connection, ConnectionPool, PoolError
from .utils import categorize_query, connection_info_for

__all__ = [
    # Cursor classes
    "BaseCursor",
    # Connection classes
    "Connection",
    "ConnectionPool",
    "Cursor",
    "PoolError",
    "Savepoint",
    # Utility functions
    "categorize_query",
    "close_all",
    "close_db",
    "connection_info_for",
    # Connection management
    "db_connect",
    "drain_all",
    "drain_db",
    # Resolved dynamically via module __getattr__ below (live metrics value).
    "sql_counter",  # noqa: F822 — exposed via __getattr__, not a real name
]

_logger = logging.getLogger(__name__)

# Connection pools (lazily initialized, protected by _pool_lock)
_Pool: ConnectionPool | None = None
_Pool_readonly: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool(readonly: bool) -> ConnectionPool:
    """Return the process-wide pool, creating it lazily.

    Double-checked locking: the fast path is a plain read; only the first
    caller per pool pays for the lock.  Config is immutable post-startup,
    so no lock is needed around the maxconn reads.
    """
    global _Pool, _Pool_readonly  # noqa: PLW0603
    pool = _Pool_readonly if readonly else _Pool
    if pool is None:
        with _pool_lock:
            pool = _Pool_readonly if readonly else _Pool
            if pool is None:
                # hasattr(odoo, "evented") detects gevent mode (set at startup).
                maxconn = (
                    tools.config["db_maxconn_gevent"]
                    if hasattr(odoo, "evented") and odoo.evented
                    else 0
                ) or tools.config["db_maxconn"]
                # Lazy by default (0); raise db_minconn to keep connections warm.
                # ``or 0`` coerces an explicit None/empty back to the default.
                minconn = tools.config["db_minconn"] or 0
                # Pool tuning is read from config here and passed in — see the
                # db_* options in tools/config.py.
                pool = ConnectionPool(
                    int(maxconn),
                    readonly=readonly,
                    minconn=int(minconn),
                    borrow_timeout=tools.config["db_borrow_timeout"],
                    max_lifetime=tools.config["db_conn_max_lifetime"],
                    max_idle=tools.config["db_conn_max_idle"],
                    reap_idle_ttl=tools.config["db_pool_reap_idle"],
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
    # Validate before touching pool state — a rejected URI must not
    # instantiate the process-wide pool as a side effect.
    db, info = connection_info_for(to, readonly)
    if not allow_uri and db != to:
        msg = "URI connections not allowed"
        raise ValueError(msg)
    return Connection(_get_pool(readonly), db, info)


def close_db(db_name: str) -> None:
    """Close all connections to a specific database.

    Also drops the schema caches (column types, id sequences) for that
    database — they would otherwise survive a drop/recreate cycle and
    poison binary COPY on the recreated schema.

    You might want to call odoo.modules.registry.Registry.delete(db_name)
    along with this function.

    :param db_name: Name of the database to close connections for
    """
    _clear_schema_caches(db_name)
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


# Close pools at exit for the paths the server's explicit close_all() misses
# (CLI commands, scripts, error exits).  atexit runs BEFORE interpreter
# finalization, where an open psycopg_pool's __del__ would raise
# PythonFinalizationError ("cannot join thread at interpreter shutdown").
# Idempotent on empty/closed pools.  Forked workers exit via os._exit() and
# bypass atexit by design (the OS reclaims their connections).
atexit.register(close_all)


def drain_db(db_name: str) -> None:
    """Drain pools and schema caches for one database.

    Called when this worker learns (via registry signaling) that another
    worker changed *db_name*'s schema: idle pooled connections hold
    auto-prepared statements from before the change, and the schema caches
    may describe columns that no longer exist with those types.  Unlike
    :func:`drain_all`, other databases served by this process are left
    untouched.
    """
    _clear_schema_caches(db_name)
    if _Pool:
        _Pool.drain_database(db_name)
    if _Pool_readonly:
        _Pool_readonly.drain_database(db_name)


def drain_all() -> None:
    """Drain all pools — replace idle connections with fresh ones.

    Call after module upgrades to discard connections with stale
    prepared statement caches from before the schema change.
    Also clears the column type cache used by binary COPY, since
    schema changes (e.g. ALTER COLUMN TYPE) make cached types stale.
    """
    _clear_schema_caches()
    if _Pool:
        _Pool.drain()
    if _Pool_readonly:
        _Pool_readonly.drain()


# Resolve mutable globals (sql_counter) dynamically so callers see the live
# value from the metrics module, not a copy frozen at import time.
def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import metrics

        return metrics.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
