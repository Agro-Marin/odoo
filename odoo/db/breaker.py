from __future__ import annotations

import threading
from time import monotonic

_INITIAL_COOLDOWN = 1.0

_PROBE_ABANDON_AFTER = 60.0


class CircuitBreaker:
    __slots__ = (
        "_cooldown",
        "_lock",
        "_open",
        "_opened_at",
        "_probing_since",
        "failures",
        "initial_cooldown",
        "max_cooldown",
        "trips",
    )

    def __init__(
        self, max_cooldown: float, initial_cooldown: float = _INITIAL_COOLDOWN
    ):
        if max_cooldown < initial_cooldown:
            raise ValueError(
                f"max_cooldown ({max_cooldown}) must be >= "
                f"initial_cooldown ({initial_cooldown})"
            )
        self.initial_cooldown = initial_cooldown
        self.max_cooldown = max_cooldown
        self._lock = threading.Lock()
        self._open = False
        self._cooldown = 0.0
        self._opened_at = 0.0
        self._probing_since = 0.0
        self.failures = 0
        self.trips = 0

    @property
    def closed(self) -> bool:
        return not self._open

    @property
    def cooldown_remaining(self) -> float:
        if self.closed:
            return 0.0
        return max(0.0, self._opened_at + self._cooldown - monotonic())

    def allow(self) -> bool:
        with self._lock:
            if self.closed:
                return True
            now = monotonic()
            if now - self._opened_at < self._cooldown:
                return False
            if self._probing_since and now - self._probing_since < _PROBE_ABANDON_AFTER:
                return False
            self._probing_since = now
            return True

    def record_success(self) -> None:
        with self._lock:
            self._open = False
            self._cooldown = 0.0
            self._opened_at = 0.0
            self._probing_since = 0.0
            self.failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if not self._open:
                self._open = True
                self._cooldown = self.initial_cooldown
                self._opened_at = monotonic()
                self._probing_since = 0.0
                self.trips += 1
                return
            if self._probing_since:
                self._cooldown = min(self._cooldown * 2, self.max_cooldown)
                self._opened_at = monotonic()
                self._probing_since = 0.0

    def snapshot(self) -> dict:
        return {
            "closed": self.closed,
            "failures": self.failures,
            "trips": self.trips,
            "cooldown_seconds": round(self._cooldown, 3),
            "cooldown_remaining_seconds": round(self.cooldown_remaining, 3),
        }
