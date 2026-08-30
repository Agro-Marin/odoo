"""Is this DSN reachable, and if not, is that permanent?

Extracted from `ConnectionPool`, which is about borrowing. Every other
cross-cutting concern in this package already has a module of its own --
`budget`, `breaker`, `lag`, `leaks`, `reaper`, `stats`, `schema_cache`,
`lifecycle`, `dsn` -- and this was the one still inlined: private state, a
lifecycle, a policy, a helper class and its own stats vocabulary
(`probe_permanent` / `probe_transient` / `probe_skipped_proven`), spread through
the 764-line class that borrows connections.

The concern is narrow and worth stating on its own. Before opening a pool to an
unseen DSN, find out whether connecting is going to fail *permanently* -- a
missing database, a rejected password -- because psycopg's pool retries a
failing connect in the background and turns a typo into a `PoolTimeout` after
the full borrow budget. Once a DSN has served a connection it is proven, and the
probe is skipped for the life of that proof.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from time import monotonic

import psycopg

from .dsn import (
    _NON_RETRYABLE_CONNECT_ERRORS,
    _expand_conninfo,
    _translate_connect_error,
)

_logger = logging.getLogger(__name__)

PROBE_CONNECT_TIMEOUT = 5


def libpq_connect_timeout(deadline: float | None, cap: int) -> int:
    if deadline is None:
        return cap
    remaining = int(deadline - monotonic())
    if remaining < 1:
        return 0
    return min(cap, remaining)


class _InFlightProbe:
    __slots__ = ("done", "exc")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.exc: BaseException | None = None


class ReachabilityProbe:
    """Proof-of-reachability per DSN key, plus the pre-flight probe itself.

    Holds its own lock. It never calls back into the pool, so a caller may hold
    the pool lock across these methods: the ordering pool -> probe is the only
    one that exists.
    """

    # No `__slots__`, unlike its sibling helpers. Those are sized for many
    # instances; there is exactly one of these per `ConnectionPool`, so slots
    # buy nothing here and cost a seam: `test_probe.py` substitutes
    # `probe_connectable` on the instance to count probes without opening a
    # socket, and a slotted class refuses the assignment.
    def __init__(self, stats) -> None:
        self._lock = threading.Lock()
        self._proven: set[frozenset] = set()
        self._inflight: dict[frozenset, _InFlightProbe] = {}
        self._stats = stats

    # -- the proof ---------------------------------------------------------
    def is_proven(self, key: frozenset) -> bool:
        with self._lock:
            return key in self._proven

    def mark_proven(self, key: frozenset) -> None:
        with self._lock:
            self._proven.add(key)

    def forget(self, key: frozenset) -> None:
        with self._lock:
            self._proven.discard(key)

    def forget_each(self, keys) -> None:
        with self._lock:
            self._proven.difference_update(keys)

    def forget_all(self) -> None:
        with self._lock:
            self._proven.clear()

    def forget_matching(self, predicate) -> None:
        """Revoke every proof the predicate selects, in one critical section.

        Not a read of the set then a write: the caller holds the pool lock
        across this, but `mark_proven` is reached from `borrow` without it, so a
        read-then-write pair lets a concurrent borrow re-prove a key that
        `close_database` is in the middle of revoking. Under one acquisition it
        cannot.
        """
        with self._lock:
            self._proven.difference_update(
                [key for key in self._proven if predicate(key)]
            )

    # -- the probe ---------------------------------------------------------
    def ensure_connectable(
        self,
        key: frozenset,
        conninfo: str,
        kwargs: dict,
        deadline: float | None = None,
    ) -> None:
        """Probe unless already proven; dedup concurrent probes of one key.

        The proof and the in-flight registration are read under ONE
        acquisition. Two (`is_proven` then `_probe_deduped`) also left a window
        in which a key proven between them started a second probe -- harmless,
        but it is a full extra connect on the path whose whole purpose is to
        avoid one.
        """
        with self._lock:
            if key in self._proven:
                proven = True
                probe = None
                leader = False
            else:
                proven = False
                probe = self._inflight.get(key)
                leader = probe is None
                if leader:
                    probe = self._inflight[key] = _InFlightProbe()
        if proven:
            self._stats.record_probe_outcome("skipped_proven")
            return
        assert probe is not None
        self._run_or_follow(key, probe, leader, conninfo, kwargs, deadline)

    def _run_or_follow(
        self,
        key: frozenset,
        probe: _InFlightProbe,
        leader: bool,
        conninfo: str,
        kwargs: dict,
        deadline: float | None = None,
    ) -> None:
        if leader:
            try:
                self.probe_connectable(conninfo, kwargs, deadline)
            except BaseException as e:
                probe.exc = e
                raise
            finally:
                with self._lock:
                    del self._inflight[key]
                probe.done.set()
        else:
            wait_timeout = (
                None if deadline is None else max(0.0, deadline - monotonic())
            )
            if probe.done.wait(wait_timeout) and probe.exc is not None:
                # `.with_traceback(None)` because every follower raises the one
                # object the leader recorded, and a `raise` APPENDS to that
                # object's traceback. Measured with eight followers on a dead
                # DSN -- the case this dedup exists for -- the shared exception
                # reached 19 frames, the same two frames repeated, interleaved
                # across threads that have nothing to do with each other, and
                # each frame keeping its thread's locals alive for as long as
                # the exception did. Clearing first bounds it at one raise.
                # psycopg does the same thing for the same reason
                # (`raise ex.with_traceback(None)` in `Cursor.copy`).
                raise probe.exc.with_traceback(None)

    def probe_connectable(
        self, conninfo: str, kwargs: dict, deadline: float | None = None
    ) -> None:
        probe_timeout = libpq_connect_timeout(deadline, PROBE_CONNECT_TIMEOUT)
        if not probe_timeout:
            return
        self._stats.record_probe_started()
        probe_kwargs = {**kwargs, "autocommit": True}
        probe_kwargs["connect_timeout"] = probe_timeout
        try:
            # Only the CONNECT is classified. `psycopg.connect(...).close()`
            # put the teardown inside the same `try`, so a connection that
            # opened -- proving the DSN reachable, which is the entire
            # question -- was filed as a transient probe failure if its close
            # raised, and the pool paid the full borrow budget behind it.
            conn = psycopg.connect(conninfo, **probe_kwargs)
        except _NON_RETRYABLE_CONNECT_ERRORS:
            self._stats.record_probe_outcome("permanent")
            raise
        except psycopg.OperationalError as e:
            translated = _translate_connect_error(e)
            if translated is not None:
                self._stats.record_probe_outcome("permanent")
                raise translated from e
            if self.database_absent(conninfo, kwargs, deadline):
                self._stats.record_probe_outcome("permanent")
                raise psycopg.errors.InvalidCatalogName(str(e)) from e
            self._stats.record_probe_outcome("transient")
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )
        except Exception:
            self._stats.record_probe_outcome("transient")
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )
        else:
            with contextlib.suppress(Exception):
                conn.close()

    def database_absent(
        self, conninfo: str, kwargs: dict, deadline: float | None = None
    ) -> bool:
        """Ask `postgres` whether the database exists.

        The locale-independent half of the permanent/transient decision:
        `dsn._translate_connect_error` only recognises English messages, so this
        is what catches a missing database under any `lc_messages`.
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
        probe_timeout = libpq_connect_timeout(deadline, PROBE_CONNECT_TIMEOUT)
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
