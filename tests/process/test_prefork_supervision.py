import os
import signal
import time

import pytest

from .conftest import Poller, requires_pg, requires_posix

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

    def test_no_connection_is_refused_while_a_worker_is_recycled(self, prefork):
        """The property `wait_until(is_serving)` above cannot see.

        That assertion asks whether the server is up *now*, so it answers yes
        the moment it recovers and says nothing about the window in between.
        Only a client already knocking during the recycle can tell you the door
        was ever shut — which is why `test_reload_continuity` polls, and why
        this suite owed the same for the kill path.

        `refused` is the count that matters and it is not a proxy: the prefork
        master binds the listen socket and workers inherit it, so a
        `ConnectionRefusedError` means the socket was closed or never re-bound,
        never that a worker was merely busy. That is a real regression shape —
        a master that rebinds on losing a worker, or one that dies with it —
        and it is exactly the shape a recovery-based assertion hides.

        Resets are NOT asserted on. SIGKILLing a worker that is holding a
        connection drops that connection by definition, so `other` is reported
        for diagnosis and left alone.

        That `refused` can rise at all is proved by
        `test_reload_continuity.test_the_poller_would_notice_a_dead_port`, which
        points the same `Poller` at a closed port. Moving the class into
        `conftest` is what makes that one self-test serve both suites.
        """
        victim = min(w.pid for w in prefork.http_workers())
        with Poller(prefork.port) as poller:
            time.sleep(0.5)
            before = poller.served
            assert before > 0, "the poller never reached the server before the kill"

            os.kill(victim, signal.SIGKILL)
            assert prefork.wait_until(
                lambda: (
                    len(prefork.http_workers()) == WORKERS
                    and victim not in {w.pid for w in prefork.http_workers()}
                ),
                timeout=60,
            ), "master did not replace the killed worker"
            # Keep polling past the recycle, so the count below covers the
            # window and not just its edges.
            time.sleep(0.5)
            served, refused, other = poller.served, poller.refused, poller.other

        assert refused == 0, (
            f"{refused} connection(s) REFUSED while a worker was recycled "
            f"({served} served, other errors: {sorted(set(other))}). The master "
            f"owns the listen socket and the surviving worker inherits it, so a "
            f"refusal means the socket was dropped rather than that a worker "
            f"was busy."
        )
        assert served > before, (
            f"the poller stopped being served across the recycle "
            f"({before} -> {served}); the assertion above would pass vacuously "
            f"if nothing reached the server at all"
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
