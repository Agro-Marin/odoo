from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import threading
from time import monotonic
from typing import TYPE_CHECKING

import psycopg
from psycopg_pool import ConnectionPool as _PsycopgPool
from psycopg_pool import PoolClosed, PoolTimeout

from odoo import tools
from odoo.release import MIN_PG_VERSION

from .budget import ConnectionBudget
from .dsn import (
    _NON_RETRYABLE_CONNECT_ERRORS,
    _expand_conninfo,
    _normalize_dsn_key,
    _translate_connect_error,
)
from .leaks import CheckoutTracker
from .lifecycle import (
    _check_connection,
    _configure_connection,
    _reset_connection,
)
from .reaper import IdlePoolReaper, note_activity
from .stats import PoolStats
from .utils import is_maintenance_db

if TYPE_CHECKING:
    from types import FrameType

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
        return not ('database "' in msg and "does not exist" in msg)


_psycopg_pool_logger = logging.getLogger("psycopg.pool")
if not any(
    isinstance(f, _SuppressKnownPoolWarnings) for f in _psycopg_pool_logger.filters
):
    _psycopg_pool_logger.addFilter(_SuppressKnownPoolWarnings())

_DEFAULT_MAX_IDLE = 60 * 10
_DEFAULT_MAX_LIFETIME = 3600
_DEFAULT_BORROW_TIMEOUT = 30.0
_DEFAULT_REAP_IDLE_TTL = 300.0

_PROBE_CONNECT_TIMEOUT = 5

_DIRECT_CONNECTION = object()

_DIRECT_IDLE_SESSION_TIMEOUT_MS = 900 * 1000

_LEAK_REPORT_INTERVAL = 60.0


def _remaining(deadline: float | None) -> float:
    """Seconds left before *deadline*; ``inf`` when it is ``None`` (unbounded)."""
    return float("inf") if deadline is None else deadline - monotonic()


def _libpq_connect_timeout(deadline: float | None, cap: int) -> int:
    """Clamp *cap* to the seconds left before *deadline*, for libpq.

    Returns ``0`` when nothing usable is left, which callers MUST read as "skip
    this connect entirely" — never as a value to hand libpq.  libpq treats
    ``connect_timeout=0`` (and negative) as *wait indefinitely* and silently
    raises ``1`` to ``2``, so naively passing a shrinking budget would turn the
    tail of a deadline into an unbounded connect: the exact overrun this guards.

    ``deadline`` of ``None`` means unbounded and yields *cap* unchanged.
    """
    if deadline is None:
        return cap
    remaining = int(deadline - monotonic())
    if remaining < 1:
        return 0
    return min(cap, remaining)


def _base_conn_options(conninfo: str, kwargs: dict) -> str:
    """Resolve the libpq ``options`` GUC string Odoo should extend.

    Precedence (most specific wins): an explicit ``options`` kwarg, then GUCs
    embedded in the URI/conninfo string (psycopg gives per-key precedence to
    kwargs, so setting ours without folding the URI's in would silently drop
    the operator's, e.g. ``?options=-csearch_path%3D...``), then the operator's
    ``PGOPTIONS`` environment variable — which libpq would honour on its own
    were we not about to pass an explicit kwarg that overrides it wholesale.
    """
    options = kwargs.get("options", "")
    if not options and conninfo:
        options = _expand_conninfo(conninfo).get("options", "")
    if not options:
        options = os.environ.get("PGOPTIONS", "")
    return options


_GUC_NAME_RE = re.compile(r"-c\s*([A-Za-z_][A-Za-z0-9_.]*)\s*=")


