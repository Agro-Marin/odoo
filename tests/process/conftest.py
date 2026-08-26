import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from .._pg import dependency_plugin, pg_reachable

REPO_ROOT = Path(__file__).resolve().parents[2]
ODOO_BIN = REPO_ROOT / "odoo-bin"

BOOT_TIMEOUT_S = 90.0

requires_pg = pytest.mark.requires_pg
requires_posix = pytest.mark.requires_posix

REQUIREMENTS = {
    "requires_pg": (pg_reachable, "process suite needs a reachable PostgreSQL"),
    "requires_posix": (
        lambda: os.name == "posix",
        "process suite exercises POSIX fork/signal behaviour",
    ),
}

pytest_configure, _skip_without_dependencies = dependency_plugin(REQUIREMENTS)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerHandle:
    def __init__(self, proc, port, logfile):
        self.proc = proc
        self.port = port
        self.logfile = logfile

    def get(self, path="/", timeout=10):
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

    def children(self):
        try:
            return psutil.Process(self.proc.pid).children(recursive=False)
        except psutil.NoSuchProcess:
            return []

    def http_workers(self):
        out = []
        for child in self.children():
            try:
                if child.status() == psutil.STATUS_ZOMBIE:
                    continue
                if "evented" not in " ".join(child.cmdline()):
                    out.append(child)
            except psutil.NoSuchProcess, psutil.AccessDenied:
                continue
        return out

    def zombie_children(self):
        out = []
        for child in self.children():
            try:
                if child.status() == psutil.STATUS_ZOMBIE:
                    out.append(child.pid)
            except psutil.NoSuchProcess:
                continue
        return out

    def wait_until(self, predicate, timeout=30, interval=0.2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return False

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
                    break
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
