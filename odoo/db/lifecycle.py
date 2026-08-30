from __future__ import annotations

from time import monotonic

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool

from odoo import tools

from .utils import register_adapters

_PREPARE_THRESHOLD = 2
"""Executions of one statement text before psycopg prepares it server-side.

Worth knowing when writing a probe: a prepared statement runs through a NAMED
portal, so a query that reads a catalog view describing the session's own
execution state starts counting itself at its third execution. Measured,
`SELECT count(*) FROM pg_cursors` on one connection answers 0, 0, 1, 1, 1
against a `pg_cursors` that is empty throughout. Nothing in the tree reads
those views, so this bites diagnostics rather than production -- but it looks
exactly like a session-state leak, and `TestResetConnectionClosesSessionGucLeak`
filters by cursor name rather than counting for that reason.
"""
_PREPARED_MAX = 500

_IDLE_SINCE_ATTR = "_odoo_idle_since"

_RESET_SESSION_STATE_SQL = (
    "RESET ALL;"
    " RESET SESSION AUTHORIZATION;"
    " CLOSE ALL;"
    " UNLISTEN *;"
    " SELECT pg_advisory_unlock_all();"
    " DISCARD TEMP;"
    " DISCARD SEQUENCES"
)


def clear_prepared_cache(conn: psycopg.Connection) -> bool:
    """Drop psycopg's client-side auto-prepare map, reporting whether it worked.

    `Connection._prepared` is private and three call sites depend on it -- the
    pool's reset, `Cursor.discard_cached_plans` and the stale-plan recovery --
    and each had invented its own contract for the same coupling: two swallowed
    `AttributeError` and carried on, one logged, disabled auto-prepare for the
    connection's life and fell back to `DEALLOCATE ALL`.  At most one of three
    could be right about how much the dependency matters.

    `clear()` is not merely a client-side forget: it appends `None` to
    psycopg's `_to_flush`, which emits a `DEALLOCATE ALL` on the next command,
    so the server side is cleaned up too and no caller needs to do it.
    """
    prepared = getattr(conn, "_prepared", None)
    if prepared is None:
        return False
    try:
        prepared.clear()
    except Exception:
        return False
    return True


def _configure_connection(conn: psycopg.Connection) -> None:
    register_adapters(conn)

    conn.prepare_threshold = _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX

    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _reset_connection(conn: psycopg.Connection) -> None:
    if tools.config["db_discard_on_return"]:
        conn.autocommit = True
        conn.execute("DISCARD ALL", prepare=False)
        clear_prepared_cache(conn)
    else:
        conn.autocommit = True
        conn.execute(_RESET_SESSION_STATE_SQL, prepare=False)
    conn.autocommit = False
    conn.isolation_level = None
    conn.read_only = None
    conn.prepare_threshold = _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX
    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _check_connection(conn: psycopg.Connection) -> None:
    grace = tools.config["db_healthcheck_grace"]
    idle_since = getattr(conn, _IDLE_SINCE_ATTR, None)
    if grace and idle_since is not None and monotonic() - idle_since < grace:
        return
    _PsycopgPool.check_connection(conn)
