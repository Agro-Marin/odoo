import os
import signal

import pytest

from .conftest import requires_pg, requires_posix

WORKERS = 2


@requires_pg
@requires_posix
class TestPreforkReplacesAKilledWorker:
    @pytest.fixture
    def prefork(self, server):
        srv = server("--workers", str(WORKERS))
        assert srv.wait_until(lambda: len(srv.http_workers()) == WORKERS, timeout=60), (
            f"master did not reach a population of {WORKERS}; "
            f"children: {[c.pid for c in srv.children()]}"
        )
        return srv

    def test_population_converges(self, prefork):
        assert len(prefork.http_workers()) == WORKERS
        assert prefork.is_serving()

    def test_a_sigkilled_worker_is_replaced(self, prefork):
        before = {w.pid for w in prefork.http_workers()}
        victim = min(before)
        os.kill(victim, signal.SIGKILL)

        replaced = prefork.wait_until(
            lambda: (
                len(prefork.http_workers()) == WORKERS
                and victim not in {w.pid for w in prefork.http_workers()}
            ),
            timeout=60,
        )
        after = {w.pid for w in prefork.http_workers()}
        assert replaced, (
            f"master did not replace worker {victim}: population went "
            f"{sorted(before)} -> {sorted(after)}"
        )
        assert prefork.is_serving(), "server stopped serving after a worker died"

    def test_the_dead_worker_is_reaped_not_left_defunct(self, prefork):
        victim = min(w.pid for w in prefork.http_workers())
        os.kill(victim, signal.SIGKILL)
        assert prefork.wait_until(
            lambda: victim not in {w.pid for w in prefork.http_workers()}, timeout=60
        )
        reaped = prefork.wait_until(lambda: not prefork.zombie_children(), timeout=30)
        assert reaped, (
            f"unreaped worker(s) left defunct: {prefork.zombie_children()}. The "
            f"master is the only process that can reap them, so this leaks a "
            f"process-table entry per recycle."
        )
