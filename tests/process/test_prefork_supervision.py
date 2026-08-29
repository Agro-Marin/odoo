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
        assert prefork.wait_until(prefork.is_serving, timeout=30), (
            "server stopped serving after a worker died"
        )

    def test_no_connection_is_refused_while_a_worker_is_recycled(self, prefork):
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
