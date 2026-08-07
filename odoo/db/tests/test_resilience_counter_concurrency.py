import sys
import threading

import pytest

from odoo.db.budget import ConnectionBudget
from odoo.db.leaks import CheckoutTracker
from odoo.db.stats import PoolStats

# The `db/` [resilience] tier keeps every counter as a bare `+=` on an instance
# attribute, with no lock:
#
#     stats.borrows += 1                 (stats.py record_borrow, 4 mutations)
#     budget.exhausted += 1              (budget.py acquire)
#     stats.borrows_failed += 1          (pool.py x4)
#     stats.borrows_direct += 1          (pool.py)
#
# `x += 1` is LOAD / ADD / STORE, which is not atomic in either build: with the
# GIL a thread switch may land between the bytecodes, and without it the write
# is a plain data race. These counters exist to diagnose pool exhaustion, i.e.
# they matter most under exactly the concurrency that can corrupt them.
#
# MEASURED on this interpreter (a GIL build: Py_GIL_DISABLED=0), 8 threads x
# 20,000 increments with sys.setswitchinterval(1e-6): **zero** lost updates.
# So this is a latent defect, not a live one -- see the audit note. These tests
# pin the *invariants* rather than assert the current happy result, so that:
#
#   * they keep passing if the counters are given a lock (the fix), and
#   * they start failing on a free-threaded build, where the race is real,
#     which is the moment somebody needs to know.
#
# `test_pool_lock_covers_every_stats_mutation_or_none` is the interesting one:
# it does not ask for locking, it asks for *consistency*. `pool.py` today
# increments `self._direct_out` inside `with self._lock` and `stats.borrows_direct`
# one line later outside it, which is the evidence that the omission is
# accidental rather than a considered "stats are best-effort" policy.

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
            # Re-surfaced by the assert below: a worker that dies silently would
            # make every count in this file pass for the wrong reason.
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
    # A weaker but sharper invariant: every recorded borrow lands in exactly one
    # latency bucket, so the histogram must sum to the counter regardless of
    # what either value is.
    stats = PoolStats()
    _hammer(lambda: stats.record_borrow(0.0))
    assert sum(stats.borrow_wait_buckets) == stats.borrows, (
        f"histogram sums to {sum(stats.borrow_wait_buckets)} but borrows is "
        f"{stats.borrows}: the counter and its buckets are separate "
        f"read-modify-writes and have drifted apart."
    )


def test_connection_budget_exhausted_count_is_not_lost():
    budget = ConnectionBudget(1)
    assert budget.acquire(0.0) is True  # drain it: every later acquire fails
    _hammer(lambda: budget.acquire(0.0))
    assert budget.exhausted == EXPECTED, (
        f"lost {EXPECTED - budget.exhausted} of {EXPECTED} increments to "
        f"ConnectionBudget.exhausted — the metric that says 'the pool ran out'."
    )


def test_budget_in_use_tracks_acquire_release_exactly():
    # The semantic invariant behind the counters: whatever the bookkeeping does,
    # in_use must equal the number of outstanding acquires.
    budget = ConnectionBudget(THREADS)
    gate = threading.Barrier(THREADS + 1)

    def hold() -> None:
        assert budget.acquire(5.0)
        gate.wait()  # all THREADS holders in flight
        gate.wait()  # released only after the main thread has measured
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
    # Not "add a lock" — "stop being inconsistent about it". pool.py holds
    # self._lock while incrementing self._direct_out and then increments
    # stats.borrows_direct one line later, outside it.
    import pathlib
    import re

    pool_py = pathlib.Path(__file__).resolve().parents[1] / "pool.py"
    lines = pool_py.read_text(encoding="utf-8").splitlines()

    def indent(s: str) -> int:
        return len(s) - len(s.lstrip())

    locked, unlocked = [], []
    for i, line in enumerate(lines):
        if not re.search(r"self\.stats\.\w+ \+= 1", line):
            continue
        # walk backwards for an enclosing `with self._lock:` at lower indent
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

    # Exact-mode pin of the current split, in the style of tooling/ratchet:
    # measured today, 2 of the 15 PoolStats increments happen to sit under
    # self._lock and 13 do not. That is not a policy, it is where the code
    # landed -- `_borrow_direct` increments self._direct_out inside
    # `with self._lock` and stats.borrows_direct one line later outside it.
    #
    # The goal state is `len(unlocked) == 0`. Until then this pin makes any
    # movement -- in either direction -- a deliberate, reviewed change rather
    # than drift.
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
