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
    __slots__ = ("_last_report", "_out")

    def __init__(self) -> None:
        self._out: dict[object, Checkout] = {}
        self._last_report = 0.0

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
        now = monotonic()
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
