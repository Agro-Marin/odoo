from __future__ import annotations

import contextlib
import logging
import os
import threading
from time import monotonic
from typing import TYPE_CHECKING

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool
from psycopg_pool import PoolClosed, PoolTimeout

from odoo.release import MIN_PG_VERSION

# DSN normalization + connect-error classification live in their own module
# (pure, security-sensitive, independently testable).  Re-imported here so the
# pool's probe/lifecycle code and existing ``from odoo.db.pool import
# _normalize_dsn_key`` references keep resolving unchanged.
from .dsn import (
    _NON_RETRYABLE_CONNECT_ERRORS,
    _expand_conninfo,
    _normalize_dsn_key,
    _translate_connect_error,
)

# Per-physical-connection lifecycle callbacks (configure/reset/check) live in
# their own module — they hold no pool state and are tested directly.  Imported
# here because pool creation passes them to each per-DSN psycopg_pool; the
# tuning constants they share (``_HEALTHCHECK_GRACE_PERIOD`` / ``_IDLE_SINCE_ATTR``
# / …) stay private to that module and are imported from ``odoo.db.lifecycle``
# by the white-box tests that need them.
from .lifecycle import (
    _check_connection,
    _configure_connection,
    _reset_connection,
)

if TYPE_CHECKING:
    from .cursor import Cursor

_logger = logging.getLogger(__name__)
_logger_conn = _logger.getChild("connection")


