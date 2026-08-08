"""Harness for the process-level suite.

These tests boot a real ``odoo-bin`` and assert on what an outside observer can
see: a listening port, a process tree, an HTTP response.  Everything else about
the service layer is covered far more cheaply by the mock-based suites in
``tests/service`` — this exists only for the handful of properties that emerge
from real processes and cannot be simulated:

* a listen socket surviving a re-exec,
* a master noticing a killed child and replacing it,
* a bounded thread pool under real half-open sockets.

Four decisions here were paid for in an audit and should not be undone:

**Readiness is a served request, never a log line.**  ``ThreadedServer.run``
calls ``self.start()`` — which spawns the WSGI server and logs "HTTP service
(werkzeug) running" — BEFORE ``preload_registries``, both under
``Registry._lock``.  So the socket accepts and the log claims readiness while
every request still blocks on that lock.  A log-predicate wait would race.

**Kill by recorded pid and psutil tree, never by ``pkill -f``.**  A pattern
matching the server's argv also matches the harness that launched it.

**Always ``--logfile``.**  A shell ``>`` redirect drops a large fraction of
odoo-bin's output, so any log assertion built on it is flaky for reasons that
have nothing to do with the server.

**No database.**  None of these properties needs one: sockets, forks and thread
pools are all observable against a server with no ``-d``.  Skipping it keeps the
suite at seconds and removes a whole class of state-leak flakiness.
"""

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from .._pg import pg_reachable

REPO_ROOT = Path(__file__).resolve().parents[2]
ODOO_BIN = REPO_ROOT / "odoo-bin"

# Wall-clock ceiling for a server to answer its first request.  Generous: a
# loaded CI box is slow, and a too-tight bound turns into an intermittent
# failure that teaches nobody anything.
BOOT_TIMEOUT_S = 90.0

# Plain markers resolved by the autouse fixture below, not eager ``skipif``
# conditions: a ``skipif`` argument runs when the decorator does, i.e. during
# collection, so merely listing this suite paid a real connect attempt.  The
# probe itself is shared with ``tests/contract`` (it used to exist here in a
# second, subtly different copy) and cached, so both suites in one invocation
# cost one connect rather than two.  See ``tests/_pg``.
requires_pg = pytest.mark.requires_pg
requires_posix = pytest.mark.requires_posix

_REQUIREMENTS = {
    "requires_pg": (pg_reachable, "process suite needs a reachable PostgreSQL"),
    "requires_posix": (
        lambda: os.name == "posix",
        "process suite exercises POSIX fork/signal behaviour",
    ),
}


def pytest_configure(config):
    for name in _REQUIREMENTS:
        config.addinivalue_line("markers", f"{name}: needs that external dependency")


@pytest.fixture(autouse=True)
def _skip_without_dependencies(request):
    """Skip a test whose external dependency is absent — resolved lazily."""
    for name, (available, reason) in _REQUIREMENTS.items():
        if request.node.get_closest_marker(name) and not available():
            pytest.skip(reason)


def free_port() -> int:
    """An unused TCP port.

    Inherently racy — the port is released before the server claims it — so
    callers must tolerate a failed bind.  ``server()`` retries for that reason.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerHandle:
    """A running ``odoo-bin`` plus the observations tests make about it."""

    def __init__(self, proc, port, logfile):
        self.proc = proc
        self.port = port
        self.logfile = logfile

    # -- observation --------------------------------------------------------
    def get(self, path="/", timeout=10):
        """Issue a request; return the status code, or raise for a refusal.

        Any HTTP status counts as "served" — the suite cares whether the server
        answered at all, not what it said.
        """
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def is_serving(self, timeout=5):
        try:
            self.get(timeout=timeout)
            return True
        except Exception:
            return False

    def log_text(self):
        return Path(self.logfile).read_text(encoding="utf-8", errors="replace")

    def wait_for_log(self, needle, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.log_text():
                return True
            time.sleep(0.1)
        return False

    def children(self):
        """Live direct children (prefork workers, the evented subprocess)."""
        try:
            return psutil.Process(self.proc.pid).children(recursive=False)
        except psutil.NoSuchProcess:
            return []

    def worker_pids(self):
        return {c.pid for c in self.children() if c.is_running()}

    def wait_until(self, predicate, timeout=30, interval=0.2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return False

    # -- teardown -----------------------------------------------------------
    def kill_tree(self):
        try:
            root = psutil.Process(self.proc.pid)
        except psutil.NoSuchProcess:
            return
        procs = root.children(recursive=True) + [root]
        for p in procs:
            with contextlib.suppress(psutil.NoSuchProcess):
                p.kill()
        psutil.wait_procs(procs, timeout=10)


@pytest.fixture
def server(tmp_path):
    """Factory: boot ``odoo-bin`` with ``args`` and wait until it SERVES.

    Yields a ``ServerHandle``.  Every server started through the factory is
    torn down (whole process tree) at the end of the test, including on failure.
    """
    started = []

    def _start(*args, env=None, wait=True, attempts=3):
        last_error = None
        for attempt in range(attempts):
            port = free_port()
            logfile = tmp_path / f"srv_{port}_{attempt}.log"
            cmd = [
                sys.executable,
                str(ODOO_BIN),
                "--http-port",
                str(port),
                "--gevent-port",
                str(free_port()),
                "--logfile",
                str(logfile),
                "--max-cron-threads",
                "0",
                "--job-workers",
                "0",
                *args,
            ]
            proc = subprocess.Popen(
                cmd,
                env={**os.environ, **(env or {})},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            handle = ServerHandle(proc, port, logfile)
            started.append(handle)
            if not wait:
                return handle
            deadline = time.monotonic() + BOOT_TIMEOUT_S
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break  # died during boot (likely a lost port race) -> retry
                if handle.is_serving(timeout=2):
                    return handle
                time.sleep(0.2)
            last_error = (
                f"server did not serve within {BOOT_TIMEOUT_S:.0f}s "
                f"(exit={proc.poll()}); log tail:\n"
                + "\n".join(handle.log_text().splitlines()[-15:])
            )
            handle.kill_tree()
        raise AssertionError(last_error)

    yield _start

    for handle in started:
        handle.kill_tree()
