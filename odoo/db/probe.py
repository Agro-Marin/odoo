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
    def __init__(self, stats) -> None:
        self._lock = threading.Lock()
        self._proven: set[frozenset] = set()
        self._inflight: dict[frozenset, _InFlightProbe] = {}
        self._stats = stats

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
        with self._lock:
            self._proven.difference_update(
                [key for key in self._proven if predicate(key)]
            )

    def ensure_connectable(
        self,
        key: frozenset,
        conninfo: str,
        kwargs: dict,
        deadline: float | None = None,
    ) -> None:
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
