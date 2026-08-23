import sys
import threading

import pytest

from odoo.db.budget import ConnectionBudget
from odoo.db.leaks import CheckoutTracker
from odoo.db.stats import _PROBE_OUTCOMES, PoolStats

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


def test_pool_never_mutates_a_counter_directly():
    """Every PoolStats field is mutated through PoolStats, under its own lock.

    This pin used to read `(2 locked, 13 unlocked)` and count how many of
    `pool.py`'s raw `self.stats.x += 1` sites happened to sit inside a
    `with self._lock:` block.  Both numbers were wrong -- the scan matched a
    lock block that had already CLOSED above the statement -- and the shape it
    described was the wrong one anyway: the pool's lock guards the pool's
    `_pools` dict, not the counters, so a counter that happened to be under it
    was protected by accident.

    PoolStats now owns a lock and exposes one method per counter, so the
    invariant is simply that `pool.py` contains no raw mutation at all.
    """
    import pathlib
    import re

    pool_py = pathlib.Path(__file__).resolve().parents[1] / "pool.py"
    raw = re.findall(r"self\.stats\.\w+\s*[-+]=", pool_py.read_text(encoding="utf-8"))
    assert not raw, (
        f"{len(raw)} raw PoolStats mutation(s) in pool.py: {raw}. "
        f"`x += 1` on an attribute is a non-atomic read-modify-write, so the "
        f"counters that exist to diagnose concurrency are the ones that lose "
        f"increments under it. Add a record_* method to PoolStats instead."
    )


def test_every_counter_has_a_recorder_that_takes_the_lock():
    import inspect

    counters = {f for f in PoolStats.__slots__ if not f.startswith("_")}
    # the probe recorder resolves its field through _PROBE_OUTCOMES, so the
    # mapping is that recorder's declaration of what it covers
    recorded = set(_PROBE_OUTCOMES.values())
    for name, member in inspect.getmembers(PoolStats, inspect.isfunction):
        if not name.startswith("record_"):
            continue
        src = inspect.getsource(member)
        assert "self._lock" in src, f"PoolStats.{name} mutates without the lock"
        recorded |= {c for c in counters if c in src}
    missing = counters - recorded
    assert not missing, (
        f"PoolStats fields with no locked recorder: {sorted(missing)} -- "
        f"whoever mutates them is doing it raw."
    )


def test_snapshot_reads_every_counter_under_the_lock():
    import inspect

    src = inspect.getsource(PoolStats.snapshot)
    assert "with self._lock:" in src, (
        "snapshot() renders the histogram alongside the total it summarises; "
        "reading them unlocked lets health() report a histogram that does not "
        "sum to its own borrow count"
    )


def test_the_histogram_still_agrees_with_the_total_under_load():
    stats = PoolStats()
    _hammer(lambda: stats.record_borrow(0.0))
    assert stats.borrows == EXPECTED
    assert sum(stats.borrow_wait_buckets) == stats.borrows


def test_probe_outcomes_are_named_not_spelled():
    stats = PoolStats()
    stats.record_probe_outcome("permanent")
    stats.record_probe_outcome("transient")
    stats.record_probe_outcome("skipped_proven")
    assert (
        stats.probe_permanent,
        stats.probe_transient,
        stats.probe_skipped_proven,
    ) == (1, 1, 1)
    try:
        stats.record_probe_outcome("nonsense")
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown probe outcome must not silently vanish")


def test_the_process_wide_sql_counter_is_not_lost():
    """`sql_counter` is a module global that every cursor in the process
    increments with `+=`, which is a non-atomic read-modify-write.

    Under the GIL this holds today -- measured, 0 lost of 160000 across 8
    threads -- so nothing is locked for it: a lock on `_record_metrics` is a
    lock on the hottest path in core, and it would buy nothing measurable. What
    this test buys is that the free-threading lane can SEE it: `odoo/db/**` is
    in `freethreading.yml`'s paths and this file is the suite it runs, so if the
    GIL goes away the answer changes here rather than silently in production
    query counts.

    `sql_log_count` is per-cursor and a cursor belongs to one thread, so it is
    only checked for company.
    """
    from odoo.db import metrics

    class _Host(metrics._MetricsMixin):
        def __init__(self):
            self._init_metrics_state()
            self._thread = threading.current_thread()

    host = _Host()
    before = metrics.sql_counter
    _hammer(lambda: host._record_metrics(0.0))
    assert metrics.sql_counter - before == EXPECTED, (
        f"lost {EXPECTED - (metrics.sql_counter - before)} of {EXPECTED} "
        f"increments to the process-wide sql_counter. Every query-count "
        f"measurement in the framework reads it -- odoo/tests/result.py, "
        f"modules/loading.py, service/lifecycle.py -- so a lost increment is a "
        f"query nobody was charged for."
    )
    assert host.sql_log_count == EXPECTED


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