class _SuppressKnownPoolWarnings(logging.Filter):
    """Drop known psycopg_pool log records that are not real errors.

    ``filter()`` returns ``False`` for a matched record, which removes it
    entirely (the level is not lowered — there is no demotion, only
    suppression).

    1. ``keep_in_pool=False`` warnings: When connections are intentionally
       closed before returning to the pool, psycopg_pool logs a WARNING
       about "discarding closed connection".  This is expected.

    2. "database does not exist" reconnection warnings: After a database
       is dropped, the pool may still attempt to reconnect for up to
       ``reconnect_timeout`` seconds.  These warnings are noise — the
       caller will get a ``PoolTimeout`` and the pool will be cleaned up.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "discarding closed connection" in msg:
            return False
        # Narrow to the specific PG phrase for a missing database; a broad
        # ``FATAL`` + ``does not exist`` test also swallows legitimate
        # misconfiguration signals like ``role "x" does not exist`` or
        # ``tablespace "x" does not exist``.
        return not ('database "' in msg and "does not exist" in msg)


# Guard against duplicate filters if the module is reloaded (e.g. via
# importlib.reload in test harnesses) — addFilter is not idempotent and
# each extra copy multiplies the per-log-record cost of the suppression
# check.
_psycopg_pool_logger = logging.getLogger("psycopg.pool")
if not any(
    isinstance(f, _SuppressKnownPoolWarnings) for f in _psycopg_pool_logger.filters
):
    _psycopg_pool_logger.addFilter(_SuppressKnownPoolWarnings())

MAX_IDLE_TIMEOUT = 60 * 10
MAX_LIFETIME = 3600  # recycle each pooled connection hourly (stale prep caches)

# Shared wall-clock budget for a single borrow(): the semaphore wait and the
# per-DSN getconn() both draw from this same window.  Named so the two uses in
# borrow() can never silently drift apart.
_BORROW_TIMEOUT = 30.0

# Idle per-DSN pool reaper.  Each database this process touches keeps its own
# psycopg_pool alive — ~3 worker threads plus up to ``maxconn`` idle connections
# — until ``close_database`` / ``close_all``.  A host that serves many databases
# over time therefore accumulates pools (and threads) for ones long gone idle;
# nothing trims the pool OBJECTS, only their connections (``max_idle``).  When a
# NEW pool is created (the cold path, already under ``self._lock``), close any
# sibling that has not been borrowed from in ``_REAP_IDLE_TTL`` seconds AND holds
# no checked-out connection — so a long-lived ``LISTEN`` / cron connection is
# never reaped.  ``_REAP_IDLE_TTL`` is set far above ``_BORROW_TIMEOUT`` so a pool
# this idle provably has no borrow in flight; the residual microsecond race (a
# borrower read the pool from the fast path the instant it was reaped) is
# recovered by ``borrow``'s rebuild-on-``PoolClosed`` retry.  ``0`` disables the
# reaper.  Read once at import — the env never changes mid-process.
try:
    _REAP_IDLE_TTL: float = float(
        os.environ.get("ODOO_DB_POOL_REAP_IDLE", "300") or "300"
    )
except ValueError:
    _REAP_IDLE_TTL = 300.0
# Monotonic timestamp stamped on each per-DSN psycopg pool whenever it is handed
# out by _get_or_create_pool; the reaper measures idleness against it.
_LAST_BORROW_ATTR = "_odoo_last_borrow"

# Throttle for the give_back-path reap sweep (see
# ``ConnectionPool._maybe_reap_idle_pools``).  The cold-path reap in
# ``_get_or_create_pool`` only fires when a NEW per-DSN pool is created, so a
# process serving a FIXED set of databases never reaps idle siblings (their
# worker threads and idle connections survive until ``close_*``).  Sweeping on
# the common return path closes that gap, throttled so the hot give_back path is
# a single monotonic compare almost every time.  A quarter of the TTL: prompt
# enough that an idle pool is reaped soon after crossing the TTL, coarse enough
# to stay off the per-return cost; floored at 1s so a tiny test TTL still yields
# a usable cadence.  ``0`` disables it in lock-step with the reaper itself.
_REAP_CHECK_INTERVAL: float = (
    max(1.0, _REAP_IDLE_TTL / 4) if _REAP_IDLE_TTL > 0 else 0.0
)

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
        The semaphore bounds CHECKED-OUT connections only.  Every per-DSN
        psycopg pool may additionally retain up to ``maxconn`` *idle*
        connections for up to ``max_idle`` (10 min) after a burst, so the
        worst-case server-side footprint of one process is
        ``2 * maxconn * n_databases``, not ``2 * maxconn``.  Single-DB
        deployments are unaffected.  Multi-tenant hosts must size
        PostgreSQL ``max_connections`` accordingly (each per-DSN pool also
        runs ~4 worker threads, and pools are only reaped by
        ``close_database``/``close_all``).
    """

    def __init__(self, maxconn: int = 64, readonly: bool = False, minconn: int = 0):
        # Reject non-positive budgets loudly — the old max(maxconn, 1)
        # silently turned ``db_maxconn=0`` (or a misconfigured gevent
        # override) into a single-slot pool that wedged the whole server
        # under trivial load.
        if maxconn <= 0:
            raise ValueError(f"ConnectionPool maxconn must be >= 1, got {maxconn}")
        # minconn warms that many connections PER per-DSN pool eagerly.  0 keeps
        # the lazy-open default (no idle connections, multi-tenant friendly).
        # It can never exceed the checkout budget, or the pool would open
        # connections it can never hand out.
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
        self._lock = threading.Lock()
        # Per-instance semaphore — gates connections to this pool, not the
        # process.  Name reflects the scope: pool-local, not global.
        self._pool_sem = threading.BoundedSemaphore(self._maxconn)
        # Last monotonic time the give_back-path idle reaper swept (see
        # _maybe_reap_idle_pools).  0.0 lets the first eligible give_back sweep
        # immediately; thereafter throttled to once per _REAP_CHECK_INTERVAL.
        self._last_reap_check = 0.0

    def __repr__(self) -> str:
        # Materialize the pools in ONE atomic step before calling get_stats():
        # ``list()`` over the dict view holds the GIL for its whole duration,
        # so no concurrent _get_or_create_pool()/close_*() can interleave.  The
        # old form iterated ``self._pools.values()`` *lazily* in a generator
        # while calling get_stats() between elements — and get_stats() runs
        # Python / acquires locks, letting another thread create or evict a pool
        # mid-iteration and raise "dictionary changed size during iteration".
        #
        # Deliberately NOT guarded by self._lock (unlike get_stats/close_*):
        # __repr__ is evaluated lazily by logging from inside _debug(), which is
        # itself called while self._lock is held (see _get_or_create_pool).
        # Re-acquiring the non-reentrant lock here would DEADLOCK.  The atomic
        # snapshot is enough — a momentarily-stale entry only skews a debug
        # string, never behaviour.  get_stats() is also called once per pool now
        # (the old code called it twice).
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

    def _probe_connectable(self, conninfo: str, kwargs: dict) -> None:
        """Fail fast on a permanently-unreachable target before building a pool.

        psycopg_pool establishes connections in a background worker and retries
        on failure until the borrower's ~30s ``getconn`` budget runs out — even
        when the failure can never succeed (the database does not exist, the
        password is wrong).  A single synchronous probe surfaces those
        permanent errors in milliseconds.  Anything that might be transient
        (server unreachable, still starting up) is swallowed so the pool's
        normal retry can still recover it.

        .. note::
            This probe runs on every COLD pool creation — including
            *re*-creation after the idle-pool reaper
            (:meth:`_collect_reapable_pools_locked`, ``_REAP_IDLE_TTL``) has
            closed a pool.  On a host that touches a database just slower than
            ``_REAP_IDLE_TTL``, each access pays the reap→recreate→re-probe
            cycle (a fresh synchronous connect, new pool worker threads, and a
            cold prepared-statement cache).  Raise ``ODOO_DB_POOL_REAP_IDLE`` if
            that thrash outweighs the idle-pool savings for your access pattern.

        :raises psycopg.Error: re-raised verbatim for a non-retryable failure,
            so callers see the precise cause (e.g. ``exp_db_exist`` matches
            ``InvalidCatalogName``) instead of an opaque ``PoolError``.
        """
        # Force the probe's own short connect timeout.  _HEALTH_PARAMS already
        # injected connect_timeout=10 into kwargs, so setdefault() would be a
        # silent no-op and the probe would inherit the full 10s — defeating the
        # "surface permanent errors in milliseconds" intent.  Only this
        # throwaway probe is bounded; the real pool connections keep their
        # configured timeout.  Worst case a slow-but-reachable server trips the
        # short timeout, the probe is treated as transient, and we fall through
        # to the pool's normal retry — losing only the optimization, not data.
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
            # The English text-match found nothing — but on a non-English
            # server (e.g. lc_messages=es_MX) a real "database does not exist"
            # hides behind an unclassifiable, localised message.  Confirm
            # locale-independently via the postgres catalog before surrendering
            # to the pool's ~30s retry; this restores ``exp_db_exist``'s fast
            # ``InvalidCatalogName`` path regardless of server language.  Only
            # runs on the already-failed path, so the English happy path pays
            # nothing.
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
        by its (localised) text, so on a non-English server the existence of a
        missing database cannot be inferred from the failure itself.  Here we
        connect to the always-present ``postgres`` maintenance DB — the same
        control DB the rest of :mod:`odoo.service.db` uses — over the identical
        host/auth and ask the catalog directly:
        ``SELECT 1 FROM pg_database WHERE datname = %s``.

        :return: ``True`` only when the catalog *confirms* the database is
            absent.  ``False`` covers both "it exists" and "couldn't tell"
            (no access to ``postgres``, network gone, target *is* ``postgres``)
            — in every uncertain case the caller falls back to treating the
            original error as transient, so this can never manufacture a false
            ``InvalidCatalogName``.
        """
        # Merge the URI/conninfo components with the explicit kwargs (kwargs win,
        # matching psycopg precedence) through the shared expander, which also
        # folds away any embedded ``dsn`` key.
        maint = _expand_conninfo({"dsn": conninfo, **kwargs}) if conninfo else dict(kwargs)
        db_name = kwargs.get("dbname") or maint.get("dbname")
        # Nothing to disambiguate, or the failing target *is* the maintenance
        # DB (probing it through itself is circular) — defer to the caller.
        if not db_name or db_name == "postgres":
            return False
        # Reuse the same host/port/user/password/sslmode; only swap the dbname
        # to ``postgres`` and force autocommit + the short probe timeout.  Drop
        # ``options`` (per-session GUCs are irrelevant to a catalog lookup).
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
            # Maintenance DB unreachable / no CONNECT / auth failure — we cannot
            # tell, so report "not confirmed absent" and let the original error
            # be handled as transient (today's behaviour, no regression).
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
            # Stamp before returning so the reaper sees this pool as freshly
            # used; the write is atomic and intentionally outside the lock to
            # keep the hot fast path lock-free (the reaper's TTL >> borrow time
            # plus borrow()'s PoolClosed retry cover the resulting microrace).
            setattr(pool, _LAST_BORROW_ATTR, monotonic())
            return pool

        # Build conninfo and run the synchronous pre-flight probe BEFORE taking
        # self._lock.  self._lock is process-wide for this ConnectionPool
        # instance and serializes the creation of EVERY per-DSN pool; holding
        # it across the probe's network round-trip lets a single slow or
        # unreachable database stall pool creation for every OTHER database
        # (measured: a 1s probe pushed a sibling database's first connect from
        # 1s to 2s wall).  Both the kwargs build (pure CPU) and the probe
        # (read-only, idempotent) are safe outside the lock; the rare cold-
        # start race where two threads probe the same new key concurrently is
        # harmless — only one wins the create under the double-check below.

        # Build conninfo: extract DSN string if present, rest as kwargs.
        # psycopg_pool passes kwargs to psycopg.connect().
        kwargs = dict(connection_info)
        conninfo = kwargs.pop("dsn", "")
        kwargs["autocommit"] = False

        # Per-session GUCs optimized for Odoo's OLTP workload on PG18.
        # Set via libpq ``options`` so they're applied during connection
        # establishment — no cursor ops needed in the configure callback.
        # - jit=off: compilation overhead (5-50ms) dwarfs execution
        #   savings for Odoo's sub-10ms OLTP queries.
        # - work_mem=16MB: default 4MB causes disk-based sorts for
        #   search_read() with many2one joins + ordering.
        # - idle_session_timeout=15min (PG14+): server-side safety net
        #   for connections that escape pool management.  Set above
        #   pool max_idle (10min) so normal pool recycling takes
        #   precedence; the server only kills truly leaked sessions.
        # NB: these are intentionally hardcoded, not configurable.
        # They are specifically tuned for Odoo's OLTP profile —
        # exposing them in odoo.conf invites misconfiguration with
        # no real upside.  Override via postgresql.conf if needed.
        options = kwargs.get("options", "")
        kwargs["options"] = (
            f"{options} -c jit=off -c work_mem=16MB -c idle_session_timeout=900000"
        ).strip()

        # Fail fast on permanent connect errors (missing DB, bad auth)
        # rather than let psycopg_pool retry them for ~30s.  Cache-miss
        # path only, so the cost (one extra connect for a reachable DB) is
        # paid once per database per process.
        self._probe_connectable(conninfo, kwargs)

        with self._lock:
            # Double-check after acquiring lock: another thread may have built
            # the pool for this key while we were probing.
            pool = self._pools.get(key)
            if pool is not None and not pool.closed:
                setattr(pool, _LAST_BORROW_ATTR, monotonic())
                return pool

            pool = _PsycopgPool(
                conninfo,
                connection_class=psycopg.Connection,
                kwargs=kwargs,
                min_size=self._minconn,
                max_size=self._maxconn,
                max_lifetime=MAX_LIFETIME,
                max_idle=MAX_IDLE_TIMEOUT,
                reconnect_timeout=15,
                configure=_configure_connection,
                reset=_reset_connection,
                check=_check_connection,
                num_workers=3,
                open=True,
            )
            # Stamp before publishing so a fresh pool is never seen as idle by a
            # concurrent reaper running for another key.
            setattr(pool, _LAST_BORROW_ATTR, monotonic())
            self._pools[key] = pool
            self._debug("Created pool for %s", dict(key))

            # Evict stale-credential siblings: a rotated password yields a NEW
            # key (the password fingerprint in _normalize_dsn_key differs) but
            # leaves the OLD per-DSN pool — its worker threads and idle
            # connections — stranded in self._pools until close_all().  Drop any
            # sibling whose key matches this one on every component EXCEPT the
            # password fingerprint; those connections authenticate with the old
            # password and can only fail now.  A genuinely different host / port
            # / user keeps its own pool (those components ARE part of the key).
            ident = frozenset(t for t in key if t[0] != "password_fp")
            stale_keys = [
                k
                for k in self._pools
                if k != key
                and frozenset(t for t in k if t[0] != "password_fp") == ident
            ]
            # Pop under the lock; close OUTSIDE it — _PsycopgPool.close() joins
            # worker threads and must not block sibling pool creation (the same
            # reason the pre-flight probe runs outside self._lock).
            stale_pools = [self._pools.pop(k) for k in stale_keys]

            # Reap idle sibling pools while we already hold the lock (stale-cred
            # siblings are gone from the dict now, so the two sets never
            # overlap).  Same pop-under-lock / close-outside-lock discipline.
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
                _REAP_IDLE_TTL,
            )
        return pool

    def _collect_reapable_pools_locked(
        self, exclude_key: frozenset | None = None
    ) -> list:
        """Return the keys of idle per-DSN pools safe to close.  Caller holds
        ``self._lock``.

        *exclude_key* is the pool the caller is about to use and must never reap
        (the cold path passes the just-created key); ``None`` excludes nothing —
        used by the give_back sweep, where the just-returned pool is protected
        anyway by its fresh ``_LAST_BORROW_ATTR`` stamp.

        A pool is reapable when BOTH hold:

        * it has not been handed out by :meth:`_get_or_create_pool` in the last
          ``_REAP_IDLE_TTL`` seconds (so — given the TTL is far above a borrow's
          ~30s budget — no borrow can be in flight against it), and
        * it currently has no checked-out connection
          (``pool_size - pool_available == 0``).  ``get_stats`` is reliable here
          precisely because the pool has been idle past the TTL: any async
          ``reset`` task from a prior return has long since drained, so a
          non-zero reading means a connection is genuinely held (e.g. a cron
          ``LISTEN``), which must NOT be reaped.

        Returns ``[]`` when the reaper is disabled (``_REAP_IDLE_TTL <= 0``).
        Pools are popped and closed by the caller (outside the lock).
        """
        if _REAP_IDLE_TTL <= 0:
            return []
        now = monotonic()
        reapable = []
        for k, pool in self._pools.items():
            if k == exclude_key:
                continue
            if now - getattr(pool, _LAST_BORROW_ATTR, now) <= _REAP_IDLE_TTL:
                continue
            stats = pool.get_stats()
            if stats.get("pool_size", 0) - stats.get("pool_available", 0) > 0:
                continue
            reapable.append(k)
        return reapable

    def _maybe_reap_idle_pools(self) -> None:
        """Throttled idle-pool sweep run from the hot :meth:`give_back` path.

        The cold-path reap in :meth:`_get_or_create_pool` only fires when a NEW
        per-DSN pool is created.  A worker that settles on a fixed set of
        databases never creates another pool after warm-up, so idle siblings for
        quiet or dropped databases — each carrying ``num_workers`` threads plus up
        to ``maxconn`` idle connections — would survive until ``close_*``.  This
        sweeps them on the common return path instead.

        Throttled to at most once per :data:`_REAP_CHECK_INTERVAL`: the lock-free
        monotonic compare below is the only cost the vast majority of give_backs
        pay.  Same pop-under-lock / close-outside-lock discipline as the cold
        path (``_PsycopgPool.close()`` joins worker threads and must not block
        under ``self._lock``).  The just-returned pool is never reaped — its
        ``_LAST_BORROW_ATTR`` stamp is fresh, well within the TTL
        ``_collect_reapable_pools_locked`` requires.
        """
        if _REAP_CHECK_INTERVAL <= 0:
            return
        now = monotonic()
        # Lock-free throttle: almost every give_back stops here.
        if now - self._last_reap_check < _REAP_CHECK_INTERVAL:
            return
        with self._lock:
            # Re-check under the lock so a burst of concurrent returns runs the
            # (lock-holding) sweep once, not once per thread.
            if now - self._last_reap_check < _REAP_CHECK_INTERVAL:
                return
            self._last_reap_check = now
            reap_keys = self._collect_reapable_pools_locked()
            reaped_pools = [self._pools.pop(k) for k in reap_keys]
        for rp in reaped_pools:
            self._safe_close(rp)
        if reaped_pools:
            _logger.info(
                "%r: reaped %d idle pool(s) on return (>%.0fs since last borrow)",
                self,
                len(reaped_pools),
                _REAP_IDLE_TTL,
            )

    def borrow(
        self, connection_info: dict, key: frozenset | None = None
    ) -> psycopg.Connection:
        """Borrow a connection from the appropriate per-database pool.

        Acquires a slot from the pool-scoped semaphore first, ensuring the
        total number of checked-out connections across all databases in
        THIS pool instance never exceeds ``maxconn``.  The 30-second
        timeout budget is shared between the semaphore wait and the
        per-database ``getconn()`` call.

        :param dict connection_info: dict of psql connection keywords
        :param key: optional pre-normalized pool routing key.  ``Connection``
            memoizes it once (the dsn is immutable for its life) and passes it
            on every cursor()/borrow, so the ``_normalize_dsn_key`` work — a
            dict expansion plus a BLAKE2s hash of the password — is not redone
            on this per-request hot path.  ``None`` recomputes it (bare callers).
        :rtype: psycopg.Connection
        """
        if key is None:
            key = _normalize_dsn_key(connection_info)
        pool = self._get_or_create_pool(key, connection_info)

        deadline = monotonic() + _BORROW_TIMEOUT

        if not self._pool_sem.acquire(timeout=_BORROW_TIMEOUT):
            raise PoolError(
                f"Could not acquire connection: pool limit ({self._maxconn}) reached, "
                f"all connections are in use across {len(self._pools)} database(s)"
            )
        try:
            # getconn, rebuilding ONCE if the per-DSN pool was closed out from
            # under us — the idle-pool reaper or a concurrent close_database can
            # close a pool a borrower already holds a reference to.  The
            # semaphore permit is already held and is NOT re-acquired on retry;
            # the shared ``deadline`` still bounds the total wait.
            for attempt in range(2):
                remaining = max(0.1, deadline - monotonic())
                try:
                    conn = pool.getconn(timeout=remaining)
                    break
                except PoolClosed as e:
                    # Drop the stale mapping and rebuild once.  A second
                    # PoolClosed means the pool is being actively torn down (not
                    # a one-shot reap race), so surface it as PoolError.
                    with self._lock:
                        if self._pools.get(key) is pool:
                            del self._pools[key]
                    self._safe_close(pool)  # idempotent on an already-closed pool
                    if attempt == 1:
                        _logger.info("Connection to the database failed: %s", e)
                        raise PoolError(str(e)) from e
                    self._debug(
                        "Pool closed under borrow(); rebuilding for %s", dict(key)
                    )
                    # Rebuild may re-probe and raise InvalidCatalogName if the
                    # database is genuinely gone — that propagates (correctly) to
                    # the outer handler, which releases the semaphore.
                    pool = self._get_or_create_pool(key, connection_info)
                except PoolTimeout as e:
                    # A timeout means the pool couldn't ESTABLISH a connection in
                    # time (the semaphore guarantees checkout capacity).  Tear
                    # the pool down only when it holds no live connections — i.e.
                    # the database is gone or fully unreachable (e.g. after DB
                    # drop), so the next borrow() builds a fresh pool.  If live
                    # connections exist, the server is reachable but slow;
                    # closing them here would turn a latency blip into a
                    # reconnect storm.
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
            # Post-getconn validation.  Any failure here must do TWO things:
            # return the connection to its psycopg pool (the inner handler) so
            # the pool slot is not leaked, AND release the semaphore (the outer
            # handler).  The earlier version released only the semaphore, so a
            # raise from conn.info access left the psycopg-pool slot checked out
            # forever — exhausting the per-DSN pool over time.
            try:
                # Minimum-version gate: server_version is read from the
                # connection startup packet (client-side, no round-trip).
                # Checked here rather than in _configure_connection so the
                # caller gets the actionable message immediately instead of a
                # generic PoolTimeout after 30s of futile worker retries.
                sv = conn.info.server_version
                if sv < MIN_PG_VERSION * 10000:
                    raise PoolError(
                        f"PostgreSQL {sv // 10000}.{sv % 10000} is below the "
                        f"minimum required {MIN_PG_VERSION}.0. Please upgrade "
                        f"to PostgreSQL {MIN_PG_VERSION} or later."
                    )
                # ``conn.info`` allocates a fresh ConnectionInfo and
                # ``backend_pid`` is a libpq call, both eager as a call argument
                # — gate on the level so this hot path (every cursor creation)
                # pays nothing when DEBUG is off.  Mirrors the isEnabledFor guard
                # in give_back() and Connection.cursor().
                if _logger_conn.isEnabledFor(logging.DEBUG):
                    self._debug(
                        "Borrow connection backend PID %d", conn.info.backend_pid
                    )
                # Tag the connection with an Odoo-owned back-reference to its
                # per-DSN psycopg pool.  give_back() uses THIS marker — not
                # psycopg_pool's private ``conn._pool`` — both to locate the
                # pool to return to and to decide whether a ``_pool_sem`` permit
                # is held.  Owning the marker makes the semaphore accounting
                # self-contained: it can no longer break if a future
                # psycopg_pool stops tagging connections at checkout (the old
                # design read ``conn._pool`` and would have leaked a permit on
                # every return).  Set last, so it marks only a fully-validated
                # connection we are committed to handing out; a failure above
                # leaves it unset and the inner handler putconn()s the
                # connection with no permit attributed to it.
                conn._odoo_pool = pool
            except BaseException:
                with contextlib.suppress(Exception):
                    pool.putconn(conn)
                raise
        except BaseException:
            self._pool_sem.release()
            raise

        return conn

    def give_back(
        self, connection: psycopg.Connection, keep_in_pool: bool = True
    ) -> None:
        """Return a connection to its pool.

        Releases a slot from the pool-scoped semaphore after returning the
        connection, keeping the per-instance budget accurate.

        :param connection: The connection to return
        :param keep_in_pool: If False, close the connection before returning
            it so the pool discards it (used for template databases).
        """
        # Gate the whole debug block behind the level check: connection.info.dsn
        # is evaluated eagerly as a call argument, and give_back() runs on every
        # cursor close, so accessing it unconditionally costs a DSN build on the
        # hot path even when DEBUG is off.  Mirrors the isEnabledFor guard in
        # Connection.cursor().  (Reading .dsn on a closed connection also raises
        # OperationalError — dead connections are a normal path in here, e.g.
        # rollback after a network drop — hence the .closed branch.)
        if _logger_conn.isEnabledFor(logging.DEBUG):
            if not connection.closed:
                self._debug("Give back connection to %r", connection.info.dsn)
            else:
                self._debug("Give back dead connection %r", connection)
        # Use the Odoo-owned marker set by borrow() — NOT psycopg_pool's private
        # ``conn._pool`` — to recover the per-DSN pool and to decide whether this
        # connection holds a ``_pool_sem`` permit.
        pool = getattr(connection, "_odoo_pool", None)
        if pool is None:
            # Never borrowed (e.g. a manually-created connection), or already
            # given back: it holds no _pool_sem permit, so releasing here would
            # over-increment the bounded semaphore and inflate the budget.  The
            # marker survives a dead/closed connection (it is a plain instance
            # attribute), so this branch is reached only by genuine non-borrowed
            # connections, never by a borrowed-then-dropped one.
            if not connection.closed:
                connection.close()
            return

        # Clear the marker BEFORE releasing so a second give_back() on the same
        # connection takes the no-op branch above instead of releasing a permit
        # twice — a BoundedSemaphore rejects over-release with ValueError, and
        # it would otherwise inflate the budget.
        connection._odoo_pool = None
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
        # Opportunistically reap idle sibling pools on this common return path
        # (throttled — see _maybe_reap_idle_pools) so they don't accumulate when
        # no new pool is ever created.  Best-effort housekeeping: the connection
        # is already back and the permit released, so a reap failure must never
        # escape give_back into the cursor-close finally that calls it.
        try:
            self._maybe_reap_idle_pools()
        except Exception:
            _logger.debug("Idle-pool reap on give_back failed", exc_info=True)

    @staticmethod
    def _safe_close(pool: _PsycopgPool) -> None:
        """``pool.close()``, swallowing a per-pool failure.

        One pool's ``close()`` must not abort cleanup of its siblings, nor
        propagate out of the ``atexit`` handler (``close_all``) or a
        post-upgrade ``drain_all``.  ``close()`` joins worker threads and can
        raise (e.g. ``PythonFinalizationError`` if reached during interpreter
        finalization).  Mirrors the isolation already applied in
        :meth:`give_back` and the stale-credential eviction in
        :meth:`_get_or_create_pool`.
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

        Matches on the database component alone, regardless of host, user
        or URI-vs-keyword form — the semantics ``close_db()`` needs when a
        database is dropped or renamed.  ``close_all(dsn)`` requires an
        exact full-DSN match and therefore misses pools created through a
        URI when the caller only knows the database name.
        """
        with self._lock:
            keys = [k for k in self._pools if dict(k).get("database") == db_name]
            pools = [self._pools.pop(k) for k in keys]
        for pool in pools:
            self._safe_close(pool)
        if pools:
            _logger.info("%r: Closed %d pool(s) for %s", self, len(pools), db_name)

    def close_all(self) -> None:
        """Close every per-DSN pool in this instance.

        Used for full teardown (server shutdown, ``atexit``).  Closing the
        pools for a single database is :meth:`close_database` (name-based);
        there is intentionally no by-DSN variant — nothing needs one.
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
        """Drain every pool — replace all idle connections with fresh ones.

        After module upgrades, idle connections may hold stale prepared
        statement caches referencing old schema.  ``drain()`` recycles
        them so the next borrow gets a freshly configured connection.
        Draining a single database is :meth:`drain_database` (name-based);
        there is intentionally no by-DSN variant — nothing needs one.
        """
        # Snapshot under the lock so a concurrent _get_or_create_pool()
        # or close_all() can't mutate the dict mid-iteration (would
        # raise "dictionary changed size during iteration" otherwise).
        with self._lock:
            pools = list(self._pools.values())
        for pool in pools:
            if not pool.closed:
                self._safe_drain(pool)
        if pools:
            _logger.debug("%r: Drained %d pool(s)", self, len(pools))

    def get_stats(self) -> dict[str, dict]:
        """Return pool statistics for all databases.

        Returns a dict keyed by database name with psycopg_pool stats.
        """
        # Snapshot under the lock so a concurrent _get_or_create_pool() or
        # close_all() can't mutate the dict mid-iteration (would raise
        # "dictionary changed size during iteration" otherwise).
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
        self.__dsn = dsn
        self.__pool = pool
        # Memoize the pool routing key once.  ``dsn`` is immutable for this
        # Connection's life — ``db_connect`` builds a fresh dict and never
        # mutates it, and ``_get_or_create_pool`` copies it before mutating —
        # so the key (which includes a BLAKE2s hash of the password) need not be
        # recomputed on every cursor()/borrow().  Registry caches the Connection
        # and reuses it per request, making borrow() the module's hottest path.
        self.__key = _normalize_dsn_key(dsn)

    @property
    def dsn(self) -> dict:
        """Connection parameters with the password removed (safe to log).

        A URI/conninfo connection stores its secret *inside* the ``dsn``
        string value, not under a ``password`` key, so a bare
        ``pop("password")`` leaks it whenever this dict is logged — e.g. by
        ``cursor()`` at DEBUG, reachable in production via ``log_db`` URIs
        (``logutils``).  :func:`_expand_conninfo` expands the conninfo string
        into discrete components first — the same treatment
        :func:`_normalize_dsn_key` and psycopg's own ``info.dsn`` apply, with
        explicit keywords winning per psycopg precedence — after which the
        password drops out cleanly.
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

        # The dsn property builds a sanitized dict copy — only pay for it
        # when DEBUG is actually enabled (cursor creation is per-request).
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("create cursor to %r", self.dsn)
        return Cursor(self.__pool, self.__dbname, self.__dsn, key=self.__key)
