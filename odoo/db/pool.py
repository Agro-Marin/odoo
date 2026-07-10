from __future__ import annotations

import contextlib
import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool
from psycopg_pool import PoolClosed, PoolTimeout

from odoo.release import MIN_PG_VERSION

# DSN normalization + connect-error classification live in their own (pure,
# security-sensitive) module.  Re-imported here so the pool code and existing
# ``from odoo.db.pool import _normalize_dsn_key`` references keep resolving.
from .dsn import (
    _NON_RETRYABLE_CONNECT_ERRORS,
    _expand_conninfo,
    _normalize_dsn_key,
    _translate_connect_error,
)

# Per-physical-connection lifecycle callbacks (configure/reset/check) live in
# their own module; imported here because pool creation passes them to each
# per-DSN psycopg_pool.
from .lifecycle import (
    _check_connection,
    _configure_connection,
    _reset_connection,
)
from .utils import is_maintenance_db

if TYPE_CHECKING:
    from .cursor import Cursor

_logger = logging.getLogger(__name__)
_logger_conn = _logger.getChild("connection")


class _SuppressKnownPoolWarnings(logging.Filter):
    """Suppress (not demote) known psycopg_pool records that are not real errors:

    1. "discarding closed connection" — logged when we intentionally close a
       connection before return (``keep_in_pool=False``); expected.
    2. "database does not exist" — reconnect attempts after a DB is dropped;
       noise, the caller gets a ``PoolTimeout`` and the pool is cleaned up.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "discarding closed connection" in msg:
            return False
        # Narrow to the missing-database phrase; a broad "does not exist" test
        # would also swallow ``role "x" does not exist`` and similar real errors.
        return not ('database "' in msg and "does not exist" in msg)


# Guard against duplicate filters on module reload (addFilter is not idempotent;
# each extra copy re-runs the suppression check per log record).
_psycopg_pool_logger = logging.getLogger("psycopg.pool")
if not any(
    isinstance(f, _SuppressKnownPoolWarnings) for f in _psycopg_pool_logger.filters
):
    _psycopg_pool_logger.addFilter(_SuppressKnownPoolWarnings())

# Default pool tuning.  These are the fallbacks for a directly constructed
# ConnectionPool (tests, low-level callers); production overrides them from the
# matching ``db_*`` options in ``tools.config`` (read in ``odoo/db/__init__.py``
# and passed to the constructor), so the whole subsystem has ONE configuration
# mechanism instead of a mix of constants, env vars and config.  Per-instance
# copies live on ``self`` (see ``__init__``); nothing reads these at module level.
_DEFAULT_MAX_IDLE = 60 * 10  # keep an idle pooled connection up to 10 min
_DEFAULT_MAX_LIFETIME = (
    3600  # recycle each pooled connection hourly (stale prep caches)
)
# Wall-clock budget for one borrow(): the semaphore wait and the per-DSN
# getconn() both draw from this window (a shared deadline, so they can't drift).
_DEFAULT_BORROW_TIMEOUT = 30.0
# Idle per-DSN pool reaper TTL.  Each database keeps its own psycopg_pool (worker
# threads + idle connections) until ``close_*``; nothing trims idle pool OBJECTS
# otherwise, so a host serving many databases accumulates them.  A pool idle
# longer than this with no checked-out connection is reaped (so a long-lived
# ``LISTEN``/cron connection is never touched).  Kept well above the borrow
# timeout so no borrow can be in flight; the residual reap-vs-borrow microrace is
# recovered by borrow()'s PoolClosed retry.  ``0`` disables it.
#
# NB: this default (300s) is BELOW ``_DEFAULT_MAX_IDLE`` (600s) by design — on a
# multi-database host, reclaiming a quiet pool's ~4 worker threads is worth more
# than keeping its connections warm, so the pool (and its still-warm idle
# connections) is reaped before those connections reach their own idle timeout;
# the next access to that database pays a pool rebuild + reconnect.  A
# single-database host is unaffected: its only pool is re-stamped active on every
# give_back, so it is never the idle pool a sweep reaps.  Raise to >=
# ``_DEFAULT_MAX_IDLE`` to let connections idle out first (fewer reconnects,
# more lingering pools).
_DEFAULT_REAP_IDLE_TTL = 300.0

# Monotonic timestamp stamped on each per-DSN psycopg pool whenever it sees
# activity — a borrow (_get_or_create_pool) or a return (give_back), both routed
# through _note_pool_activity.  The reaper measures idleness against it, so a pool
# that just handed out or took back a connection is never mistaken for idle.
_LAST_BORROW_ATTR = "_odoo_last_borrow"

# libpq connect timeout (seconds) for that probe.  Kept short: a permanent
# rejection comes back in one round-trip, so this only bounds the exotic
# "TCP SYN silently dropped" case — where we fall through to the pool's
# normal retry anyway.
_PROBE_CONNECT_TIMEOUT = 5


class PoolError(Exception):
    """Connection pool error."""


class ConnectionPool:
    """Manages per-database psycopg_pool.ConnectionPool instances.

    Each unique DSN (database) gets its own psycopg_pool with:
    - Health checks on borrow (detects dead connections)
    - max_lifetime rotation (recycles connections every hour)
    - Background workers for connection creation
    - Pool statistics via get_stats()

    Connection budget is enforced by ``_pool_sem``, a per-instance bounded
    semaphore sized at ``maxconn``.  Because the R/W and read-only pools
    are two separate ``ConnectionPool`` instances (see ``odoo/db/__init__.py``),
    the PROCESS-WIDE budget is ``2 * maxconn``, not ``maxconn``.

    .. warning::
        The semaphore bounds CHECKED-OUT connections only.  Each per-DSN pool
        may also retain up to ``maxconn`` *idle* connections for ``max_idle``
        (10 min), so one process's worst-case server footprint is
        ``2 * maxconn * n_databases``.  Multi-tenant hosts must size PostgreSQL
        ``max_connections`` accordingly (each per-DSN pool also runs ~4 worker
        threads, and pools are only reaped by ``close_database``/``close_all``).
    """

    def __init__(
        self,
        maxconn: int = 64,
        readonly: bool = False,
        minconn: int = 0,
        *,
        borrow_timeout: float = _DEFAULT_BORROW_TIMEOUT,
        max_lifetime: int = _DEFAULT_MAX_LIFETIME,
        max_idle: int = _DEFAULT_MAX_IDLE,
        reap_idle_ttl: float = _DEFAULT_REAP_IDLE_TTL,
    ):
        # Reject non-positive budgets loudly: a 0/negative maxconn would
        # otherwise wedge the whole server under trivial load.
        if maxconn <= 0:
            raise ValueError(f"ConnectionPool maxconn must be >= 1, got {maxconn}")
        # minconn warms that many connections per per-DSN pool eagerly (0 = lazy
        # open).  Cannot exceed maxconn, else the pool opens connections it can
        # never hand out.
        if minconn < 0:
            raise ValueError(f"ConnectionPool minconn must be >= 0, got {minconn}")
        if minconn > maxconn:
            raise ValueError(
                f"ConnectionPool minconn ({minconn}) cannot exceed maxconn ({maxconn})"
            )
        self._pools: dict[frozenset, _PsycopgPool] = {}
        self._maxconn = maxconn
        self._minconn = minconn
        self._readonly = readonly
        # Per-instance tuning (production reads these from tools.config in
        # odoo/db/__init__.py; the defaults above serve direct construction).
        self._borrow_timeout = borrow_timeout
        self._max_lifetime = max_lifetime
        self._max_idle = max_idle
        self._reap_idle_ttl = reap_idle_ttl
        # Throttle for the give_back-path reap sweep (see _maybe_reap_idle_pools):
        # the cold-path reap only fires on NEW pool creation, so a process on a
        # fixed set of databases would never reap idle siblings.  A quarter of the
        # TTL — prompt but off the hot path — floored at 1s for tiny test TTLs.
        # ``0`` disables it (mirrors ``reap_idle_ttl <= 0``).
        self._reap_check_interval = (
            max(1.0, reap_idle_ttl / 4) if reap_idle_ttl > 0 else 0.0
        )
        self._lock = threading.Lock()
        # Per-instance semaphore — gates connections to this pool, not the process.
        self._pool_sem = threading.BoundedSemaphore(self._maxconn)
        # Last monotonic time the give_back idle reaper swept; 0.0 lets the first
        # eligible give_back sweep immediately (see _maybe_reap_idle_pools).
        self._last_reap_check = 0.0

    def __repr__(self) -> str:
        # Snapshot the pools atomically (``list()`` holds the GIL throughout) so
        # a concurrent create/close can't raise "dictionary changed size".  NOT
        # guarded by self._lock: __repr__ is reached via _debug() while the lock
        # is already held (see _get_or_create_pool), so re-acquiring it would
        # deadlock; a momentarily-stale entry only skews a debug string.
        pools = list(self._pools.values())
        total = available = 0
        for p in pools:
            stats = p.get_stats()
            total += stats.get("pool_size", 0)
            available += stats.get("pool_available", 0)
        used = total - available
        mode = "read-only" if self._readonly else "read/write"
        return (
            f"ConnectionPool({mode};used={used}/total={total}"
            f"/limit={self._maxconn};dbs={len(pools)})"
        )

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _debug(self, msg: str, *args: object) -> None:
        _logger_conn.debug(("%r " + msg), self, *args)

    @staticmethod
    def _checked_out(pool: _PsycopgPool) -> int:
        """Connections *pool* currently has handed out (size minus available).

        Once a pool has been idle past the reap TTL this reading is reliable: any
        async ``reset`` from a recent return has long since drained, so a non-zero
        value is a genuine hold (e.g. a cron ``LISTEN``), not a transient.  Single
        source of truth for the ``pool_size - pool_available`` formula.
        """
        stats = pool.get_stats()
        return stats.get("pool_size", 0) - stats.get("pool_available", 0)

    @staticmethod
    def _note_pool_activity(pool: _PsycopgPool) -> None:
        """Stamp *pool* as freshly active for the idle reaper.

        The single place the ``_LAST_BORROW_ATTR`` stamp is written.  Called on
        EVERY borrow (:meth:`_get_or_create_pool`) and EVERY return
        (:meth:`give_back`): a pool that just handed out or took back a connection
        is active, not idle, and must not be reaped out from under its next user.
        Stamping on return — not only on borrow — is what stops a connection held
        longer than ``reap_idle_ttl`` and then returned from leaving its pool with
        a stale stamp that the next sweep reaps.  ``setattr`` is atomic under the
        GIL, so this needs no lock.
        """
        setattr(pool, _LAST_BORROW_ATTR, monotonic())

    def _probe_connectable(self, conninfo: str, kwargs: dict) -> None:
        """Fail fast on a permanently-unreachable target before building a pool.

        psycopg_pool retries failed connections in a background worker until the
        borrower's ~30s budget expires — even for permanent failures (missing
        database, wrong password).  One synchronous probe surfaces those in
        milliseconds; anything possibly transient is swallowed for the pool's
        normal retry.

        .. note::
            Runs on every COLD pool creation, including re-creation after the
            idle-pool reaper closed a pool.  A database accessed just slower than
            the reap TTL pays the reap→recreate→re-probe cycle each time;
            raise ``db_pool_reap_idle`` if that thrash hurts.

        :raises psycopg.Error: re-raised verbatim for a non-retryable failure,
            so callers see the precise cause (e.g. ``InvalidCatalogName``).
        """
        # Force the probe's own short connect timeout.  _HEALTH_PARAMS already
        # set connect_timeout=10, so overwrite (not setdefault) it — only this
        # throwaway probe is bounded; real pool connections keep their timeout.
        # A slow-but-reachable server just trips it and falls through to retry.
        probe_kwargs = {**kwargs, "autocommit": True}
        probe_kwargs["connect_timeout"] = _PROBE_CONNECT_TIMEOUT
        try:
            psycopg.connect(conninfo, **probe_kwargs).close()
        except _NON_RETRYABLE_CONNECT_ERRORS:
            # SQLSTATE was already parsed into the precise class — permanent.
            raise
        except psycopg.OperationalError as e:
            # Connection-phase failure: no SQLSTATE, only the FATAL text.
            translated = _translate_connect_error(e)
            if translated is not None:
                raise translated from e
            # No English match — but a non-English server (lc_messages=es_MX)
            # hides a real "database does not exist" behind a localised message.
            # Confirm via the postgres catalog before surrendering to the ~30s
            # retry, restoring the fast ``InvalidCatalogName`` path in any locale.
            if self._database_absent(conninfo, kwargs):
                raise psycopg.errors.InvalidCatalogName(str(e)) from e
            # Unrecognised / possibly transient — let the pool's retry recover it.
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )
        except Exception:
            # Non-connection error (malformed conninfo, etc.) — let the pool
            # surface it the same way it would without the probe.
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )

    def _database_absent(self, conninfo: str, kwargs: dict) -> bool:
        """Locale-independently decide whether the target database is absent.

        The connect-phase "database does not exist" FATAL is only classifiable
        by its localised text, so on a non-English server we instead connect to
        the always-present ``postgres`` maintenance DB and ask the catalog:
        ``SELECT 1 FROM pg_database WHERE datname = %s``.

        :return: ``True`` only when the catalog *confirms* absence.  ``False``
            covers both "exists" and "couldn't tell" (no access, network gone,
            target *is* ``postgres``), so this never manufactures a false
            ``InvalidCatalogName``.
        """
        # Merge URI components with explicit kwargs (kwargs win) via the shared
        # expander, which also folds away any embedded ``dsn`` key.
        maint = (
            _expand_conninfo({"dsn": conninfo, **kwargs}) if conninfo else dict(kwargs)
        )
        db_name = kwargs.get("dbname") or maint.get("dbname")
        # Nothing to check, or the target *is* the maintenance DB (circular).
        if not db_name or db_name == "postgres":
            return False
        # Reuse the same host/auth; only swap dbname to ``postgres`` and force
        # autocommit + the short timeout.  Drop ``options`` (GUCs are irrelevant).
        maint.pop("options", None)
        maint["dbname"] = "postgres"
        maint["autocommit"] = True
        maint["connect_timeout"] = _PROBE_CONNECT_TIMEOUT
        try:
            with psycopg.connect("", **maint) as mc:
                row = mc.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
                ).fetchone()
            return row is None
        except Exception:
            # Maintenance DB unreachable / no access — can't tell, so report
            # "not confirmed absent" and let the original error stay transient.
            _logger.debug(
                "pg_database existence check unavailable for %r",
                db_name,
                exc_info=True,
            )
            return False

    def _get_or_create_pool(
        self, key: frozenset, connection_info: dict
    ) -> _PsycopgPool:
        """Get an existing pool for this DSN or create a new one."""
        pool = self._pools.get(key)
        if pool is not None and not pool.closed:
            # Mark active (outside the lock, atomic) so the reaper sees it as
            # freshly used; the TTL >> borrow time and borrow()'s retry cover the
            # microrace.
            self._note_pool_activity(pool)
            return pool

        # Build conninfo and run the pre-flight probe BEFORE taking self._lock:
        # the lock serializes creation of EVERY per-DSN pool, so holding it
        # across the probe's network round-trip would let one slow database
        # stall pool creation for all others.  The probe is read-only and
        # idempotent; a concurrent cold-start race is resolved by the
        # double-check below.

        # Build conninfo: extract DSN string if present, rest as kwargs.
        # psycopg_pool passes kwargs to psycopg.connect().
        kwargs = dict(connection_info)
        conninfo = kwargs.pop("dsn", "")
        kwargs["autocommit"] = False

        # Per-session GUCs for Odoo's OLTP workload, set via libpq ``options``
        # so they apply at connection establishment (no cursor ops in configure):
        # - jit=off: compile overhead (5-50ms) dwarfs Odoo's sub-10ms queries.
        # - work_mem=16MB: 4MB default forces disk sorts for search_read joins.
        # - idle_session_timeout: server-side net for escaped connections.
        #   Derived as 1.5 * max_idle (floored at 15 min, the value matching the
        #   600s default) so raising ``db_conn_max_idle`` cannot put the pool's
        #   idle window past the server's — the server would then silently kill
        #   warm pooled connections and every borrow past the grace period would
        #   pay a probe failure + reconnect.
        # jit/work_mem are hardcoded, not configurable: tuned for Odoo's
        # profile; override via postgresql.conf if needed.
        options = kwargs.get("options", "")
        if not options and conninfo:
            # A URI's ``?options=...`` GUCs live inside the conninfo string, and
            # psycopg gives per-key precedence to kwargs — so setting ours
            # without folding the URI's in would silently drop the operator's
            # (e.g. a ?options=-csearch_path%3D... on the URI).
            options = _expand_conninfo(conninfo).get("options", "")
        idle_session_ms = max(900, int(self._max_idle * 1.5)) * 1000
        kwargs["options"] = (
            f"{options} -c jit=off -c work_mem=16MB"
            f" -c idle_session_timeout={idle_session_ms}"
        ).strip()

        # Fail fast on permanent connect errors instead of a ~30s pool retry.
        # Cache-miss path only: one extra connect per database per process.
        self._probe_connectable(conninfo, kwargs)

        with self._lock:
            # Double-check after acquiring lock: another thread may have built
            # the pool for this key while we were probing.
            pool = self._pools.get(key)
            if pool is not None and not pool.closed:
                self._note_pool_activity(pool)
                return pool

            # Never warm connections to system/template databases: psycopg_pool
            # maintains min_size by reconnecting after every discard, so the
            # cursor-close discard (Cursor._close keep_in_pool=False) alone
            # cannot keep them connection-free — and an idle connection to a
            # template blocks CREATE DATABASE ... TEMPLATE outright.
            min_size = self._minconn
            if min_size and is_maintenance_db(dict(key).get("database", "")):
                min_size = 0
            pool = _PsycopgPool(
                conninfo,
                connection_class=psycopg.Connection,
                kwargs=kwargs,
                min_size=min_size,
                max_size=self._maxconn,
                max_lifetime=self._max_lifetime,
                max_idle=self._max_idle,
                reconnect_timeout=15,
                configure=_configure_connection,
                reset=_reset_connection,
                check=_check_connection,
                num_workers=3,
                open=True,
            )
            # Mark active before publishing so a fresh pool is never seen as idle
            # by a concurrent reaper running for another key.
            self._note_pool_activity(pool)
            self._pools[key] = pool
            self._debug("Created pool for %s", dict(key))

            # Evict stale-credential siblings: a rotated password yields a new
            # key but strands the old per-DSN pool (its threads/connections) in
            # self._pools.  Drop any sibling matching on every component EXCEPT
            # the password fingerprint — those connections can only fail now.
            ident = frozenset(t for t in key if t[0] != "password_fp")
            stale_keys = [
                k
                for k in self._pools
                if k != key
                and frozenset(t for t in k if t[0] != "password_fp") == ident
            ]
            # Pop under the lock; close OUTSIDE it — close() joins worker threads
            # and must not block sibling pool creation.
            stale_pools = [self._pools.pop(k) for k in stale_keys]

            # Reap idle siblings while holding the lock (stale-cred siblings are
            # already gone, so the sets don't overlap).  Same pop/close discipline.
            reap_keys = self._collect_reapable_pools_locked(exclude_key=key)
            reaped_pools = [self._pools.pop(k) for k in reap_keys]

        for sp in stale_pools:
            self._safe_close(sp)
        if stale_pools:
            _logger.info(
                "%r: evicted %d stale-credential pool(s) after key change",
                self,
                len(stale_pools),
            )
        for rp in reaped_pools:
            self._safe_close(rp)
        if reaped_pools:
            _logger.info(
                "%r: reaped %d idle pool(s) (>%.0fs since last borrow)",
                self,
                len(reaped_pools),
                self._reap_idle_ttl,
            )
        return pool

    def _collect_reapable_pools_locked(
        self, exclude_key: frozenset | None = None
    ) -> list:
        """Return the keys of idle per-DSN pools safe to close.  Caller holds
        ``self._lock``.

        *exclude_key* is the pool the caller is about to use and must never reap
        (the cold path passes the just-created key); ``None`` excludes nothing
        (on the give_back sweep the just-returned pool is protected because
        :meth:`give_back` re-stamps it through :meth:`_note_pool_activity`).

        A pool is reapable when BOTH: it has seen no activity — borrow or return —
        in the last ``reap_idle_ttl`` seconds (so none can be in flight), and it
        holds no checked-out connection (:meth:`_checked_out` ``== 0`` — reliable
        once idle past the TTL, since any async ``reset`` has long since drained,
        so a non-zero reading is a genuine hold like a cron ``LISTEN``).

        Returns ``[]`` when disabled (``reap_idle_ttl <= 0``).
        """
        if self._reap_idle_ttl <= 0:
            return []
        now = monotonic()
        reapable = []
        for k, pool in self._pools.items():
            if k == exclude_key:
                continue
            if now - getattr(pool, _LAST_BORROW_ATTR, now) <= self._reap_idle_ttl:
                continue
            if self._checked_out(pool) > 0:
                continue
            reapable.append(k)
        return reapable

    def _maybe_reap_idle_pools(self) -> None:
        """Throttled idle-pool sweep run from the hot :meth:`give_back` path.

        The cold-path reap only fires on NEW pool creation, so a worker on a
        fixed set of databases would never reap idle siblings for quiet/dropped
        databases.  This sweeps them on the common return path, throttled to once
        per ``self._reap_check_interval`` (a lock-free monotonic compare on the
        common path).  The just-returned pool is never reaped: :meth:`give_back`
        re-stamps it via :meth:`_note_pool_activity` before this sweep runs.
        """
        if self._reap_check_interval <= 0:
            return
        now = monotonic()
        # Lock-free throttle: almost every give_back stops here.
        if now - self._last_reap_check < self._reap_check_interval:
            return
        with self._lock:
            # Re-check under the lock so a burst of concurrent returns runs the
            # (lock-holding) sweep once, not once per thread.
            if now - self._last_reap_check < self._reap_check_interval:
                return
            self._last_reap_check = now
            reap_keys = self._collect_reapable_pools_locked()
            reaped_pools = [self._pools.pop(k) for k in reap_keys]
        if reaped_pools:
            # Close the reaped pools OFF the caller's thread: pool.close() joins
            # ~4 worker threads (up to ~5s), and this runs on the cursor-close
            # hot path (give_back <- Cursor._close), so closing inline would add
            # multi-second tail latency to one unlucky request. The pools are
            # already detached from self._pools under the lock above, so a
            # background close is safe. Reaps are throttled to
            # _reap_check_interval, so at most one such thread runs per interval.
            threading.Thread(
                target=self._close_reaped_pools,
                args=(reaped_pools,),
                name="odoo.db.pool-reaper",
                daemon=True,
            ).start()

    def _close_reaped_pools(self, pools: list[_PsycopgPool]) -> None:
        """Close idle pools reaped on the return path (runs on a daemon thread)."""
        for rp in pools:
            self._safe_close(rp)
        _logger.info(
            "%r: reaped %d idle pool(s) on return (>%.0fs since last borrow)",
            self,
            len(pools),
            self._reap_idle_ttl,
        )

    def borrow(
        self, connection_info: dict, key: frozenset | None = None
    ) -> psycopg.Connection:
        """Borrow a connection from the appropriate per-database pool.

        Acquires a slot from the pool-scoped semaphore first, ensuring the
        total number of checked-out connections across all databases in
        THIS pool instance never exceeds ``maxconn``.  The borrow-timeout
        budget (``db_borrow_timeout``) is shared between the semaphore wait
        and the per-database ``getconn()`` call via a single ``deadline``.

        Semaphore accounting lives ENTIRELY in this method: the permit is taken
        here, released here on any failure, and otherwise travels with the
        connection (tagged via ``_odoo_pool``) to be released by
        :meth:`give_back`.  The two helpers it calls
        (:meth:`_getconn_with_retry`, :meth:`_validate_borrowed_conn`) never
        touch the semaphore, so the permit can neither leak nor double-release.

        :param dict connection_info: dict of psql connection keywords
        :param key: optional pre-normalized routing key.  ``Connection``
            memoizes it once and passes it on every borrow, skipping the
            ``_normalize_dsn_key`` work on this hot path.  ``None`` recomputes it.
        :rtype: psycopg.Connection
        """
        if key is None:
            key = _normalize_dsn_key(connection_info)
        pool = self._get_or_create_pool(key, connection_info)

        deadline = monotonic() + self._borrow_timeout
        if not self._pool_sem.acquire(timeout=self._borrow_timeout):
            raise PoolError(
                f"Could not acquire connection: pool limit ({self._maxconn}) reached, "
                f"all connections are in use across {len(self._pools)} database(s)"
            )
        try:
            conn, pool = self._getconn_with_retry(pool, key, connection_info, deadline)
            self._validate_borrowed_conn(conn, pool)
        except BaseException:
            self._pool_sem.release()
            raise
        return conn

    def _getconn_with_retry(
        self,
        pool: _PsycopgPool,
        key: frozenset,
        connection_info: dict,
        deadline: float,
    ) -> tuple[psycopg.Connection, _PsycopgPool]:
        """``getconn`` from *pool*, rebuilding ONCE if it was closed under us.

        Returns ``(conn, pool)``; the returned pool differs from the argument
        only when a ``PoolClosed`` (reaper / concurrent ``close_database`` race)
        forced a rebuild — the caller must thread it on so the connection's
        ``_odoo_pool`` marker points at the pool it actually came from.  The
        caller holds the ``_pool_sem`` permit across the retry and the shared
        *deadline* bounds the total wait; this method never touches the
        semaphore, so every exit leaves the permit for the caller to release.

        :raises PoolError: capacity/teardown failures (and any unexpected
            non-psycopg error), so callers see one error type.
        :raises psycopg.Error: a connect-phase failure is surfaced verbatim
            (e.g. ``InvalidCatalogName``) so the caller gets the precise cause.
        """
        for attempt in range(2):
            remaining = max(0.1, deadline - monotonic())
            try:
                return pool.getconn(timeout=remaining), pool
            except PoolClosed as e:
                # Drop the stale mapping and rebuild once.  A second PoolClosed
                # means the pool is being actively torn down (not a one-shot reap
                # race), so surface it as PoolError.
                with self._lock:
                    if self._pools.get(key) is pool:
                        del self._pools[key]
                self._safe_close(pool)  # idempotent on an already-closed pool
                if attempt == 1:
                    _logger.info("Connection to the database failed: %s", e)
                    raise PoolError(str(e)) from e
                self._debug("Pool closed under borrow(); rebuilding for %s", dict(key))
                # Rebuild may re-probe and raise InvalidCatalogName if the DB is
                # gone; that propagates to the caller (which releases the sem).
                pool = self._get_or_create_pool(key, connection_info)
            except PoolTimeout as e:
                # Couldn't ESTABLISH a connection in time (the semaphore already
                # guarantees checkout capacity).  Tear the pool down only if it
                # has no live connections (DB gone/unreachable); if some are live
                # the server is just slow, and closing them would turn a latency
                # blip into a reconnect storm.
                if pool.get_stats().get("pool_size", 0) == 0:
                    with self._lock:
                        if self._pools.get(key) is pool:
                            del self._pools[key]
                    self._safe_close(pool)
                _logger.info("Connection to the database failed: %s", e)
                raise PoolError(str(e)) from e
            except psycopg.Error as e:
                _logger.info("Connection to the database failed: %s", e)
                raise
            except Exception as e:
                raise PoolError(str(e)) from e
        # Unreachable: attempt 1's PoolClosed raises instead of looping, and every
        # other branch returns or raises.  Kept so the function never implicitly
        # returns None against its (conn, pool) contract.
        raise PoolError("getconn retry budget exhausted")

    def _validate_borrowed_conn(
        self, conn: psycopg.Connection, pool: _PsycopgPool
    ) -> None:
        """Post-``getconn`` validation of a freshly borrowed *conn*.

        On ANY failure, return *conn* to its per-DSN pool (so the pool slot is
        not leaked) and re-raise; the caller's outer handler releases the
        ``_pool_sem`` permit.  Like :meth:`_getconn_with_retry`, this never
        touches the semaphore.
        """
        try:
            # Minimum-version gate (server_version is client-side, no round-trip).
            # Here rather than in _configure_connection so the caller gets the real
            # message, not a generic borrow-timeout PoolTimeout.
            sv = conn.info.server_version
            if sv < MIN_PG_VERSION * 10000:
                raise PoolError(
                    f"PostgreSQL {sv // 10000}.{sv % 10000} is below the "
                    f"minimum required {MIN_PG_VERSION}.0. Please upgrade "
                    f"to PostgreSQL {MIN_PG_VERSION} or later."
                )
            # Gate on the level: conn.info + backend_pid are eager and this runs on
            # every cursor creation, so pay nothing when DEBUG is off.
            if _logger_conn.isEnabledFor(logging.DEBUG):
                self._debug("Borrow connection backend PID %d", conn.info.backend_pid)
            # Tag the connection with an Odoo-owned back-reference to its pool.
            # give_back() uses THIS marker (not psycopg_pool's private
            # ``conn._pool``) to find the pool and to know a ``_pool_sem`` permit is
            # held, making the accounting self-contained.  Set last, so only a
            # fully-validated connection carries it; on a failure above the
            # connection is putconn()ed with no permit attributed.
            conn._odoo_pool = pool
        except BaseException:
            with contextlib.suppress(Exception):
                pool.putconn(conn)
            raise

    def give_back(
        self, connection: psycopg.Connection, keep_in_pool: bool = True
    ) -> None:
        """Return a connection to its pool.

        Releases a slot from the pool-scoped semaphore after returning the
        connection, keeping the per-instance budget accurate.

        :param connection: The connection to return
        :param keep_in_pool: If False, close the connection before returning
            it so the pool discards it (e.g. for template/system databases).
        """
        # Gate the debug block on the level: connection.info.dsn is eager and
        # give_back() runs on every cursor close, so pay nothing when DEBUG is
        # off.  (Reading .dsn on a closed connection also raises, hence .closed.)
        if _logger_conn.isEnabledFor(logging.DEBUG):
            if not connection.closed:
                self._debug("Give back connection to %r", connection.info.dsn)
            else:
                self._debug("Give back dead connection %r", connection)
        # Use the Odoo-owned marker set by borrow() (not psycopg_pool's private
        # ``conn._pool``) to find the pool and know a permit is held.
        pool = getattr(connection, "_odoo_pool", None)
        if pool is None:
            # Never borrowed or already given back: no permit is held, so
            # releasing would over-increment the bounded semaphore.  The marker
            # survives a closed connection, so this is never a
            # borrowed-then-dropped one.
            if not connection.closed:
                connection.close()
            return

        # Clear the marker BEFORE releasing so a second give_back() hits the
        # no-op branch above instead of releasing the permit twice.
        connection._odoo_pool = None
        # Returning a connection is activity: mark the pool fresh so neither the
        # reap sweep below nor a later one treats a just-used pool as idle.
        # Without this, a connection held longer than reap_idle_ttl and then
        # returned leaves the pool's stamp stale, and the next sweep reaps it —
        # discarding the warm connection and forcing a rebuild + reconnect (and a
        # synchronous pre-flight probe) on the very next use.
        self._note_pool_activity(pool)
        try:
            if not keep_in_pool:
                # Close the connection first; the pool detects the closed
                # connection and discards it, creating a replacement if needed.
                with contextlib.suppress(Exception):
                    connection.close()

            try:
                pool.putconn(connection)
            except Exception:
                _logger.debug("Failed to return connection to pool", exc_info=True)
        finally:
            self._pool_sem.release()
        # Opportunistically reap idle sibling pools (throttled); best-effort, so
        # a reap failure must never escape into the cursor-close finally.
        try:
            self._maybe_reap_idle_pools()
        except Exception:
            _logger.debug("Idle-pool reap on give_back failed", exc_info=True)

    @staticmethod
    def _safe_close(pool: _PsycopgPool) -> None:
        """``pool.close()``, swallowing a per-pool failure.

        One pool's ``close()`` (which joins worker threads and can raise, e.g.
        ``PythonFinalizationError`` at interpreter shutdown) must not abort
        cleanup of its siblings nor escape ``close_all``/``drain_all``.
        """
        try:
            pool.close()
        except Exception:
            _logger.debug("Failed to close pool during teardown", exc_info=True)

    @staticmethod
    def _safe_drain(pool: _PsycopgPool) -> None:
        """``pool.drain()``, swallowing a per-pool failure (see :meth:`_safe_close`)."""
        try:
            pool.drain()
        except Exception:
            _logger.debug("Failed to drain pool", exc_info=True)

    def close_database(self, db_name: str) -> None:
        """Close every per-DSN pool connected to *db_name*.

        Matches on the database component alone (any host/user/URI form) — the
        semantics ``close_db()`` needs when a database is dropped or renamed.
        """
        with self._lock:
            keys = [k for k in self._pools if dict(k).get("database") == db_name]
            pools = [self._pools.pop(k) for k in keys]
        for pool in pools:
            self._safe_close(pool)
        if pools:
            _logger.info("%r: Closed %d pool(s) for %s", self, len(pools), db_name)

    def close_all(self) -> None:
        """Close every per-DSN pool in this instance (full teardown: shutdown,
        ``atexit``).  Single-database close is :meth:`close_database`.
        """
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        count = 0
        for pool in pools:
            self._safe_close(pool)
            count += 1
        if count:
            _logger.info("%r: Closed %d pool(s)", self, count)

    def drain_database(self, db_name: str) -> None:
        """Drain every per-DSN pool connected to *db_name*.

        Name-based matching, like :meth:`close_database` — see there for
        why exact-DSN matching is insufficient.
        """
        with self._lock:
            pools = [
                pool
                for key, pool in self._pools.items()
                if dict(key).get("database") == db_name
            ]
        for pool in pools:
            if not pool.closed:
                self._safe_drain(pool)
        if pools:
            _logger.debug("%r: Drained %d pool(s) for %s", self, len(pools), db_name)

    def drain(self) -> None:
        """Drain every pool — replace idle connections with fresh ones.

        After module upgrades, idle connections may hold stale prepared-statement
        caches referencing old schema; ``drain()`` recycles them.  Single-database
        drain is :meth:`drain_database`.
        """
        # Snapshot under the lock so a concurrent create/close can't raise
        # "dictionary changed size during iteration".
        with self._lock:
            pools = list(self._pools.values())
        for pool in pools:
            if not pool.closed:
                self._safe_drain(pool)
        if pools:
            _logger.debug("%r: Drained %d pool(s)", self, len(pools))

    def get_stats(self) -> dict[str, dict]:
        """Return psycopg_pool stats keyed by database name."""
        # Snapshot under the lock so a concurrent create/close can't raise
        # "dictionary changed size during iteration".
        with self._lock:
            snapshot = list(self._pools.items())
        stats = {}
        for key, pool in snapshot:
            db_name = dict(key).get("database", "unknown")
            stats[db_name] = pool.get_stats()
        return stats


class Connection:
    """A lightweight instance of a connection to postgres"""

    __slots__ = ("__dbname", "__dsn", "__key", "__pool")

    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
        self.__dbname = dbname
        # Private copy: the memoized routing key below is only valid while the
        # dsn is immutable, so don't alias a caller-owned dict it could mutate.
        self.__dsn = dict(dsn)
        self.__pool = pool
        # Memoize the routing key once: ``dsn`` is immutable for this
        # Connection's life, so the key (a BLAKE2s hash of the password plus
        # components) need not be recomputed on every borrow().  Registry caches
        # the Connection per request, making borrow() the module's hottest path.
        self.__key = _normalize_dsn_key(dsn)

    @property
    def dsn(self) -> dict:
        """Connection parameters with the password removed (safe to log).

        A URI/conninfo connection stores its secret *inside* the ``dsn`` string,
        not under a ``password`` key, so a bare ``pop("password")`` would leak it
        when the dict is logged.  :func:`_expand_conninfo` expands the conninfo
        into discrete components first, after which the password drops out cleanly.
        """
        dsn = _expand_conninfo(self.__dsn)
        dsn.pop("password", None)
        return dsn

    @property
    def dbname(self) -> str:
        return self.__dbname

    def cursor(self) -> Cursor:
        """Create a new cursor for this connection.

        Note: Import is done here to avoid circular imports.
        """
        from .cursor import Cursor

        # The dsn property builds a sanitized copy — only pay for it at DEBUG.
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("create cursor to %r", self.dsn)
        return Cursor(self.__pool, self.__dbname, self.__dsn, key=self.__key)
