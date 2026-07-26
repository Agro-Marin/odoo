"""Half-open connections must not exhaust the bounded HTTP thread pool.

``wsgi.http_socket_timeout`` documents a MEASURED denial of service: on the
threaded server, "six connections sending nine bytes each (``GET /slow``, no
CRLF) drained the pool to 0/4 and every subsequent request timed out — an
unauthenticated denial of service costing the attacker almost nothing."

The fix (a per-operation socket timeout on every connection, not only under
``--test-enable``) is unit-tested in ``tests/service``, but only as "``setup``
assigns ``self.timeout``".  That assertion would still pass if the timeout were
never armed on the socket, if werkzeug stopped honouring it, or if the semaphore
were released on the wrong path — the attack is a property of real sockets
against a real accept loop, so it is reproduced here as one.
"""

import contextlib
import socket
import time

from .conftest import requires_pg, requires_posix

# Small enough to exhaust quickly, large enough that the server is genuinely
# multi-threaded.  The attack opens more than this many sockets.
MAX_THREADS = 4
N_ATTACKERS = MAX_THREADS + 2


@requires_pg
@requires_posix
class TestHalfOpenConnectionsDoNotStarveTheAcceptLoop:
    def test_a_normal_request_still_succeeds(self, server):
        srv = server(
            "--workers",
            "0",  # threaded server: the flavour with the bound
            env={
                "ODOO_MAX_HTTP_THREADS": str(MAX_THREADS),
                # The defence under test.  Keep it short so the test does not
                # have to wait out a production-sized deadline.
                "ODOO_HTTP_SOCKET_TIMEOUT": "1",
            },
        )

        attackers = []
        try:
            for _ in range(N_ATTACKERS):
                s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
                # A request line that never terminates: the handler blocks in
                # readline() holding one of the bounded slots.
                s.sendall(b"GET /slo")
                attackers.append(s)

            # Give the accept loop a moment to pick every attacker up, so the
            # test measures a genuinely saturated pool rather than a race.
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

    def test_the_pool_recovers_after_the_attack_stops(self, server):
        """Slots must come back, i.e. the semaphore is released on the timeout
        path too — a leak there would degrade the server permanently rather
        than for the duration of the attack."""
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
            time.sleep(1.5)  # let the timeouts fire and the slots return

        assert srv.wait_until(lambda: srv.is_serving(timeout=5), timeout=30), (
            "the thread pool did not recover after repeated half-open bursts; "
            "a slot is leaking on the socket-timeout path"
        )
