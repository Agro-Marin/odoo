"""A prefork reload must not drop the listen socket.

This is the whole point of ``fork_and_reload`` + ``ODOO_HTTP_SOCKET_FD``: the
original master hands its bound listening socket to the re-exec'd one, and the
outgoing master keeps its workers serving until the newcomer signals readiness.
Done right, a client cannot tell a reload happened; done wrong, the port is
unbound for the length of a full server boot and every request in that window is
refused.

No unit test can show this.  The mechanism is a real ``fork``, a real
``execve``, an inherited file descriptor and a real signal handshake between two
processes — mock any of it and the thing being asserted is gone.  ``tests/service``
covers the decision logic around it (``TestForkAndReloadTimeout``,
``TestPreforkPhoenixStopTerminatesSurvivors``); this covers the property those
decisions exist to protect.

The assertion is deliberately narrow: **zero ECONNREFUSED**.  A reset or a
timeout on an in-flight connection is a real but different (and much less
severe) event, and asserting on it would make the test hostage to scheduling.
Refusal is the one outcome the socket handoff is supposed to make impossible,
and the one an operator's load balancer turns into a 502.
"""

import os
import signal
import socket
import threading
import time

from .conftest import requires_pg, requires_posix

WORKERS = 2
# Observed reload of a database-less prefork server: ~1.5s.  60s is ~40x that,
# generous for a loaded CI box, and bounds how long a BROKEN handoff takes to
# report -- the earlier 180s turned a clear failure into a three-minute wait.
RELOAD_TIMEOUT_S = 60.0


def _child_pids(srv):
    """Worker pids, via the shared ``ServerHandle`` helper.

    At boot this is exactly the worker set.  During a reload the outgoing
    master's drain process is a fork of the master and therefore shares its
    command line, so this set is NOT a reliable worker count mid-reload — which
    is why the completion signal below keys on the ORIGINAL pids disappearing
    rather than on any count.
    """
    return {worker.pid for worker in srv.http_workers()}


class _Poller(threading.Thread):
    """Hammer the port and classify every outcome."""

    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.stop_flag = threading.Event()
        self.served = 0
        self.refused = 0
        self.other = []

    def run(self):
        while not self.stop_flag.is_set():
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
                    s.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                    s.recv(64)
                self.served += 1
            except ConnectionRefusedError:
                # The one outcome the socket handoff must make impossible.
                self.refused += 1
            except Exception as exc:
                self.other.append(type(exc).__name__)
            time.sleep(0.02)


@requires_pg
@requires_posix
class TestSighupReloadKeepsServing:
    def test_no_connection_is_refused_across_a_reload(self, server):
        srv = server("--workers", str(WORKERS))
        assert srv.wait_until(lambda: len(_child_pids(srv)) == WORKERS, timeout=60), (
            "master never reached its worker population"
        )
        original = _child_pids(srv)

        poller = _Poller(srv.port)
        poller.start()
        time.sleep(1.0)  # establish a baseline of successful requests
        baseline = poller.served
        assert baseline > 0, "the poller never reached the server before the reload"

        os.kill(srv.proc.pid, signal.SIGHUP)

        # Reload is complete once every ORIGINAL worker is gone and the server
        # answers again.  Keyed on the original pids, not on a count, because
        # mid-reload the child set also holds the outgoing master's drain
        # process (a fork, so it looks exactly like a worker from outside).
        def reload_complete():
            current = _child_pids(srv)
            # NEW children must exist as well as the old ones being gone: the
            # two conditions can otherwise both hold in the brief window after
            # the outgoing workers exit and before the newcomer forks its own,
            # which would let this return before the reload finished.
            return bool(current) and not (original & current) and srv.is_serving(3)

        done = srv.wait_until(reload_complete, timeout=RELOAD_TIMEOUT_S, interval=0.5)
        poller.stop_flag.set()
        poller.join(timeout=10)

        # Refusals FIRST: it is the property under test, and when the handoff
        # is broken it is also the accurate diagnosis.  Asserting completion
        # first reported "reload did not complete" for what was really "the port
        # went away", which points at the wrong subsystem.
        assert poller.refused == 0, (
            f"{poller.refused} connection(s) REFUSED during the reload "
            f"({poller.served} served, other errors: {set(poller.other)}). The "
            f"listen socket was not carried across the re-exec, so the port was "
            f"unbound for the length of a server boot."
        )
        assert done, (
            f"reload did not complete within {RELOAD_TIMEOUT_S:.0f}s; original "
            f"workers still alive: {sorted(original & _child_pids(srv))}, "
            f"current children: {sorted(_child_pids(srv))}"
        )
        assert poller.served > baseline, (
            "no request was served after the reload started; the test proves "
            "nothing about continuity"
        )
        assert srv.is_serving(), "server is not serving after the reload"
        # A reload really happened, rather than the worker set churning for some
        # other reason.  The re-exec'd master inherits ``--logfile``, so both
        # generations write here (verified: two "HTTP service" lines).
        log = srv.log_text()
        assert "Reloading server" in log and "New server has started" in log, (
            "SIGHUP did not drive the fork_and_reload handshake; this test is "
            "no longer exercising the socket handoff"
        )

    def test_the_poller_would_notice_a_dead_port(self, server):
        """Guard against the assertion above passing vacuously.

        ``refused == 0`` is only evidence if a refusal would actually have been
        counted.  Point the same poller at a port with nothing behind it and
        confirm it reports refusals.
        """
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        poller = _Poller(dead_port)
        poller.start()
        time.sleep(0.5)
        poller.stop_flag.set()
        poller.join(timeout=10)
        assert poller.refused > 0, (
            "the poller does not detect a closed port, so the continuity "
            "assertion above would pass no matter what the server did"
        )
