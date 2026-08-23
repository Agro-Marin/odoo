from __future__ import annotations

import threading
from time import monotonic

_WAIT_BUCKETS: tuple[float, ...] = (0.001, 0.01, 0.1, 1.0, 5.0, 30.0)

_PROBE_OUTCOMES: dict[str, str] = {
    "permanent": "probe_permanent",
    "transient": "probe_transient",
    "skipped_proven": "probe_skipped_proven",
}


class PoolStats:
    """Counters behind `ConnectionPool.health()`, and the lock that makes them true.

    Every field is mutated only through the methods below, each of which holds
    `_lock` for the whole update. `x += 1` on an attribute is a non-atomic
    read-modify-write, so the counters that exist to diagnose concurrency were
    the ones losing increments under it — and the histogram could drift out of
    step with the total it summarises, because they were separate writes.

    The cost is one uncontended lock acquisition per borrow, against a ~140 us
    cursor cycle.
    """

    __slots__ = (
        "_lock",
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
        self._lock = threading.Lock()
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
        bucket = len(_WAIT_BUCKETS)
        for i, edge in enumerate(_WAIT_BUCKETS):
            if waited <= edge:
                bucket = i
                break
        with self._lock:
            self.borrows += 1
            self.borrow_wait_total += waited
            self.borrow_wait_max = max(self.borrow_wait_max, waited)
            self.borrow_wait_buckets[bucket] += 1

    def record_borrow_failed(self) -> None:
        with self._lock:
            self.borrows_failed += 1

    def record_direct_borrow(self) -> None:
        with self._lock:
            self.borrows_direct += 1

    def record_probe_started(self) -> None:
        with self._lock:
            self.probe_run += 1

    def record_probe_outcome(self, outcome: str) -> None:
        field = _PROBE_OUTCOMES[outcome]
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    def record_pool_created(self) -> None:
        with self._lock:
            self.pools_created += 1

    def record_pools_reaped(self, count: int) -> None:
        with self._lock:
            self.pools_reaped += count

    def record_pools_evicted_stale(self, count: int) -> None:
        with self._lock:
            self.pools_evicted_stale += count

    def record_connection_discarded(self) -> None:
        with self._lock:
            self.connections_discarded += 1

    def record_leak_report(self) -> None:
        with self._lock:
            self.leaks_reported += 1

    def snapshot(
        self, *, budget=None, direct_out: int = 0, pools: int = 0, checkouts=None
    ) -> dict:
        with self._lock:
            buckets = list(self.borrow_wait_buckets)
            totals = (
                self.borrows,
                self.borrows_direct,
                self.borrows_failed,
                self.borrow_wait_total,
                self.borrow_wait_max,
                self.pools_created,
                self.pools_reaped,
                self.pools_evicted_stale,
                self.connections_discarded,
                self.leaks_reported,
                self.probe_run,
                self.probe_permanent,
                self.probe_transient,
                self.probe_skipped_proven,
            )
        (
            borrows,
            borrows_direct,
            borrows_failed,
            wait_total,
            wait_max,
            pools_created,
            pools_reaped,
            pools_evicted_stale,
            connections_discarded,
            leaks_reported,
            probe_run,
            probe_permanent,
            probe_transient,
            probe_skipped_proven,
        ) = totals
        waits = {}
        running = 0
        for edge, count in zip(_WAIT_BUCKETS, buckets, strict=False):
            running += count
            waits[f"le_{edge}"] = running
        waits["le_+Inf"] = running + buckets[-1]
        out = {
            "borrows": borrows,
            "borrows_direct": borrows_direct,
            "borrows_failed": borrows_failed,
            "borrow_wait_seconds_total": round(wait_total, 6),
            "borrow_wait_seconds_max": round(wait_max, 6),
            "borrow_wait_seconds": waits,
            "pools_created": pools_created,
            "pools_reaped": pools_reaped,
            "pools_evicted_stale": pools_evicted_stale,
            "connections_discarded": connections_discarded,
            "leaks_reported": leaks_reported,
            "probe_run": probe_run,
            "probe_permanent": probe_permanent,
            "probe_transient": probe_transient,
            "probe_skipped_proven": probe_skipped_proven,
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
