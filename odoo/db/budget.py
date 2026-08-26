from __future__ import annotations

import threading
from time import monotonic


class ConnectionBudget:
    """The `db_maxconn` cap for one PostgreSQL server, as permits.

    Implemented on a `Condition` rather than a `BoundedSemaphore` so that
    `available`, `in_use` and `exhausted` are exact and are read under the same
    lock that hands the permits out. The semaphore version derived them from
    `threading.BoundedSemaphore._value` — a private CPython attribute, read
    without the semaphore's own lock, on the path that renders
    `db.pool_health()`. `BoundedSemaphore` is itself a `Condition` plus a
    counter, so this costs the same lock acquisition it always did.
    """

    __slots__ = ("_cond", "_exhausted", "_in_use", "maxconn")

    def __init__(self, maxconn: int):
        if maxconn <= 0:
            raise ValueError(f"ConnectionBudget maxconn must be >= 1, got {maxconn}")
        self.maxconn = maxconn
        self._cond = threading.Condition(threading.Lock())
        self._in_use = 0
        self._exhausted = 0

    def acquire(self, timeout: float) -> bool:
        endtime = None
        with self._cond:
            while self._in_use >= self.maxconn:
                if timeout == float("inf"):
                    self._cond.wait()
                    continue
                if endtime is None:
                    endtime = monotonic() + max(0.0, timeout)
                remaining = endtime - monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    if self._in_use < self.maxconn:
                        continue
                    self._exhausted += 1
                    return False
            self._in_use += 1
            return True

    def release(self) -> None:
        with self._cond:
            if self._in_use <= 0:
                raise ValueError("ConnectionBudget released more times than acquired")
            self._in_use -= 1
            self._cond.notify()

    @property
    def available(self) -> int:
        with self._cond:
            return self.maxconn - self._in_use

    @property
    def in_use(self) -> int:
        with self._cond:
            return self._in_use

    @property
    def exhausted(self) -> int:
        with self._cond:
            return self._exhausted
