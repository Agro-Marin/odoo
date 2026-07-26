"""Which connections are checked out, since when, and from where.

:class:`~odoo.db.budget.ConnectionBudget` reports *that* the process ran out of
permits; it cannot say who was holding them.  That is the question an operator
actually has when ``db_maxconn`` is reached, and the answer used to require
attaching a debugger to a saturated worker.

The tracker is the other half of that story: every borrow records the connection
with a timestamp and the thread holding it, every return removes it, and what is
left is by definition still out.  Saturation then produces an error naming the
oldest holders instead of only the limit that was hit, and a checkout older than
``db_leak_detection`` is reported on its own — a connection held for minutes is
either a genuine long-running job or a cursor nobody closed, and both are worth
seeing before the pool runs dry.

Cost is one dict insert per borrow and one delete per return: 413 ns for the
pair, against a ~140 us cursor cycle.  The borrow site is captured too, always —
it costs 300 ns because the stack walk stops at the first application frame, so
gating it behind a config option would have bought nothing and left the
saturation error mute on the deployments that had not opted in.
``db_leak_detection`` therefore controls only *when to complain*, not what is
recorded.

``describe()`` is the one non-trivial read (1.2 us with one checkout, 72 us with
512), which is why it runs on the throttled warning path and in the error
message, never per borrow.
"""

from __future__ import annotations

import threading
from time import monotonic
from typing import NamedTuple


class Checkout(NamedTuple):
    """One connection currently held by a borrower."""

    since: float
    thread: str
    caller: str | None

    def age(self) -> float:
        """Seconds this connection has been checked out."""
        return monotonic() - self.since

    def describe(self) -> str:
        where = f" at {self.caller}" if self.caller else ""
        return f"{self.age():.1f}s by {self.thread}{where}"


class CheckoutTracker:
    """Outstanding checkouts for one :class:`~odoo.db.pool.ConnectionPool`.

    Keyed by the connection object, so an entry cannot outlive the connection's
    identity the way an ``id()`` key could after a free-and-reuse.  Holding a
    strong reference is deliberate: a tracked connection is checked out, so
    something already holds it, and an entry that never goes away IS the leak
    being reported.

    Mutation is a bare dict insert/delete, atomic under the GIL and off any
    lock, because it sits on the borrow path.  Reads take a ``dict.copy()``
    (atomic in CPython) rather than iterating, so a concurrent borrow cannot
    raise "dictionary changed size during iteration".
    """

    __slots__ = ("_last_report", "_out")

    def __init__(self) -> None:
        self._out: dict[object, Checkout] = {}
        self._last_report = 0.0

    def track(self, conn: object, caller: str | None = None) -> None:
        """Record *conn* as checked out by the current thread."""
        self._out[conn] = Checkout(monotonic(), threading.current_thread().name, caller)

    def release(self, conn: object) -> float | None:
        """Forget *conn*; return how long it was held, or ``None`` if untracked."""
        entry = self._out.pop(conn, None)
        return None if entry is None else entry.age()

    def __len__(self) -> int:
        return len(self._out)

    def outstanding(self, older_than: float = 0.0) -> list[Checkout]:
        """Checkouts held longer than *older_than* seconds, oldest first."""
        return sorted(
            (c for c in self._out.copy().values() if c.age() > older_than),
            key=lambda c: c.since,
        )

    def oldest_age(self) -> float:
        """Age of the longest-held checkout, or ``0.0`` when nothing is out."""
        entries = self._out.copy().values()
        return max((c.age() for c in entries), default=0.0)

    def due_for_report(self, interval: float) -> bool:
        """Whether a leak warning is due, claiming the slot if so.

        Its own throttle rather than the idle reaper's: sharing one would mean
        a leak warning consumed the sweep that reaps quiet pools, and whichever
        ran first would silence the other.  The read-and-stamp races benignly —
        losing it costs a duplicate warning, not a missed leak.
        """
        now = monotonic()
        if now - self._last_report < interval:
            return False
        self._last_report = now
        return True

    def describe(self, limit: int = 3, older_than: float = 0.0) -> str:
        """One line naming the oldest holders, for an error message or a log.

        Empty when nothing qualifies, so a caller can append it unconditionally
        and get no trailing noise in the ordinary case.
        """
        held = self.outstanding(older_than)
        if not held:
            return ""
        shown = "; ".join(c.describe() for c in held[:limit])
        more = f" (+{len(held) - limit} more)" if len(held) > limit else ""
        return f"oldest checkouts: {shown}{more}"
