"""Per-physical-connection lifecycle callbacks for the psycopg_pool pools.

Split out of :mod:`odoo.db.pool` — like :mod:`odoo.db.dsn` / :mod:`odoo.db.ddl`
— so the policy applied to each *physical* connection lives in a small,
independently testable unit.  These three functions are the ``configure`` /
``reset`` / ``check`` callbacks :class:`ConnectionPool` hands to every per-DSN
``psycopg_pool.ConnectionPool``:

* :func:`_configure_connection` — runs once when psycopg_pool creates a new
  backend connection (register Odoo's type adapters, tune auto-prepare, seed the
  liveness stamp).
* :func:`_reset_connection` — runs each time a connection is returned to the
  pool (restore session defaults + prepare tuning; optional ``DISCARD ALL``).
* :func:`_check_connection` — runs on every ``getconn`` (grace-windowed liveness
  probe).

They take a bare ``psycopg.Connection`` and hold **no** pool, socket-owning, or
``self`` state — the same "pure, per-X, independently testable" profile as the
DSN helpers, and the reason the suite can already exercise them by calling e.g.
``_reset_connection(cr.connection)`` directly.  The tuning constants the three
callbacks share live here too, so the two that re-apply them
(``_configure_connection`` / ``_reset_connection``) cannot drift apart.

Pool-*creation* config (``max_lifetime`` / ``max_idle``) intentionally stays in
:mod:`odoo.db.pool`: it parameterizes the pool object, not the per-connection
policy.  :mod:`odoo.db.pool` re-imports the names below that it (and white-box
tests) reference, so ``from odoo.db.pool import _configure_connection`` and
friends keep resolving unchanged.
"""

from __future__ import annotations

import os
from time import monotonic

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool

from .utils import register_adapters

# Auto-prepared-statement tuning (PG18-optimized).  Odoo's ORM repeats the same
# query shapes, so preparing after the 2nd execution (vs psycopg's default 5)
# skips re-parse/plan; a 500-entry LRU (vs default 100) covers the hot ORM paths
# without bloat.  Applied at connection creation (``_configure_connection``) AND
# re-applied on return (``_reset_connection``, which may have to undo the
# DDL-fallback ``prepare_threshold = None``) — defined here once so the two
# callbacks cannot silently drift out of sync.
_PREPARE_THRESHOLD = 2
_PREPARED_MAX = 500

# Liveness-check bypass window.  The per-borrow check (``check=`` below) is a
# server round-trip on every ``getconn``; a connection released within this many
# seconds was provably alive then, so re-probing it only burns latency.
# Connections idle longer ARE still probed.  See :func:`_check_connection`.
_HEALTHCHECK_GRACE_PERIOD = 1.0
# Instance attribute stamped on a connection whenever it is (re)admitted to the
# pool as known-alive — at creation (``configure``) and on return (``reset``).
_IDLE_SINCE_ATTR = "_odoo_idle_since"

# Opt-in hard session reset on connection return.  By default _reset_connection
# issues NO ``DISCARD``/``RESET ALL`` (see its docstring): that keeps the return
# path purely client-side and preserves the auto-prepared-statement cache, at
# the cost of letting session-scoped state a borrower forgets to clean up
# (committed temp tables, ``SET`` GUCs, ``LISTEN`` channels, advisory locks)
# survive onto the next borrower of the same physical connection.  For
# multi-tenant hosts that need hard isolation between borrows, set
# ``ODOO_DB_DISCARD_ON_RETURN=1`` to run ``DISCARD ALL`` on every return.  This
# trades the warm prepared-statement cache (DISCARD ALL deallocates it) for a
# guaranteed-clean session.  Read once at import — the env never changes
# mid-process — so the hot return path pays only a single boolean test.
_DISCARD_ON_RETURN: bool = os.environ.get(
    "ODOO_DB_DISCARD_ON_RETURN", ""
).strip().lower() in ("1", "true", "yes", "on")


