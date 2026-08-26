import contextlib
import socket
import time

from .conftest import requires_pg, requires_posix

MAX_THREADS = 4
N_ATTACKERS = MAX_THREADS + 2


@requires_pg
@requires_posix
class TestHalfOpenConnectionsDoNotStarveTheAcceptLoop:
    def test_a_normal_request_still_succeeds(self, server):
        srv = server(
            "--workers",
            "0",
            env={
                "ODOO_MAX_HTTP_THREADS": str(MAX_THREADS),
                "ODOO_HTTP_SOCKET_TIMEOUT": "1",
            },
        )

        attackers = []
        try:
            for _ in range(N_ATTACKERS):
                s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
                s.sendall(b"GET /slo")
                attackers.append(s)

            time.sleep(1.0)

            served = srv.wait_until(lambda: srv.is_serving(timeout=5), timeout=30)
            assert served, (
                f"{N_ATTACKERS} half-open connections starved a pool of "
                f"{MAX_THREADS}: the server stopped answering. The "
                f"per-operation socket timeout is not bounding the "
                f"request-read phase."
            )
        finally:
            for s in attackers:
                with contextlib.suppress(OSError):
                    s.close()

    def test_the_pool_recovers_after_repeated_bursts(self, server):
        srv = server(
            "--workers",
            "0",
            env={
                "ODOO_MAX_HTTP_THREADS": str(MAX_THREADS),
                "ODOO_HTTP_SOCKET_TIMEOUT": "1",
            },
        )
        for _ in range(3):
            attackers = [
                socket.create_connection(("127.0.0.1", srv.port), timeout=5)
                for _ in range(N_ATTACKERS)
            ]
            for s in attackers:
                s.sendall(b"GET /slo")
            for s in attackers:
                s.close()
            time.sleep(1.5)

        assert srv.wait_until(lambda: srv.is_serving(timeout=5), timeout=30), (
            "the thread pool did not recover after repeated half-open bursts; "
            "a slot is leaking on the EOF path"
        )
