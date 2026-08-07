from __future__ import annotations

import threading


class ConnectionBudget:
    __slots__ = ("_sem", "exhausted", "maxconn")

    def __init__(self, maxconn: int):
        if maxconn <= 0:
            raise ValueError(f"ConnectionBudget maxconn must be >= 1, got {maxconn}")
        self.maxconn = maxconn
        self._sem = threading.BoundedSemaphore(maxconn)
        self.exhausted = 0

    def acquire(self, timeout: float) -> bool:
        if timeout == float("inf"):
            got = self._sem.acquire()
        else:
            got = self._sem.acquire(timeout=max(0.0, timeout))
        if not got:
            self.exhausted += 1
        return got

    def release(self) -> None:
        self._sem.release()

    @property
    def available(self) -> int:
        return self._sem._value

    @property
    def in_use(self) -> int:
        return self.maxconn - self._sem._value