def _session_gucs(base_options: str) -> str:
    """Render Odoo's session GUCs, yielding to any the operator already set.

    Odoo appends ``-c`` switches to *base_options*, and libpq lets the last
    occurrence win — so appending unconditionally silently overrode an operator
    who had asked for something else.  ``PGOPTIONS='-c work_mem=64MB -c jit=on'``
    arrived at the backend as ``work_mem=16MB``/``jit=off``, with nothing in any
    log to say why.

    ``db_session_gucs`` carries the defaults (``jit=off`` — Odoo's queries are
    short and the planner's JIT decisions cost more than they save; ``work_mem``
    sized for OLTP sorts), so a deployment can retune them without patching, and
    an explicitly-set GUC always beats Odoo's default for that key.
    """
    already_set = set(_GUC_NAME_RE.findall(base_options))
    configured = tools.config["db_session_gucs"] or ""
    gucs = [
        f"-c {name}={value}"
        for entry in configured.split(",")
        if (name := entry.partition("=")[0].strip())
        and (value := entry.partition("=")[2].strip())
        and name not in already_set
    ]
    return " ".join(gucs)


def _borrow_caller() -> str | None:
    """Where this borrow came from: the first frame outside ``odoo/db``.

    Always captured, not gated behind ``db_leak_detection``, because it turns
    out to be cheap: the loop stops at the first application frame, so the walk
    is 2-3 frames whatever the stack below it looks like.  Measured 300 ns flat
    at 0, 10 and 40 extra frames of depth — less than the 413 ns the tracker's
    own dict insert/delete pair costs.  Gating it would have saved nothing and
    left the saturation error unable to name a culprit on the deployments that
    had not opted in, which is exactly when it is needed.

    Frames inside ``odoo/db`` are skipped: the useful answer is the application
    code that opened a cursor, not ``Connection.cursor`` or ``Cursor.__init__``.
    """
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if f"{os.sep}odoo{os.sep}db{os.sep}" not in name:
            return f"{name}:{frame.f_lineno}"
        frame = frame.f_back
    return None


class PoolError(Exception):
    """Connection pool error."""


