from __future__ import annotations

from time import monotonic

_WAIT_BUCKETS: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 5.0, 30.0)


class PoolStats:
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
