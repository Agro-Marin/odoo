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

import signal
import time

import psutil
import pytest

from .conftest import requires_pg, requires_posix

WORKERS = 2


def _http_workers(srv):
    """Direct children that are forked workers, not the evented subprocess.

    The evented long-poller is a ``Popen`` of ``odoo-bin evented``, so it is a
    child too; it is excluded by its command line rather than by counting, which
    would silently drift if the master ever spawned something else.
    """
    out = []
    for child in srv.children():
        try:
            if "evented" not in " ".join(child.cmdline()):
                out.append(child)
        except psutil.NoSuchProcess, psutil.AccessDenied:
            continue
    return out


@requires_pg
@requires_posix
class TestPreforkReplacesAKilledWorker:
    @pytest.fixture
    def prefork(self, server):
        srv = server("--workers", str(WORKERS))
        assert srv.wait_until(lambda: len(_http_workers(srv)) == WORKERS, timeout=60), (
            f"master did not reach a population of {WORKERS}; "
            f"children: {[c.pid for c in srv.children()]}"
        )
        return srv

    def test_population_converges(self, prefork):
        assert len(_http_workers(prefork)) == WORKERS
        assert prefork.is_serving()

    def test_a_sigkilled_worker_is_replaced(self, prefork):
        """The property the whole supervisor exists for.

        SIGKILL, not SIGTERM: uncatchable, so this tests the master's reaping
        and respawn rather than any cooperative shutdown path in the worker.
        """
        before = {w.pid for w in _http_workers(prefork)}
        victim = min(before)
        os_kill(victim)

        replaced = prefork.wait_until(
            lambda: (
                len(_http_workers(prefork)) == WORKERS
                and victim not in {w.pid for w in _http_workers(prefork)}
            ),
            timeout=60,
        )
        after = {w.pid for w in _http_workers(prefork)}
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
        victim = min(w.pid for w in _http_workers(prefork))
        os_kill(victim)
        assert prefork.wait_until(
            lambda: victim not in {w.pid for w in _http_workers(prefork)}, timeout=60
        )
        # Let the master finish its reap cycle (it polls on a ~4s beat).
        time.sleep(1.0)
        zombies = []
        for child in prefork.children():
            try:
                if child.status() == psutil.STATUS_ZOMBIE:
                    zombies.append(child.pid)
            except psutil.NoSuchProcess:
                continue
        assert not zombies, f"unreaped worker(s) left defunct: {zombies}"


def os_kill(pid):
    import os

    os.kill(pid, signal.SIGKILL)