class ConnectionPool:
    """Manages per-database psycopg_pool.ConnectionPool instances.

    Each unique DSN (database) gets its own psycopg_pool with:
    - Health checks on borrow (detects dead connections)
    - max_lifetime rotation (recycles connections every hour)
    - Background workers for connection creation
    - Pool statistics via get_stats()

    Connection budget is enforced by ``_budget``, a :class:`ConnectionBudget`.
    ``odoo/db/__init__.py`` builds ONE and hands it to both the R/W and the
    read-only pool, so ``db_maxconn`` caps the whole process (see that class).
    A directly-constructed pool gets its own budget sized at ``maxconn``.

    .. warning::
        The budget bounds CHECKED-OUT connections only.  Each per-DSN pool may
        also retain up to ``maxconn`` *idle* connections for ``max_idle``
        (10 min), so one process's worst-case server footprint is
        ``maxconn * n_databases``.  Multi-tenant hosts must size PostgreSQL
        ``max_connections`` accordingly (each per-DSN pool also runs ~4 worker
        threads; pools are reaped by the idle reaper and by
        ``close_database``/``close_all``).
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
        budget: ConnectionBudget | None = None,
    ):
        if maxconn <= 0:
            raise ValueError(f"ConnectionPool maxconn must be >= 1, got {maxconn}")
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
        self._borrow_timeout = borrow_timeout
        self._max_lifetime = max_lifetime
        self._max_idle = max_idle
        self._reaper = IdlePoolReaper(reap_idle_ttl)
        self._lock = threading.Lock()
        self.stats = PoolStats()
        self._checkouts = CheckoutTracker()
        self._budget = budget if budget is not None else ConnectionBudget(maxconn)
        self._direct_out = 0
        self._reachable_keys: set[frozenset] = set()

    def __repr__(self) -> str:
        pools = list(self._pools.values())
        total = available = 0
        for p in pools:
            stats = p.get_stats()
            total += stats.get("pool_size", 0)
            available += stats.get("pool_available", 0)
        used = total - available
        mode = "read-only" if self._readonly else "read/write"
        direct = self._direct_out
        return (
            f"ConnectionPool({mode};used={used}/total={total}"
            f"/limit={self._budget.maxconn};dbs={len(pools)};direct={direct})"
        )

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _debug(self, msg: str, *args: object) -> None:
        _logger_conn.debug(("%r " + msg), self, *args)

    def _is_proven_reachable(self, key: frozenset) -> bool:
        """True when this process has already connected with *key* successfully.

        The pre-flight probe exists to convert a permanent connect failure
        (missing database, wrong password) from a ~30s ``PoolTimeout`` into a
        millisecond ``InvalidCatalogName``.  It costs a full extra connect, and
        it ran on every pool *rebuild* — not just the first sight of a DSN.  With
        the default tuning (``db_pool_reap_idle`` 300s below ``db_conn_max_idle``
        600s) a database touched every few minutes is reaped and rebuilt
        repeatedly, so a host serving many quiet databases paid that connect over
        and over to re-answer a question it had already answered.

        A DSN that connected once is not going to be a *typo*, so the fast-fail
        the probe buys is worthless for it.  The proof is dropped whenever the
        premise could have changed: the database was closed out
        (:meth:`close_database` — Odoo's own drop/rename path, and
        :meth:`close_all`), the credentials rotated (stale-key eviction), or a
        connect actually failed (:meth:`_getconn_with_retry`).  A database
        dropped *behind Odoo's back* therefore falls back to the pool's own
        bounded retry for one borrow, and the failure there un-proves the key
        for the next.

        The proof set is the one piece of per-DSN state the idle reaper does not
        collect — deliberately, since reaping a quiet pool says nothing about
        reachability — so it grows monotonically with the number of distinct
        DSNs this process has ever reached (~330 bytes each; ~3 MB at 10k
        databases).
        """
        return key in self._reachable_keys

    def _mark_reachable(self, key: frozenset) -> None:
        """Record that *key* connected successfully (see :meth:`_is_proven_reachable`)."""
        self._reachable_keys.add(key)

    def _forget_reachable(self, key: frozenset) -> None:
        """Drop *key*'s reachability proof, so the next cold start re-probes."""
        self._reachable_keys.discard(key)

    def _probe_connectable(
        self, conninfo: str, kwargs: dict, deadline: float | None = None
    ) -> None:
        """Fail fast on a permanently-unreachable target before building a pool.

        psycopg_pool retries failed connections in a background worker until the
        borrower's ~30s budget expires — even for permanent failures (missing
        database, wrong password).  One synchronous probe surfaces those in
        milliseconds; anything possibly transient is swallowed for the pool's
        normal retry.

        *deadline* is the borrower's shared budget (see :meth:`borrow`).  Both
        connects below draw from it, so a black-holed host cannot push a borrow
        past ``db_borrow_timeout``; with no budget left the probe is skipped
        entirely and the pool's own bounded ``getconn`` reports the failure.

        .. note::
            Runs on every COLD pool creation for a DSN this process has not yet
            reached — see :meth:`_is_proven_reachable` for why a *re*-creation
            (after the idle reaper, or after a ``PoolClosed`` rebuild) skips it.

        :raises psycopg.Error: re-raised verbatim for a non-retryable failure,
            so callers see the precise cause (e.g. ``InvalidCatalogName``).
        """
        probe_timeout = _libpq_connect_timeout(deadline, _PROBE_CONNECT_TIMEOUT)
        if not probe_timeout:
            return
        self.stats.probe_run += 1
        probe_kwargs = {**kwargs, "autocommit": True}
        probe_kwargs["connect_timeout"] = probe_timeout
        try:
            psycopg.connect(conninfo, **probe_kwargs).close()
        except _NON_RETRYABLE_CONNECT_ERRORS:
            self.stats.probe_permanent += 1
            raise
        except psycopg.OperationalError as e:
            translated = _translate_connect_error(e)
            if translated is not None:
                self.stats.probe_permanent += 1
                raise translated from e
            if self._database_absent(conninfo, kwargs, deadline):
                self.stats.probe_permanent += 1
                raise psycopg.errors.InvalidCatalogName(str(e)) from e
            self.stats.probe_transient += 1
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )
        except Exception:
            self.stats.probe_transient += 1
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )

    def _database_absent(
        self, conninfo: str, kwargs: dict, deadline: float | None = None
    ) -> bool:
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
        maint = (
            _expand_conninfo({"dsn": conninfo, **kwargs}) if conninfo else dict(kwargs)
        )
        db_name = kwargs.get("dbname") or maint.get("dbname")
        if not db_name or db_name == "postgres":
            return False
        maint.pop("options", None)
        maint["dbname"] = "postgres"
        maint["autocommit"] = True
        probe_timeout = _libpq_connect_timeout(deadline, _PROBE_CONNECT_TIMEOUT)
        if not probe_timeout:
            return False
        maint["connect_timeout"] = probe_timeout
        try:
            with psycopg.connect("", **maint) as mc:
                row = mc.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
                ).fetchone()
            return row is None
        except Exception:
            _logger.debug(
                "pg_database existence check unavailable for %r",
                db_name,
                exc_info=True,
            )
            return False

    def _get_or_create_pool(
        self, key: frozenset, connection_info: dict, deadline: float | None = None
    ) -> _PsycopgPool:
        """Get an existing pool for this DSN or create a new one.

        *deadline* bounds the cold path's pre-flight probe against the borrower's
        budget (see :meth:`borrow`); the warm path never touches the network.
        """
        pool = self._pools.get(key)
        if pool is not None and not pool.closed:
            note_activity(pool)
            return pool

        kwargs = dict(connection_info)
        conninfo = kwargs.pop("dsn", "")
        kwargs["autocommit"] = False

        options = _base_conn_options(conninfo, kwargs)
        idle_session_ms = max(900, int(self._max_idle * 1.5)) * 1000
        kwargs["options"] = (
            f"{options} {_session_gucs(options)}"
            f" -c idle_session_timeout={idle_session_ms}"
        ).strip()

        if self._is_proven_reachable(key):
            self.stats.probe_skipped_proven += 1
        else:
            self._probe_connectable(conninfo, kwargs, deadline)

        with self._lock:
            pool = self._pools.get(key)
            if pool is not None and not pool.closed:
                note_activity(pool)
                return pool

            pool = _PsycopgPool(
                conninfo,
                connection_class=psycopg.Connection,
                kwargs=kwargs,
                min_size=self._minconn,
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
            note_activity(pool)
            self._pools[key] = pool
            self.stats.pools_created += 1
            self._debug("Created pool for %s", dict(key))

            ident = frozenset(t for t in key if t[0] != "password_fp")
            stale_keys = [
                k
                for k in self._pools
                if k != key
                and frozenset(t for t in k if t[0] != "password_fp") == ident
            ]
            stale_pools = [self._pools.pop(k) for k in stale_keys]
            for k in stale_keys:
                self._forget_reachable(k)

            reap_keys = self._reaper.collect(self._pools, exclude_key=key)
            reaped_pools = [self._pools.pop(k) for k in reap_keys]

        for sp in stale_pools:
            self._safe_close(sp)
        if stale_pools:
            self.stats.pools_evicted_stale += len(stale_pools)
            _logger.info(
                "%r: evicted %d stale-credential pool(s) after key change",
                self,
                len(stale_pools),
            )
        for rp in reaped_pools:
            self._safe_close(rp)
        if reaped_pools:
            self.stats.pools_reaped += len(reaped_pools)
            _logger.info(
                "%r: reaped %d idle pool(s) (>%.0fs since last borrow)",
                self,
                len(reaped_pools),
                self._reaper.ttl,
            )
        return pool

    def _maybe_reap_idle_pools(self) -> None:
        """Throttled idle-pool sweep run from the hot :meth:`give_back` path.

        The cold-path reap only fires on NEW pool creation, so a worker on a
        fixed set of databases would never reap idle siblings for quiet or
        dropped databases.  This sweeps them on the common return path, behind
        the reaper's throttle (a lock-free compare first, so the common return
        pays nothing).  The just-returned pool is never reaped: :meth:`give_back`
        re-stamps it through ``reaper.note_activity`` before this runs.
        """
        if not self._reaper.probably_due():
            return
        with self._lock:
            if not self._reaper.due():
                return
            reap_keys = self._reaper.collect(self._pools)
            reaped_pools = [self._pools.pop(k) for k in reap_keys]
        if reaped_pools:
            IdlePoolReaper.close_in_background(
                self._close_reaped_pools, reaped_pools, "odoo.db.pool-reaper"
            )

    def _close_reaped_pools(self, pools: list[_PsycopgPool]) -> None:
        """Close idle pools reaped on the return path (runs on a daemon thread)."""
        for rp in pools:
            self._safe_close(rp)
        self.stats.pools_reaped += len(pools)
        _logger.info(
            "%r: reaped %d idle pool(s) on return (>%.0fs since last borrow)",
            self,
            len(pools),
            self._reaper.ttl,
        )

    def borrow(
        self, connection_info: dict, key: frozenset | None = None
    ) -> psycopg.Connection:
        """Borrow a connection from the appropriate per-database pool.

        Acquires a slot from the pool-scoped semaphore first, ensuring the
        total number of checked-out connections across all databases in
        THIS pool instance never exceeds ``maxconn``.  The borrow-timeout
        budget (``db_borrow_timeout``) is shared by EVERY step that can block —
        the cold path's pre-flight probe, the semaphore wait and the per-database
        ``getconn()`` — via a single ``deadline`` taken before the first of them.
        (It used to be taken *after* pool creation, so a black-holed host cost
        two 5s probe connects on top of the budget: measured 13s against a
        documented 3s.)

        Semaphore accounting lives ENTIRELY in this method: the permit is taken
        here, released here on any failure, and otherwise travels with the
        connection (tagged via ``_odoo_pool``) to be released by
        :meth:`give_back`.  The two helpers it calls
        (:meth:`_getconn_with_retry`, :meth:`_validate_borrowed_conn`) never
        touch the semaphore, so the permit can neither leak nor double-release.
        (Maintenance databases short-circuit into :meth:`_borrow_direct`, which
        keeps the same permit discipline for its never-pooled connections.)

        :param dict connection_info: dict of psql connection keywords
        :param key: optional pre-normalized routing key.  ``Connection``
            memoizes it once and passes it on every borrow, skipping the
            ``_normalize_dsn_key`` work on this hot path.  ``None`` recomputes it.
        :rtype: psycopg.Connection
        """
        started = monotonic()
        deadline = started + self._borrow_timeout
        if key is None:
            key = _normalize_dsn_key(connection_info)
        dbname = connection_info.get("dbname") or dict(key).get("database", "")
        if is_maintenance_db(dbname):
            return self._borrow_direct(connection_info, deadline)
        try:
            pool = self._get_or_create_pool(key, connection_info, deadline)
        except BaseException:
            self.stats.borrows_failed += 1
            raise

        if not self._budget.acquire(deadline - monotonic()):
            self.stats.borrows_failed += 1
            raise PoolError(
                f"Could not acquire connection: connection budget "
                f"({self._budget.maxconn}) reached, "
                f"all connections are in use across {len(self._pools)} database(s) "
                f"(+{self._direct_out} direct maintenance connection(s)). "
                f"{self._checkouts.describe()}"
            )
        try:
            conn, pool = self._getconn_with_retry(pool, key, connection_info, deadline)
            self._validate_borrowed_conn(conn, pool)
            self._mark_reachable(key)
        except BaseException:
            self._budget.release()
            self.stats.borrows_failed += 1
            raise
        self._checkouts.track(conn, _borrow_caller())
        self._warn_about_leaks()
        self.stats.record_borrow(started)
        return conn

    def _warn_about_leaks(self) -> None:
        """Report connections held past ``db_leak_detection``.

        Reported from :meth:`borrow` rather than a timer: a leak only matters
        when someone else needs a connection, and that is exactly when this
        runs.  Throttled by the tracker's own clock — never the reaper's, whose
        slot belongs to reaping quiet pools.
        """
        threshold = tools.config["db_leak_detection"]
        if not threshold:
            return
        if not self._checkouts.due_for_report(max(_LEAK_REPORT_INTERVAL, threshold)):
            return
        held = self._checkouts.describe(older_than=threshold)
        if held:
            self.stats.leaks_reported += 1
            _logger.warning(
                "%r: connection(s) checked out longer than %ss; %s",
                self,
                threshold,
                held,
            )

    def _borrow_direct(
        self, connection_info: dict, deadline: float | None = None
    ) -> psycopg.Connection:
        """Open a dedicated, never-pooled connection to a maintenance database.

        ``postgres``/template databases must be connection-free the moment no
        cursor is open on them, or ``CREATE DATABASE`` / ``DROP DATABASE``
        against them fails with "being accessed by other users".  A psycopg_pool
        cannot guarantee that: it replaces every discarded connection to keep
        its connection count, so the old discard-on-close approach left an idle
        replacement parked on the database (verified: it blocks
        ``CREATE DATABASE ... TEMPLATE`` until the idle-pool reaper fires).

        The connection still draws a ``_budget`` permit (the budget is
        per-instance, not per-DSN) and is tagged ``_DIRECT_CONNECTION`` so
        :meth:`give_back` closes it instead of returning it anywhere.
        ``keep_in_pool`` is irrelevant on this path — the connection is always
        closed on return.

        Deliberately skipped versus the pooled path: the OLTP session GUCs
        ``jit``/``work_mem`` (pointless for short-lived catalog work) and the
        pre-flight probe (a direct connect already fails fast with the precise
        error).  ``idle_session_timeout`` IS applied — it is the server-side
        net that reclaims an escaped connection, and an idle session parked on
        a template blocks ``CREATE DATABASE ... TEMPLATE``.  Outstanding
        direct connections are counted in ``_direct_out`` (repr/exhaustion
        messages); the per-DSN ``get_stats()`` never sees them.
        """
        kwargs = dict(connection_info)
        conninfo = kwargs.pop("dsn", "")
        kwargs["autocommit"] = False
        options = _base_conn_options(conninfo, kwargs)
        kwargs["options"] = (
            f"{options} -c idle_session_timeout={_DIRECT_IDLE_SESSION_TIMEOUT_MS}"
        ).strip()
        if not self._budget.acquire(_remaining(deadline)):
            self.stats.borrows_failed += 1
            raise PoolError(
                f"Could not acquire connection: connection budget "
                f"({self._budget.maxconn}) reached, all connections are in use across "
                f"{len(self._pools)} database(s) "
                f"(+{self._direct_out} direct maintenance connection(s)). "
                f"{self._checkouts.describe()}"
            )
        if deadline is not None:
            connect_timeout = _libpq_connect_timeout(
                deadline, int(kwargs.get("connect_timeout", _PROBE_CONNECT_TIMEOUT))
            )
            if not connect_timeout:
                self._budget.release()
                raise PoolError(
                    f"Could not acquire connection to maintenance database "
                    f"within the {self._borrow_timeout}s borrow budget"
                )
            kwargs["connect_timeout"] = connect_timeout
        try:
            conn = psycopg.connect(conninfo, **kwargs)
        except BaseException:
            self._budget.release()
            raise
        try:
            _configure_connection(conn)
            self._check_min_server_version(conn)
            conn._odoo_pool = _DIRECT_CONNECTION
        except BaseException:
            with contextlib.suppress(Exception):
                conn.close()
            self._budget.release()
            raise
        with self._lock:
            self._direct_out += 1
        self._checkouts.track(conn, _borrow_caller())
        self.stats.borrows_direct += 1
        return conn

    @staticmethod
    def _check_min_server_version(conn: psycopg.Connection) -> None:
        """Raise :class:`PoolError` when the server is below ``MIN_PG_VERSION``.

        ``server_version`` is client-side (no round-trip).  Shared by the
        pooled (:meth:`_validate_borrowed_conn`) and direct
        (:meth:`_borrow_direct`) borrow paths.
        """
        sv = conn.info.server_version
        if sv < MIN_PG_VERSION * 10000:
            raise PoolError(
                f"PostgreSQL {sv // 10000}.{sv % 10000} is below the "
                f"minimum required {MIN_PG_VERSION}.0. Please upgrade "
                f"to PostgreSQL {MIN_PG_VERSION} or later."
            )

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
        caller holds the ``_budget`` permit across the retry and the shared
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
                with self._lock:
                    if self._pools.get(key) is pool:
                        del self._pools[key]
                self._safe_close(pool)
                if attempt == 1:
                    _logger.info("Connection to the database failed: %s", e)
                    raise PoolError(str(e)) from e
                self._debug("Pool closed under borrow(); rebuilding for %s", dict(key))
                pool = self._get_or_create_pool(key, connection_info, deadline)
            except PoolTimeout as e:
                if pool.get_stats().get("pool_size", 0) == 0:
                    with self._lock:
                        if self._pools.get(key) is pool:
                            del self._pools[key]
                    self._safe_close(pool)
                self._forget_reachable(key)
                _logger.info("Connection to the database failed: %s", e)
                raise PoolError(str(e)) from e
            except psycopg.Error as e:
                self._forget_reachable(key)
                _logger.info("Connection to the database failed: %s", e)
                raise
            except Exception as e:
                raise PoolError(str(e)) from e
        raise PoolError("getconn retry budget exhausted")

    def _validate_borrowed_conn(
        self, conn: psycopg.Connection, pool: _PsycopgPool
    ) -> None:
        """Post-``getconn`` validation of a freshly borrowed *conn*.

        On ANY failure, return *conn* to its per-DSN pool (so the pool slot is
        not leaked) and re-raise; the caller's outer handler releases the
        ``_budget`` permit.  Like :meth:`_getconn_with_retry`, this never
        touches the semaphore.
        """
        try:
            self._check_min_server_version(conn)
            if _logger_conn.isEnabledFor(logging.DEBUG):
                self._debug("Borrow connection backend PID %d", conn.info.backend_pid)
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
        if _logger_conn.isEnabledFor(logging.DEBUG):
            if not connection.closed:
                self._debug("Give back connection to %r", connection.info.dsn)
            else:
                self._debug("Give back dead connection %r", connection)
        self._checkouts.release(connection)
        pool = connection.__dict__.pop("_odoo_pool", None)
        if pool is None:
            if not connection.closed:
                connection.close()
            return
        if pool is _DIRECT_CONNECTION:
            with contextlib.suppress(Exception):
                connection.close()
            with self._lock:
                self._direct_out -= 1
            self._budget.release()
            return

        note_activity(pool)
        try:
            if not keep_in_pool:
                self.stats.connections_discarded += 1
                with contextlib.suppress(Exception):
                    connection.close()

            try:
                pool.putconn(connection)
            except Exception:
                _logger.debug("Failed to return connection to pool", exc_info=True)
        finally:
            self._budget.release()
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

    def has_database(self, db_name: str) -> bool:
        """Whether any per-DSN pool for *db_name* currently exists.

        A read-only predicate: unlike :meth:`Connection.cursor`, whose borrow
        creates the per-DSN pool on demand, asking does not create one.  Lets a caller that must connect to a database purely
        to inspect it (``service.db.list_db_incompatible``) tell "this database
        was already being served" from "I opened this pool myself", and so close
        only the pools it created — instead of evicting a live one as a side
        effect of looking at it.

        Same database-component matching as :meth:`close_database`, so the two
        agree on what "a pool for this database" means.
        """
        with self._lock:
            return any(dict(k).get("database") == db_name for k in self._pools)

    def close_database(self, db_name: str) -> None:
        """Close every per-DSN pool connected to *db_name*.

        Matches on the database component alone (any host/user/URI form) — the
        semantics ``close_db()`` needs when a database is dropped or renamed.
        """
        with self._lock:
            keys = [k for k in self._pools if dict(k).get("database") == db_name]
            pools = [self._pools.pop(k) for k in keys]
            for k in [
                k for k in self._reachable_keys if dict(k).get("database") == db_name
            ]:
                self._forget_reachable(k)
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
            self._reachable_keys.clear()
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
        with self._lock:
            pools = list(self._pools.values())
        for pool in pools:
            if not pool.closed:
                self._safe_drain(pool)
        if pools:
            _logger.debug("%r: Drained %d pool(s)", self, len(pools))

    def get_stats(self) -> dict[str, dict]:
        """Return psycopg_pool stats keyed by database name.

        Kept for callers that only want the per-DSN view; :meth:`health` adds
        the pool-level counters and gauges those numbers cannot express.
        """
        with self._lock:
            snapshot = list(self._pools.items())
        stats = {}
        for key, pool in snapshot:
            db_name = dict(key).get("database", "unknown")
            stats[db_name] = pool.get_stats()
        return stats

    def health(self) -> dict:
        """Everything an operator needs to explain this pool's behaviour.

        ``get_stats()`` reports what each per-DSN psycopg_pool holds right now,
        which cannot answer the questions that actually come up: was a slow
        request waiting on a *connection*, is the shared budget approaching
        saturation, is the pre-flight probe still paying for itself, is the idle
        reaper churning pools for databases that are merely quiet.  Those are
        counters, and they live in :class:`~odoo.db.stats.PoolStats`.

        Shape: ``mode``/``databases`` identify the pool, ``pool`` carries the
        counters and gauges, ``per_database`` is :meth:`get_stats`.  Totals are
        monotonic, so a scraper differences them for rates.

        ``backends`` is the number of server connections this pool is actually
        holding, checked out *and* idle, summed across its per-DSN pools.  It is
        reported because it is the number PostgreSQL's ``max_connections`` is
        spent on, and it is NOT bounded by ``db_maxconn`` — the budget bounds
        concurrent checkouts, while each per-DSN pool independently retains up
        to that many idle connections for ``db_conn_max_idle``.  A process
        serving several databases therefore holds up to ``maxconn ×
        n_databases``, which nothing here caps and which no other counter
        exposed.
        """
        per_database = self.get_stats()
        with self._lock:
            n_pools = len(self._pools)
            direct_out = self._direct_out
        return {
            "mode": "read-only" if self._readonly else "read/write",
            "databases": n_pools,
            "backends": sum(s.get("pool_size", 0) for s in per_database.values())
            + direct_out,
            "pool": self.stats.snapshot(
                budget=self._budget,
                direct_out=direct_out,
                pools=n_pools,
                checkouts=self._checkouts,
            ),
            "per_database": per_database,
        }


class Connection:
    """A lightweight instance of a connection to postgres"""

    __slots__ = ("__dbname", "__dsn", "__key", "__pool")

    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
        self.__dbname = dbname
        self.__dsn = dict(dsn)
        self.__pool = pool
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

        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("create cursor to %r", self.dsn)
        return Cursor(self.__pool, self.__dbname, self.__dsn, key=self.__key)