def _configure_connection(conn: psycopg.Connection) -> None:
    """Configure each new connection created by psycopg_pool.

    Type adapters (numeric→float) are registered here, per-connection, via
    :func:`utils.register_adapters` — deliberately NOT on the process-global
    ``psycopg.adapters``, so importing the db package does not change numeric
    decoding for unrelated psycopg users in the process.

    Prepared statement tuning: Odoo's ORM generates the same query
    shapes repeatedly (SELECT with same columns, UPDATE same fields).
    Auto-preparing after the 2nd execution (instead of default 5)
    skips parse+plan on subsequent calls.  A 500-statement LRU cache
    (instead of default 100) covers the hot ORM paths without bloat.
    PG18's improved plan-cache invalidation makes this safe.

    Per-session GUCs (jit, work_mem) are set via the ``options``
    connection parameter in :meth:`ConnectionPool._get_or_create_pool` to avoid
    cursor operations in this callback (which runs in pool worker
    threads and can interact badly with pool lifecycle).

    NB: the PostgreSQL minimum-version gate lives in
    :meth:`ConnectionPool.borrow`, not here.  Raising from this callback
    runs inside a pool worker thread: psycopg_pool just logs the error,
    retries with backoff, and the caller eventually gets a generic 30s
    ``PoolTimeout`` — the actionable "upgrade your PostgreSQL" message
    never reaches them.  Checking in ``borrow()`` is a local attribute
    read (no round-trip) and fails fast with the real message.
    """
    # Register Odoo's type adapters on THIS connection (per-connection, not
    # process-global — see utils.register_adapters for the rationale).
    register_adapters(conn)

    # Prepared statement tuning (PG18-optimized) — see _PREPARE_THRESHOLD.
    conn.prepare_threshold = _PREPARE_THRESHOLD
    conn.prepared_max = _PREPARED_MAX

    # A freshly connected socket is alive by definition, so seed the liveness
    # stamp here too: a connection created on-demand and handed straight to its
    # requester skips the redundant probe (see _check_connection).
    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _reset_connection(conn: psycopg.Connection) -> None:
    """Reset connection state when returned to pool.

    psycopg_pool auto-rolls back active transactions before calling
    this. We reset session-level settings that Cursor.__init__ may
    have changed (isolation_level, read_only) and ensure autocommit
    is off for the next user. Using attribute assignment avoids a
    round-trip (unlike ``RESET ALL``).

    Also restore the prepared-statement tuning set by
    :func:`_configure_connection`.  ``Cursor.execute`` may have set
    ``prepare_threshold = None`` in the DDL-fallback path (when
    ``Connection._prepared`` is unavailable) — without this restore the
    next borrower inherits disabled auto-prepare for up to max_lifetime.

    By default this reset issues NO ``DISCARD`` / ``RESET ALL`` (set
    ``ODOO_DB_DISCARD_ON_RETURN=1`` to opt into ``DISCARD ALL`` — see
    :data:`_DISCARD_ON_RETURN`).

    .. warning::
        In the default (no-DISCARD) mode, those statements would add a server
        round-trip on every pool return (this callback is otherwise purely
        client-side), and ``DISCARD ALL`` would additionally wipe the
        auto-prepared-statement cache that :func:`_configure_connection`
        deliberately keeps warm.  As a consequence, ANY session-scoped state a
        borrower leaves behind survives onto the *next* borrower of the same
        physical connection, until ``max_lifetime`` (1h) recycles it:

        - **Temp tables** that were committed (i.e. not created ``ON COMMIT
          DROP``) stay visible to the next borrower — a re-``CREATE TEMP TABLE``
          of the same name then fails with ``DuplicateTable`` and stale rows can
          be read.  Production callers MUST use ``ON COMMIT DROP`` (and,
          defensively, ``DROP TABLE IF EXISTS`` first); see
          ``account/res_currency.py`` for the established pattern.
        - **Arbitrary session GUCs** set via ``SET x = y`` persist; use ``SET
          LOCAL`` (transaction-scoped) or an explicit ``RESET`` before release.
          (``isolation_level`` / ``read_only`` / ``autocommit`` and the prepare
          tuning ARE reset below — only *arbitrary* GUCs leak.)
        - **Server-side cursors, ``LISTEN`` channels and advisory locks** left
          without ``CLOSE`` / ``UNLISTEN`` / unlock likewise persist.

        The rollback psycopg_pool runs before this callback only undoes the
        open transaction; it does not drop committed temp objects or reset
        GUCs.  Hosts that need hard isolation between borrows can opt in via
        ``ODOO_DB_DISCARD_ON_RETURN=1`` rather than making every return pay for
        it.
    """
    if _DISCARD_ON_RETURN:
        # Hard reset: drop every session-scoped object/setting the borrower may
        # have left behind.  ``DISCARD ALL`` cannot run inside a transaction
        # block; psycopg_pool has already rolled back the open transaction, so
        # switch to autocommit (no-op if already there, no round-trip) before
        # issuing it.  This also deallocates the prepared-statement cache — the
        # documented cost of opting in — which the prepare tuning below leaves
        # ready to re-warm on the next borrower.
        conn.autocommit = True
        conn.execute("DISCARD ALL")
    conn.autocommit = False
    conn.isolation_level = None  # restore server default
    conn.read_only = None  # restore server default
    conn.prepare_threshold = _PREPARE_THRESHOLD  # see _configure_connection
    conn.prepared_max = _PREPARED_MAX
    # Stamp last: the connection is now fully reset and known-alive (its borrower
    # just released it without error), so the next borrow within the grace window
    # can trust it without a probe.  See _check_connection.
    setattr(conn, _IDLE_SINCE_ATTR, monotonic())


def _check_connection(conn: psycopg.Connection) -> None:
    """Liveness check psycopg_pool runs on every ``getconn`` (the pool's
    ``check=`` callback) — gated so a connection released within the last
    :data:`_HEALTHCHECK_GRACE_PERIOD` seconds skips the probe.

    The probe itself (:meth:`psycopg_pool.ConnectionPool.check_connection`, an
    empty ``execute("")``) is a **server round-trip on every borrow**, plus an
    autocommit flip for our non-autocommit connections.  A connection its
    previous borrower released a few hundred milliseconds ago was provably alive
    then, so re-probing it only adds latency — the dominant, repeated cost on a
    busy worker that reuses the same warm connection request after request.

    Connections idle **longer** than the grace window are still probed, so a
    backend that died while parked in the pool (server restart, failover,
    ``pg_terminate_backend``) is detected and discarded before it reaches a
    borrower — the same protection the unconditional check gave, minus the
    hot-path round-trip.  The residual exposure is bounded to the sub-grace
    window and is symmetric with running no check at all there: a connection
    that dies *and* is reborrowed within ``_HEALTHCHECK_GRACE_PERIOD`` is handed
    out and fails on first use (then discarded on the following borrow's probe).
    Pattern mirrors HikariCP's ``aliveBypassWindow``.

    Raising propagates to psycopg_pool, which discards the connection and retries
    with another (``CLIENT_EXCEPTIONS`` is ``Exception``) — so a failed probe
    transparently yields a fresh connection to the borrower.  A connection with
    no stamp yet (should not happen — ``configure``/``reset`` both set it) fails
    safe to the full probe.
    """
    idle_since = getattr(conn, _IDLE_SINCE_ATTR, None)
    if idle_since is not None and monotonic() - idle_since < _HEALTHCHECK_GRACE_PERIOD:
        return
    _PsycopgPool.check_connection(conn)
