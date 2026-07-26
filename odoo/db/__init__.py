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

from .budget import ConnectionBudget
from .cursor import BaseCursor, Cursor, Savepoint
from .pool import Connection, ConnectionPool, PoolError
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
    "pool_health",
    "sql_counter",
]

_logger = logging.getLogger(__name__)

_Pool: ConnectionPool | None = None
_Pool_readonly: ConnectionPool | None = None
_budgets: dict[tuple, ConnectionBudget] = {}
_pool_lock = threading.Lock()


def _endpoint_of(readonly: bool) -> tuple:
    """The PostgreSQL server a pool of this flavour will actually connect to.

    Config-derived host/port only: that is what identifies a *server*, and it is
    knowable at pool-construction time, whereas a DSN only arrives per
    ``db_connect``.  A URI connection (``allow_uri``) is an escape hatch that
    may point anywhere and is simply attributed to its pool's endpoint, exactly
    as it was when one budget covered everything.
    """
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
    """Ceiling for this flavour's endpoint.

    ``db_maxconn_replica`` applies only when the read-only pool really does
    reach a different server; when it resolves to the primary the two share one
    budget and a separate replica ceiling would be meaningless.
    """
    base = _base_maxconn()
    if readonly and _endpoint_of(True) != _endpoint_of(False):
        return int(tools.config["db_maxconn_replica"] or base)
    return base


def _budget_for(readonly: bool) -> ConnectionBudget:
    """The budget for this flavour's endpoint, created once per endpoint.

    ``db_maxconn`` means "physical connections to PostgreSQL", which an operator
    sizes ``max_connections`` against — so the cap belongs to a *server*, not to
    a pool.  One shared budget was right while both pools reached the same
    server (two ``BoundedSemaphore(db_maxconn)`` let a worker hold
    ``2 * db_maxconn``, 128 against a stock 100).  With ``db_replica_host`` set
    they reach two machines with two independent limits, and one budget then
    bounded their *sum*: a replica added no concurrency, and — verified — four
    replica checkouts against ``db_maxconn = 4`` made the primary refuse.

    Keying on the resolved endpoint keeps both properties.  Same server, one
    budget, so the ``2 * db_maxconn`` overshoot cannot come back — including
    when the read-only pool deliberately targets the primary, which is what
    ``test_enable`` and ``dev_mode=replica`` do.  Different servers, one budget
    each, so the replica adds real capacity and cannot starve the primary.
    """
    key = _endpoint_of(readonly)
    budget = _budgets.get(key)
    if budget is None:
        budget = _budgets[key] = ConnectionBudget(_maxconn_for(readonly))
    return budget


def _get_pool(readonly: bool) -> ConnectionPool:
    """Return the process-wide pool, creating it lazily.

    Double-checked locking: the fast path is a plain read; only the first
    caller per pool pays for the lock.  Config is immutable post-startup,
    so no lock is needed around the maxconn reads.
    """
    global _Pool, _Pool_readonly
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


def pool_health() -> dict:
    """Operational counters and gauges for both process-wide pools.

    The one call an operator or a metrics exporter needs: borrow-wait
    distribution, budget saturation, probe outcomes, pool churn, plus the live
    per-database psycopg_pool view.  Pools not yet created are reported as
    ``None`` rather than built, so asking never changes behaviour.
    """
    return {
        "read_write": _Pool.health() if _Pool else None,
        "read_only": _Pool_readonly.health() if _Pool_readonly else None,
    }


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
