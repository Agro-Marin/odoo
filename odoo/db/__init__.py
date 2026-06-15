"""
Database connectivity layer for Odoo.

This package provides the PostgreSQL connectivity layer including:
- Connection pooling (ConnectionPool, Connection)
- Cursor management (BaseCursor, Cursor, Savepoint)
- Utility functions (connection_info_for, categorize_query)

Usage:
    from odoo.db import db_connect, close_db, close_all

    # Get a connection
    conn = db_connect('mydb')

    # Create a cursor for transactions
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
    # Global counter — resolved dynamically via module __getattr__ below
    # so callers always see the current cursor.sql_counter value.
    "sql_counter",  # noqa: F822 — exposed via module __getattr__, not a name
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
                # NB: hasattr(odoo, "evented") is the standard pattern for
                # detecting gevent mode — set once at startup, never changes.
                maxconn = (
                    tools.config["db_maxconn_gevent"]
                    if hasattr(odoo, "evented") and odoo.evented
                    else 0
                ) or tools.config["db_maxconn"]
                # Lazy by default (0); raise db_minconn to keep connections warm.
                minconn = tools.config.get("db_minconn", 0) or 0
                pool = ConnectionPool(
                    int(maxconn), readonly=readonly, minconn=int(minconn)
                )
                if readonly:
                    _Pool_readonly = pool
                else:
                    _Pool = pool
    return pool


def db_connect(to: str, allow_uri: bool = False, readonly: bool = False) -> Connection:
    """Connect to a PostgreSQL database.

    Returns a Connection object that can be used to create cursors.

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


# Close pools before interpreter finalization.  The server's own shutdown
# paths call close_all() explicitly; this atexit handler covers the rest —
# CLI commands, scripts, and error exits — that would otherwise leave pools
# open.  Under Python 3.14 an open psycopg_pool's __del__ runs during
# finalization and raises ``PythonFinalizationError: cannot join thread at
# interpreter shutdown`` (worker threads can no longer be joined that late);
# atexit runs BEFORE finalization, so close()'s thread joins still succeed.
# Idempotent: re-running on an already-closed/empty pool set is a no-op.
# Note: forked workers exit via os._exit(), which bypasses atexit by design —
# they rely on the OS to reclaim their connections.
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


# Dynamic attribute access for mutable globals like sql_counter.
# This ensures db.sql_counter always returns the current value
# from the cursor module, not a stale copy from import time.
# Cost: ~100ns per access (string compare + cached module lookup).
# Called ~1/request for metrics — negligible vs query time.
def __getattr__(name: str) -> int:
    if name == "sql_counter":
        from . import cursor

        return cursor.sql_counter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
