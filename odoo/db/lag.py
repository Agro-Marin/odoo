from __future__ import annotations

import threading
from time import monotonic

LAG_SQL = """
    SELECT coalesce(
        CASE
            WHEN NOT pg_is_in_recovery() THEN 0
            WHEN pg_last_wal_receive_lsn() IS NULL THEN 0
            WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0
            ELSE greatest(
                0, extract(epoch FROM now() - pg_last_xact_replay_timestamp())
            )
        END, 0)::float8
"""
"""Apply lag in seconds, and zero wherever the question cannot be answered.

The caught-up check exists because `pg_last_xact_replay_timestamp()` grows
without bound on an idle primary, so the replay timestamp is only consulted
when WAL is genuinely outstanding.

The NULL branch is the same argument reached through a different door, and it
was verified against a real standby rather than reasoned about.
`pg_last_wal_receive_lsn()` is NULL when no walreceiver has ever run -- a
standby recovering from archive alone -- and `NULL = anything` is NULL rather
than false, so without this clause the CASE does not take the caught-up branch:
it falls through to the ELSE and reports the idle primary's elapsed time as
lag. Measured on a PG 18 standby built with `pg_basebackup` and started with no
`primary_conninfo`, `pg_is_in_recovery()` true and `pg_last_wal_receive_lsn()`
NULL: the previous query answered **55.1 s** and this one answers **0**, and
the 55.1 would have gone on growing. A streaming standby with genuinely
outstanding WAL is untouched -- both queries answered 0.20 and 0.23 there,
which is the interval between the two calls.

Zero is the right answer for the same reason a failed measurement is recorded
as healthy: demoting on a question the server could not answer is demoting on
no evidence.
"""


class ReplicaLagGate:
    __slots__ = (
        "_lagging",
        "_last_sample",
        "_lock",
        "last_lag",
        "max_lag",
        "sample_interval",
    )

    def __init__(self, max_lag: float, sample_interval: float | None = None):
        if max_lag < 0:
            raise ValueError(f"max_lag must be >= 0, got {max_lag}")
        self.max_lag = max_lag
        self.sample_interval = (
            sample_interval if sample_interval is not None else max(1.0, max_lag / 4)
        )
        self._lock = threading.Lock()
        self._last_sample = 0.0
        self._lagging = False
        self.last_lag = 0.0

    @property
    def enabled(self) -> bool:
        return self.max_lag > 0

    def is_replica_usable(self) -> bool:
        return not (self.enabled and self._lagging)

    def acquire_sample_interval(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            now = monotonic()
            if self._last_sample and now - self._last_sample < self.sample_interval:
                return False
            self._last_sample = now
            return True

    def record(self, lag_seconds: float | None) -> None:
        lag = 0.0 if lag_seconds is None else max(0.0, lag_seconds)
        with self._lock:
            self.last_lag = lag
            self._lagging = self.enabled and lag > self.max_lag

    def get_snapshot(self) -> dict:
        with self._lock:
            last_lag, lagging = self.last_lag, self._lagging
        return {
            "enabled": self.enabled,
            "max_lag_seconds": self.max_lag,
            "last_lag_seconds": round(last_lag, 3),
            "lagging": lagging,
        }
