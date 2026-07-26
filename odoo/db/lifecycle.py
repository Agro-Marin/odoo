"""Per-physical-connection lifecycle callbacks for the psycopg_pool pools.

Split out of :mod:`odoo.db.pool` so the per-*physical*-connection policy lives
in a small, independently testable unit.  These are the ``configure`` /
``reset`` / ``check`` callbacks :class:`ConnectionPool` hands to every per-DSN
``psycopg_pool.ConnectionPool``:

* :func:`_configure_connection` — once, when a new backend connection is created
  (register type adapters, tune auto-prepare, seed the liveness stamp).
* :func:`_reset_connection` — on every return to the pool (restore session
  defaults + prepare tuning; optional ``DISCARD ALL``).
* :func:`_check_connection` — on every ``getconn`` (grace-windowed liveness probe).

They take a bare ``psycopg.Connection`` and hold no pool/socket/``self`` state.
The tuning constants they share live here too, so the two that re-apply them
cannot drift.  :mod:`odoo.db.pool` re-imports these names, so
``from odoo.db.pool import _configure_connection`` keeps resolving.
"""

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
    """Configure each new connection created by psycopg_pool.

    Registers Odoo's type adapters per-connection (not on the process-global
    ``psycopg.adapters``, so importing the db package doesn't change numeric
    decoding for other psycopg users) and applies the prepare tuning
    (see _PREPARE_THRESHOLD).

    Per-session GUCs (jit, work_mem) are set via the ``options`` connection
    parameter in :meth:`ConnectionPool._get_or_create_pool`, not here — this
    callback runs in pool worker threads and must avoid cursor ops.  The
    minimum-version gate likewise lives in :meth:`ConnectionPool.borrow`, where
    it can fail fast with the real message instead of a generic 30s PoolTimeout.
    """
    register_adapters(conn)

    conn.prepare_threshold = _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX

    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _reset_connection(conn: psycopg.Connection) -> None:
    """Reset connection state when returned to the pool.

    psycopg_pool auto-rolls back the open transaction before this runs.  We reset
    the session settings ``Cursor.__init__`` may have changed (isolation_level,
    read_only, autocommit) by attribute assignment (no round-trip, unlike
    ``RESET ALL``), and restore the prepare tuning that ``Cursor.execute`` may
    have cleared in its DDL fallback (``prepare_threshold = None``).

    By default this issues a cheap single-round-trip session reset
    (:data:`_RESET_SESSION_STATE_SQL`) that closes the cross-borrower leaks —
    GUCs (incl. ``search_path``), ``SET ROLE``, committed temp tables,
    ``LISTEN`` channels, session advisory locks, open cursors — while
    preserving the prepared-statement/plan caches for the next borrower.  With
    the ``db_discard_on_return`` config option set, it runs the full
    ``DISCARD ALL`` instead (hard isolation, also dropping those caches).

    ``DISCARD``/``DISCARD TEMP`` cannot run inside a transaction block; psycopg_pool
    has already rolled back the open transaction, so we switch to autocommit first.
    """
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
    """Liveness check psycopg_pool runs on every ``getconn`` — gated so a
    connection released within the last ``db_healthcheck_grace`` seconds
    skips the probe.

    The probe (an empty ``execute("")``) is a server round-trip on every borrow;
    a connection released a few hundred ms ago was provably alive then, so
    re-probing only adds latency on a busy worker reusing a warm connection.
    Connections idle longer ARE still probed, so a backend that died while parked
    (restart, failover, ``pg_terminate_backend``) is still discarded before
    reaching a borrower.  The only exposure is the sub-grace window: a connection
    that dies and is reborrowed within it is handed out and fails on first use,
    then discarded on the next probe.  Mirrors HikariCP's ``aliveBypassWindow``.

    A failed probe raises, and psycopg_pool discards the connection and retries
    with a fresh one.  A connection with no stamp (shouldn't happen) fails safe
    to the full probe.
    """
    grace = tools.config["db_healthcheck_grace"]
    idle_since = getattr(conn, _IDLE_SINCE_ATTR, None)
    if grace and idle_since is not None and monotonic() - idle_since < grace:
        return
    _PsycopgPool.check_connection(conn)
