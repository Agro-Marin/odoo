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
        # Waited for, not sampled — the only assertion in this class that used
        # to sample. The predicate above is satisfied when the replacement
        # *process exists*, which psutil reports the moment the master forks;
        # it says nothing about the worker having finished booting and reached
        # `accept()` on the shared listen socket. With WORKERS=2 and one just
        # SIGKILLed, a single `is_serving()` in that window depends on the one
        # surviving worker answering within five seconds, and on a loaded box
        # it does not: this failed 2 runs in 5, reporting "server stopped
        # serving" for a server that was serving again a moment later.
        #
        # This is the property the message claims — a server that STAYS down —
        # and it is the weaker of the two available. Asserting that not one
        # connection was refused across the recycle would be stronger and needs
        # a poller thread, the way `test_reload_continuity` does it.
        assert prefork.wait_until(prefork.is_serving, timeout=30), (
            "server stopped serving after a worker died"
        )

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
