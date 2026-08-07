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
    return float("inf") if deadline is None else deadline - monotonic()


def _libpq_connect_timeout(deadline: float | None, cap: int) -> int:
    if deadline is None:
        return cap
    remaining = int(deadline - monotonic())
    if remaining < 1:
        return 0
    return min(cap, remaining)


def _base_conn_options(conninfo: str, kwargs: dict) -> str:
    options = kwargs.get("options", "")
    if not options and conninfo:
        options = _expand_conninfo(conninfo).get("options", "")
    if not options:
        options = os.environ.get("PGOPTIONS", "")
    return options


_GUC_NAME_RE = re.compile(r"-c\s*([A-Za-z_][A-Za-z0-9_.]*)\s*=")


def _session_gucs(base_options: str) -> str:
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
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if f"{os.sep}odoo{os.sep}db{os.sep}" not in name:
            return f"{name}:{frame.f_lineno}"
        frame = frame.f_back
    return None


class PoolError(Exception):
    pass


class ConnectionPool:
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
        return key in self._reachable_keys

    def _mark_reachable(self, key: frozenset) -> None:
        self._reachable_keys.add(key)

    def _forget_reachable(self, key: frozenset) -> None:
        self._reachable_keys.discard(key)

    def _probe_connectable(
        self, conninfo: str, kwargs: dict, deadline: float | None = None
    ) -> None:
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
        try:
            pool.close()
        except Exception:
            _logger.debug("Failed to close pool during teardown", exc_info=True)

    @staticmethod
    def _safe_drain(pool: _PsycopgPool) -> None:
        try:
            pool.drain()
        except Exception:
            _logger.debug("Failed to drain pool", exc_info=True)

    def has_database(self, db_name: str) -> bool:
        with self._lock:
            return any(dict(k).get("database") == db_name for k in self._pools)

    def close_database(self, db_name: str) -> None:
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
        with self._lock:
            pools = list(self._pools.values())
        for pool in pools:
            if not pool.closed:
                self._safe_drain(pool)
        if pools:
            _logger.debug("%r: Drained %d pool(s)", self, len(pools))

    def get_stats(self) -> dict[str, dict]:
        with self._lock:
            snapshot = list(self._pools.items())
        stats = {}
        for key, pool in snapshot:
            db_name = dict(key).get("database", "unknown")
            stats[db_name] = pool.get_stats()
        return stats

    def health(self) -> dict:
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
    __slots__ = ("__dbname", "__dsn", "__key", "__pool")

    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
        self.__dbname = dbname
        self.__dsn = dict(dsn)
        self.__pool = pool
        self.__key = _normalize_dsn_key(dsn)

    @property
    def dsn(self) -> dict:
        dsn = _expand_conninfo(self.__dsn)
        dsn.pop("password", None)
        return dsn

    @property
    def dbname(self) -> str:
        return self.__dbname

    def cursor(self) -> Cursor:
        from .cursor import Cursor

        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("create cursor to %r", self.dsn)
        return Cursor(self.__pool, self.__dbname, self.__dsn, key=self.__key)
