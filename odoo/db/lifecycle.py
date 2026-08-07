from __future__ import annotations

import contextlib
from time import monotonic

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool

from odoo import tools

from .utils import register_adapters

_PREPARE_THRESHOLD = 2
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


def _configure_connection(conn: psycopg.Connection) -> None:
    register_adapters(conn)

    conn.prepare_threshold = _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX

    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _reset_connection(conn: psycopg.Connection) -> None:
    if tools.config["db_discard_on_return"]:
        conn.autocommit = True
        conn.execute("DISCARD ALL", prepare=False)
        with contextlib.suppress(AttributeError):
            conn._prepared.clear()
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
