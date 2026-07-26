"""Operational counters for :class:`~odoo.db.pool.ConnectionPool`.

Distinct from :mod:`odoo.db.metrics`, which counts *SQL* per cursor
(``sql_counter``, per-table timings, ``assertQueryCount``).  This module counts
what the *pool* did: how long borrows waited, how often the budget was
exhausted, what the pre-flight probe concluded, how many per-DSN pools were
created, reaped or evicted.

Why this exists.  The pool makes two deliberate trades that are only defensible
if they are visible.  One shared :class:`~odoo.db.budget.ConnectionBudget` can
starve itself where two could not, accepted because saturation degrades to a
legible ``PoolError`` — but a ``PoolError`` is the moment it already hurt, and
there was no way to watch the budget approach exhaustion.  The pre-flight probe
buys a fast permanent-failure at the cost of a connect, memoized per DSN — with
no way to tell whether the memo was paying off.  Both are now countable.

Cost on the borrow path is one ``monotonic()`` and a handful of integer
increments: :meth:`PoolStats.record_borrow` measures 230 ns, against a cursor
open/query/commit/close cycle of ~140 us over a unix socket.  An A/B of the
whole cycle cannot resolve it — the two medians overlap — which is the useful
way to state the cost.

Counters are plain ints mutated without a lock: CPython only runs the eval
breaker at specific bytecodes, so ``+=`` on an attribute does not lose updates
under the GIL (verified: 8 threads x 60k increments at a 1 us switch interval
lost none).  On a free-threaded build they become approximate, which is the
right trade for diagnostics on a hot path.
"""

from __future__ import annotations

from time import monotonic

_WAIT_BUCKETS: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 5.0, 30.0)


class PoolStats:
    """Counters for one :class:`~odoo.db.pool.ConnectionPool` instance.

    Monotonic totals, never reset, so a scraper computes rates by differencing —
    the convention every metrics backend expects.  :meth:`snapshot` renders them
    alongside the live gauges the pool can only report at read time.
    """

    __slots__ = (
        "borrow_wait_buckets",
        "borrow_wait_max",
        "borrow_wait_total",
        "borrows",
        "borrows_direct",
        "borrows_failed",
        "connections_discarded",
        "leaks_reported",
        "pools_created",
        "pools_evicted_stale",
        "pools_reaped",
        "probe_permanent",
        "probe_run",
        "probe_skipped_proven",
        "probe_transient",
    )

    def __init__(self) -> None:
        self.borrows = 0
        self.borrows_direct = 0
        self.borrows_failed = 0
        self.borrow_wait_total = 0.0
        self.borrow_wait_max = 0.0
        self.borrow_wait_buckets = [0] * (len(_WAIT_BUCKETS) + 1)
        self.pools_created = 0
        self.pools_reaped = 0
        self.pools_evicted_stale = 0
        self.connections_discarded = 0
        self.leaks_reported = 0
        self.probe_run = 0
        self.probe_permanent = 0
        self.probe_transient = 0
        self.probe_skipped_proven = 0

    def record_borrow(self, started_at: float) -> None:
        """Account one successful borrow that began at *started_at*."""
        waited = monotonic() - started_at
        self.borrows += 1
        self.borrow_wait_total += waited
        self.borrow_wait_max = max(self.borrow_wait_max, waited)
        for i, edge in enumerate(_WAIT_BUCKETS):
            if waited <= edge:
                self.borrow_wait_buckets[i] += 1
                return
        self.borrow_wait_buckets[-1] += 1

    def snapshot(
        self, *, budget=None, direct_out: int = 0, pools: int = 0, checkouts=None
    ) -> dict:
        """Render the counters, plus the live gauges only the pool knows.

        Bucket keys are cumulative upper bounds in seconds (``le``), the shape a
        histogram scraper expects; ``+Inf`` collects everything slower than the
        last edge.
        """
        waits = {}
        running = 0
        for edge, count in zip(_WAIT_BUCKETS, self.borrow_wait_buckets, strict=False):
            running += count
            waits[f"le_{edge}"] = running
        waits["le_+Inf"] = running + self.borrow_wait_buckets[-1]
        out = {
            "borrows": self.borrows,
            "borrows_direct": self.borrows_direct,
            "borrows_failed": self.borrows_failed,
            "borrow_wait_seconds_total": round(self.borrow_wait_total, 6),
            "borrow_wait_seconds_max": round(self.borrow_wait_max, 6),
            "borrow_wait_seconds": waits,
            "pools_created": self.pools_created,
            "pools_reaped": self.pools_reaped,
            "pools_evicted_stale": self.pools_evicted_stale,
            "connections_discarded": self.connections_discarded,
            "leaks_reported": self.leaks_reported,
            "probe_run": self.probe_run,
            "probe_permanent": self.probe_permanent,
            "probe_transient": self.probe_transient,
            "probe_skipped_proven": self.probe_skipped_proven,
            "direct_out": direct_out,
            "pools": pools,
        }
        if checkouts is not None:
            out["checked_out"] = len(checkouts)
            out["checked_out_oldest_seconds"] = round(checkouts.oldest_age(), 3)
        if budget is not None:
            out["budget_maxconn"] = budget.maxconn
            out["budget_available"] = budget.available
            out["budget_in_use"] = budget.in_use
            out["budget_exhausted"] = budget.exhausted
        return out
