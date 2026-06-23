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

import os
from time import monotonic

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool

from .utils import register_adapters

# Auto-prepared-statement tuning.  Odoo's ORM repeats query shapes, so preparing
# after the 2nd execution (psycopg default 5) skips re-parse/plan; a 500-entry
# LRU (default 100) covers the hot paths.  Applied at creation and re-applied on
# return (which may undo the DDL-fallback ``prepare_threshold = None``).
_PREPARE_THRESHOLD = 2
_PREPARED_MAX = 500

# Liveness-check bypass window: a connection released within this many seconds
# was provably alive then, so skip the per-borrow probe (see _check_connection).
# Connections idle longer ARE still probed.
_HEALTHCHECK_GRACE_PERIOD = 1.0
# Stamped on a connection whenever it is (re)admitted as known-alive — at
# creation (``configure``) and on return (``reset``).
_IDLE_SINCE_ATTR = "_odoo_idle_since"

# Opt-in hard session reset on return.  By default _reset_connection issues no
# ``DISCARD``/``RESET ALL`` (purely client-side, preserves the prepared-statement
# cache) — at the cost of leaking session state (committed temp tables, GUCs,
# ``LISTEN``, advisory locks) to the next borrower.  Set
# ``ODOO_DB_DISCARD_ON_RETURN=1`` for hard isolation (deallocates the cache).
# Read once at import, so the hot return path pays one boolean test.
_DISCARD_ON_RETURN: bool = os.environ.get(
    "ODOO_DB_DISCARD_ON_RETURN", ""
).strip().lower() in ("1", "true", "yes", "on")


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
    # Per-connection, not process-global (see utils.register_adapters).
    register_adapters(conn)

    conn.prepare_threshold = _PREPARE_THRESHOLD  # see _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX

    # A fresh socket is alive, so seed the stamp: a connection handed straight to
    # its requester skips the redundant probe (see _check_connection).
    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _reset_connection(conn: psycopg.Connection) -> None:
    """Reset connection state when returned to the pool.

    psycopg_pool auto-rolls back the open transaction before this runs.  We reset
    the session settings ``Cursor.__init__`` may have changed (isolation_level,
    read_only, autocommit) by attribute assignment (no round-trip, unlike
    ``RESET ALL``), and restore the prepare tuning that ``Cursor.execute`` may
    have cleared in its DDL fallback (``prepare_threshold = None``).

    By default this issues NO ``DISCARD``/``RESET ALL``
    (see :data:`_DISCARD_ON_RETURN`).

    .. warning::
        In the default mode, session-scoped state a borrower leaves behind
        survives to the *next* borrower of the same physical connection until
        ``max_lifetime`` (1h) recycles it — only autocommit/isolation/read_only
        and the prepare tuning are reset below.  In particular:

        - **Committed temp tables** (not ``ON COMMIT DROP``) stay visible — a
          re-``CREATE TEMP TABLE`` then hits ``DuplicateTable``.  Callers MUST use
          ``ON COMMIT DROP`` (+ ``DROP TABLE IF EXISTS``); see
          ``account/res_currency.py``.
        - **Arbitrary GUCs** (``SET x = y``) persist; use ``SET LOCAL`` or ``RESET``.
        - **Server-side cursors, ``LISTEN`` channels, advisory locks** persist
          without ``CLOSE``/``UNLISTEN``/unlock.

        Opt into ``ODOO_DB_DISCARD_ON_RETURN=1`` for hard isolation.
    """
    if _DISCARD_ON_RETURN:
        # ``DISCARD ALL`` can't run in a transaction block; psycopg_pool already
        # rolled back, so switch to autocommit first.  This also deallocates the
        # prepared-statement cache (the documented cost), which the tuning below
        # leaves ready to re-warm.
        conn.autocommit = True
        conn.execute("DISCARD ALL")
    conn.autocommit = False
    conn.isolation_level = None  # restore server default
    conn.read_only = None  # restore server default
    conn.prepare_threshold = _PREPARE_THRESHOLD  # see _configure_connection
    conn.prepared_max = _PREPARED_MAX
    # Stamp last: now fully reset and known-alive, so the next borrow within the
    # grace window can trust it without a probe (see _check_connection).
    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _check_connection(conn: psycopg.Connection) -> None:
    """Liveness check psycopg_pool runs on every ``getconn`` — gated so a
    connection released within the last :data:`_HEALTHCHECK_GRACE_PERIOD` seconds
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
    idle_since = getattr(conn, _IDLE_SINCE_ATTR, None)
    if idle_since is not None and monotonic() - idle_since < _HEALTHCHECK_GRACE_PERIOD:
        return
    _PsycopgPool.check_connection(conn)
