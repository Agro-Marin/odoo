"""Shared PerfTimer warmup/timed-loop wrapper.

`TestDomainBenchmark._bench` and `TestPythonHotspots._bench` each hand-rolled
the same ~6-line warmup-then-timed loop around `odoo.tests.benchmark.PerfTimer`
— the exact kind of drifted duplicate `BenchmarkCase` (odoo/tests/benchmark.py)
exists to stop for the query/invalidate-aware harness. `PerfTimer` itself
already lives in that shared module; only the loop around it was duplicated
here, so it is factored into this one in-addon helper both files import,
without touching odoo/tests/benchmark.py (out of scope for this audit).
"""

from collections.abc import Callable

from odoo.tests.benchmark import PerfTimer


def run_perf_timer(func: Callable[[], None], n: int, warmup: int) -> PerfTimer:
    """Warm up `func`, then time it for `n` iterations with `PerfTimer`."""
    timer = PerfTimer()
    for _ in range(warmup):
        func()
    for _ in range(n):
        timer.start()
        func()
        timer.stop()
    return timer
