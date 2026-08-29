from collections.abc import Callable

from odoo.tests.benchmark import PerfTimer


def run_perf_timer(func: Callable[[], None], n: int, warmup: int) -> PerfTimer:
    timer = PerfTimer()
    for _ in range(warmup):
        func()
    for _ in range(n):
        timer.start()
        func()
        timer.stop()
    return timer
