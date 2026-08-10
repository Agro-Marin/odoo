import sys
import threading

import pytest

from odoo.db.budget import ConnectionBudget
from odoo.db.leaks import CheckoutTracker
from odoo.db.stats import PoolStats

THREADS = 8
ITERATIONS = 5_000
EXPECTED = THREADS * ITERATIONS


def _hammer(fn, threads: int = THREADS, iterations: int = ITERATIONS) -> None:
    barrier = threading.Barrier(threads)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            for _ in range(iterations):
                fn()
        except BaseException as exc:
            errors.append(exc)

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        workers = [threading.Thread(target=worker) for _ in range(threads)]
        for t in workers:
            t.start()
        for t in workers:
            t.join()
    finally:
        sys.setswitchinterval(old)
    assert not errors, f"worker raised: {errors[0]!r}"


def test_pool_stats_borrow_count_is_not_lost_under_concurrency():
    stats = PoolStats()
    _hammer(lambda: stats.record_borrow(0.0))
    assert stats.borrows == EXPECTED, (
        f"lost {EXPECTED - stats.borrows} of {EXPECTED} increments to "
        f"PoolStats.borrows. `borrows += 1` is a non-atomic read-modify-write; "
        f"give PoolStats a lock (or use itertools.count) — the pool's "
        f"exhaustion diagnostics are now under-reporting."
    )


def test_pool_stats_histogram_agrees_with_the_total():
    stats = PoolStats()
    _hammer(lambda: stats.record_borrow(0.0))
    assert sum(stats.borrow_wait_buckets) == stats.borrows, (
        f"histogram sums to {sum(stats.borrow_wait_buckets)} but borrows is "
        f"{stats.borrows}: the counter and its buckets are separate "
        f"read-modify-writes and have drifted apart."
    )


def test_connection_budget_exhausted_count_is_not_lost():
    budget = ConnectionBudget(1)
    assert budget.acquire(0.0) is True
    _hammer(lambda: budget.acquire(0.0))
    assert budget.exhausted == EXPECTED, (
        f"lost {EXPECTED - budget.exhausted} of {EXPECTED} increments to "
        f"ConnectionBudget.exhausted — the metric that says 'the pool ran out'."
    )


def test_budget_in_use_tracks_acquire_release_exactly():
    budget = ConnectionBudget(THREADS)
    gate = threading.Barrier(THREADS + 1)

    def hold() -> None:
        assert budget.acquire(5.0)
        gate.wait()
        gate.wait()
        budget.release()

    holders = [threading.Thread(target=hold) for _ in range(THREADS)]
    for t in holders:
        t.start()
    gate.wait()
    try:
        assert budget.in_use == THREADS
        assert budget.available == 0
    finally:
        gate.wait()
        for t in holders:
            t.join()
    assert budget.in_use == 0
    assert budget.available == THREADS


def test_checkout_tracker_length_matches_tracked_connections():
    tracker = CheckoutTracker()
    conns = [object() for _ in range(THREADS * 50)]
    chunks = [conns[i::THREADS] for i in range(THREADS)]
    barrier = threading.Barrier(THREADS)

    def worker(mine: list) -> None:
        barrier.wait()
        for conn in mine:
            tracker.track(conn)

    threads = [threading.Thread(target=worker, args=(c,)) for c in chunks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tracker) == len(conns)
    for conn in conns:
        assert tracker.release(conn) is not None
    assert len(tracker) == 0


def test_pool_lock_covers_every_stats_mutation_or_none():
    import pathlib
    import re

    pool_py = pathlib.Path(__file__).resolve().parents[1] / "pool.py"
    lines = pool_py.read_text(encoding="utf-8").splitlines()

    def indent(s: str) -> int:
        return len(s) - len(s.lstrip())

    locked: list[int] = []
    unlocked: list[int] = []
    for i, line in enumerate(lines):
        if not re.search(r"self\.stats\.\w+ \+= 1", line):
            continue
        under_lock = False
        for j in range(i - 1, max(i - 40, -1), -1):
            prev = lines[j]
            if not prev.strip():
                continue
            if indent(prev) < indent(line):
                if "with self._lock" in prev:
                    under_lock = True
                    break
                if re.match(r"\s*(def |class )", prev):
                    break
        (locked if under_lock else unlocked).append(i + 1)

    assert locked or unlocked, "no stats mutations found in pool.py — scan broke"

    assert (len(locked), len(unlocked)) == (2, 13), (
        f"the PoolStats locking split moved: {len(locked)} locked "
        f"(lines {locked}), {len(unlocked)} unlocked (lines {unlocked}); "
        f"expected (2, 13).\n"
        f"If you locked more of them: good — update this pin, and prefer "
        f"finishing the job so `unlocked` reaches 0.\n"
        f"If you added a new unlocked increment: that is one more counter that "
        f"silently under-reports under the concurrency it exists to diagnose."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
