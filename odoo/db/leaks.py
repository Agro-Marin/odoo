from __future__ import annotations

import threading
from time import monotonic
from typing import NamedTuple


class Checkout(NamedTuple):
    since: float
    thread: str
    caller: str | None

    def age(self) -> float:
        return monotonic() - self.since

    def describe(self) -> str:
        where = f" at {self.caller}" if self.caller else ""
        return f"{self.age():.1f}s by {self.thread}{where}"


class CheckoutTracker:
    __slots__ = ("_last_report", "_out", "_report_lock")

    def __init__(self) -> None:
        self._out: dict[object, Checkout] = {}
        self._last_report = 0.0
        self._report_lock = threading.Lock()

    def track(self, conn: object, caller: str | None = None) -> None:
        self._out[conn] = Checkout(monotonic(), threading.current_thread().name, caller)

    def release(self, conn: object) -> float | None:
        entry = self._out.pop(conn, None)
        return None if entry is None else entry.age()

    def __len__(self) -> int:
        return len(self._out)

    def outstanding(self, older_than: float = 0.0) -> list[Checkout]:
        return sorted(
            (c for c in self._out.copy().values() if c.age() > older_than),
            key=lambda c: c.since,
        )

    def oldest_age(self) -> float:
        entries = self._out.copy().values()
        return max((c.age() for c in entries), default=0.0)

    def due_for_report(self, interval: float) -> bool:
        """Claim the reporting slot, or report that someone else has it.

        A throttle is a read-modify-write and this one had no lock. **No loss
        is observable on this interpreter and the fix does not pretend
        otherwise**: 16 threads released from a barrier onto the unguarded
        body still produced exactly one winner over five rounds, because the
        compare and the store are adjacent bytecodes with no call between them
        and CPython 3.14's GIL does not preempt there. The guard is taken on
        the terms the rest of this package states -- `PoolStats` owns its lock
        for the same reason -- and on a free-threaded build it is the
        difference between a throttle and none.

        It is a separate lock from nothing: `track` and `release` are single
        dict operations and stay lock-free. It is taken only when
        `db_leak_detection` is set, because `_warn_about_leaks` returns before
        reaching this otherwise.
        """
        now = monotonic()
        with self._report_lock:
            if now - self._last_report < interval:
                return False
            self._last_report = now
            return True

    def describe(self, limit: int = 3, older_than: float = 0.0) -> str:
        held = self.outstanding(older_than)
        if not held:
            return ""
        shown = "; ".join(c.describe() for c in held[:limit])
        more = f" (+{len(held) - limit} more)" if len(held) > limit else ""
        return f"oldest checkouts: {shown}{more}"
