from __future__ import annotations

import threading
from time import monotonic

LAG_SQL = """
    SELECT coalesce(
        CASE
            WHEN NOT pg_is_in_recovery() THEN 0
            WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0
            ELSE greatest(
                0, extract(epoch FROM now() - pg_last_xact_replay_timestamp())
            )
        END, 0)::float8
"""
"""Apply lag in seconds, or ``0`` when the server has nothing outstanding.

Zero for a primary too (``NOT pg_is_in_recovery()``): ``test_enable`` and
``dev_mode=replica`` point the read-only connection at the primary on purpose,
and that is a replica zero seconds behind itself, not an error.
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

    def allows(self) -> bool:
        return not (self.enabled and self._lagging)

    def due_for_sample(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            now = monotonic()
            if self._last_sample and now - self._last_sample < self.sample_interval:
                return False
            self._last_sample = now
            return True

    def record(self, lag_seconds: float | None) -> None:
        self.last_lag = 0.0 if lag_seconds is None else max(0.0, lag_seconds)
        self._lagging = self.enabled and self.last_lag > self.max_lag

    def snapshot(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_lag_seconds": self.max_lag,
            "last_lag_seconds": round(self.last_lag, 3),
            "lagging": self._lagging,
        }
