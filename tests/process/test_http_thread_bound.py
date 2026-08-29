import contextlib
import socket
import time

from .conftest import requires_pg, requires_posix

MAX_THREADS = 4
N_ATTACKERS = MAX_THREADS + 2

SOCKET_TIMEOUT_S = 1

RECOVERY_BUDGET_S = 4 * SOCKET_TIMEOUT_S


def _time_to_recover(srv, budget=RECOVERY_BUDGET_S):
    start = time.monotonic()
    if srv.wait_until(lambda: srv.is_serving(timeout=budget), timeout=budget):
        return time.monotonic() - start
    return None


@requires_pg
@requires_posix
class TestHalfOpenConnectionsDoNotStarveTheAcceptLoop:
    def test_a_normal_request_still_succeeds(self, server):
        srv = server(
            "--workers",
            "0",
            env={
                "ODOO_MAX_HTTP_THREADS": str(MAX_THREADS),
                "ODOO_HTTP_SOCKET_TIMEOUT": str(SOCKET_TIMEOUT_S),
            },
        )

        attackers = []
        try:
            for _ in range(N_ATTACKERS):
                s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
                s.sendall(b"GET /slo")
                attackers.append(s)

            elapsed = _time_to_recover(srv)
            assert elapsed is not None, (
                f"{N_ATTACKERS} half-open connections starved a pool of "
                f"{MAX_THREADS}: the server did not answer within "
                f"{RECOVERY_BUDGET_S}s. The per-operation socket timeout is "
                f"not bounding the request-read phase."
            )
            assert elapsed <= RECOVERY_BUDGET_S, (
                f"the server recovered, but only after {elapsed:.1f}s against a "
                f"configured ODOO_HTTP_SOCKET_TIMEOUT of {SOCKET_TIMEOUT_S}s. "
                f"The bound is being honoured at the wrong magnitude."
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
                "ODOO_HTTP_SOCKET_TIMEOUT": str(SOCKET_TIMEOUT_S),
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

            elapsed = _time_to_recover(srv)
            assert elapsed is not None and elapsed <= RECOVERY_BUDGET_S, (
                f"the thread pool did not recover within {RECOVERY_BUDGET_S}s "
                f"after a half-open burst (took {elapsed}); a slot is leaking "
                f"on the EOF path"
            )
