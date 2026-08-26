import os
import signal
import socket
import threading
import time

from .conftest import requires_pg, requires_posix

WORKERS = 2
RELOAD_TIMEOUT_S = 60.0


def _child_pids(srv):
    return {worker.pid for worker in srv.http_workers()}


class _Poller(threading.Thread):
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
        time.sleep(1.0)
        baseline = poller.served
        assert baseline > 0, "the poller never reached the server before the reload"

        os.kill(srv.proc.pid, signal.SIGHUP)

        def reload_complete():
            current = _child_pids(srv)
            return bool(current) and not (original & current) and srv.is_serving(3)

        done = srv.wait_until(reload_complete, timeout=RELOAD_TIMEOUT_S, interval=0.5)
        poller.stop_flag.set()
        poller.join(timeout=10)

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
        log = srv.log_text()
        assert "Reloading server" in log and "New server has started" in log, (
            "SIGHUP did not drive the fork_and_reload handshake; this test is "
            "no longer exercising the socket handoff"
        )

    def test_the_poller_would_notice_a_dead_port(self, server):
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
