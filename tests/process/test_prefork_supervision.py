"""The prefork master must notice a dead worker and replace it.

``tests/service`` covers the supervision LOGIC thoroughly — ``process_zombie``,
``process_spawn``, ``_note_worker_exit``, the respawn backoff — by driving those
methods with fabricated ``waitpid`` results and mock workers.  That is the right
way to test the decision table, and it says nothing about whether the decisions
are wired to real signals: a master that never installs its ``SIGCHLD`` handler,
never reaps, or reaps into the wrong registry would pass every one of them.

So this asserts the composed behaviour from outside, with real forks: the
population converges, an externally killed worker is replaced, nothing is left
defunct, and the server keeps serving throughout.
"""

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
        """The property the whole supervisor exists for.

        SIGKILL, not SIGTERM: uncatchable, so this tests the master's reaping
        and respawn rather than any cooperative shutdown path in the worker.
        """
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
        """A replaced-but-unreaped worker is a zombie.

        The master is the only process that can reap them, so a supervisor that
        respawns without reaping leaks a process-table entry per recycle — over
        a long uptime with ``limit_request`` recycling, that is unbounded.
        """
        victim = min(w.pid for w in prefork.http_workers())
        os.kill(victim, signal.SIGKILL)
        assert prefork.wait_until(
            lambda: victim not in {w.pid for w in prefork.http_workers()}, timeout=60
        )
        # Wait on the CONDITION, not on a duration.  This was `time.sleep(1.0)`
        # under a comment saying the master polls on a ~4s beat — under-waiting
        # by its own reasoning.  (Measured, the master reaps on SIGCHLD in ~6ms,
        # so the sleep was also 160x longer than needed; a condition wait is
        # right at both ends.)
        reaped = prefork.wait_until(lambda: not prefork.zombie_children(), timeout=30)
        assert reaped, (
            f"unreaped worker(s) left defunct: {prefork.zombie_children()}. The "
            f"master is the only process that can reap them, so this leaks a "
            f"process-table entry per recycle."
        )
