"""Prefork (multiprocess) server.

``PreforkServer`` (aka Multicorn) forks one ``Worker`` child (``_worker.py``)
per HTTP/cron slot and supervises them from a signal-driven master loop.
Subclasses ``CommonServer`` (``_base_server.py``).
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from typing import Any

import psutil

if os.name == "posix":
    import fcntl

from odoo import db
from odoo.modules.registry import Registry
from odoo.tools import config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks, stripped_sys_argv

from . import lifecycle  # mutated for ``server_phoenix`` (single source of truth)
from ._base_server import _SIGHUP_AVAILABLE, CommonServer
from ._env import env_float
from ._helpers import empty_pipe
from ._worker import Worker, WorkerCron, WorkerHTTP
from .lifecycle import _reexec, preload_registries

_logger = logging.getLogger("odoo.service.server")


class PreforkServer(CommonServer):
    """Multiprocessing inspired by (g)unicorn.
    PreforkServer (aka Multicorn) currently uses accept(2) as dispatching
    method between workers but we plan to replace it by a more intelligent
    dispatcher to parse the first HTTP request line.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        # config
        self.population = config["workers"]
        # ``limit_time_real <= 0`` means "no real-time watchdog": a 0 would make
        # every HTTP worker's ``watchdog_timeout`` 0, so ``process_timeout``
        # would SIGKILL brand-new workers at once and the master would respawn
        # them in a loop.
        self.timeout = config["limit_time_real"] or None
        self.limit_request = config["limit_request"]
        self.cron_timeout = config["limit_time_real_cron"] or None
        if self.cron_timeout == -1:
            self.cron_timeout = self.timeout
        # working vars
        self.beat = 4
        self.socket = None
        self.workers_http = {}
        self.workers_cron = {}
        self.workers = {}
        # Worker spawns over this server's lifetime (logs/diagnostics only).
        self.generation = 0
        self.queue = deque()
        self.long_polling_pid = None

    def pipe_new(self) -> tuple[int, int]:
        """Create a new non-blocking, close-on-exec pipe pair."""
        return os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def pipe_ping(self, pipe: tuple[int, int]) -> None:
        """Write a single byte to the write end of a pipe to wake the master."""
        try:
            os.write(pipe[1], b".")
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    #: Control signals that must never be dropped even when the queue is full of
    #: SIGCHLD storms: an operator still needs SIGINT/SIGTERM/SIGHUP to get
    #: through, and SIGTTIN/SIGTTOU reshape the worker pool.
    _UNDROPPABLE_SIGNALS = frozenset(
        {
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGTTIN,
            signal.SIGTTOU,
        }
        | ({signal.SIGHUP} if _SIGHUP_AVAILABLE else set())
    )

    def signal_handler(self, sig: int, frame: Any) -> None:
        # SIGCHLD is coalesced by the kernel; one pending SIGCHLD drives a
        # full ``waitpid(-1, WNOHANG)`` loop in ``process_zombie``, so a
        # single slot is enough regardless of how many children died.
        if sig == signal.SIGCHLD:
            if signal.SIGCHLD not in self.queue:
                self.queue.append(sig)
                self.pipe_ping(self.pipe)
            return
        if sig in self._UNDROPPABLE_SIGNALS or len(self.queue) < 5:
            self.queue.append(sig)
            self.pipe_ping(self.pipe)
        else:
            self.logger.warning("Dropping signal: %s", sig)

    def _close_inherited_pipe_fds_in_child(self, new_worker: Worker) -> None:
        """Release sibling workers' pipe fds that this child inherited via fork.

        ``os.pipe2(O_CLOEXEC)`` only closes on ``execve``, so after a bare
        ``fork`` the child still holds every sibling's ``watchdog_pipe`` /
        ``eintr_pipe`` plus the master wakeup pipe — leaked for the child's
        whole lifetime (N=8 workers → 30 fds/child, compounding under reload).
        Close them all except the new worker's own pipes.
        """
        keep = {
            new_worker.watchdog_pipe[0],
            new_worker.watchdog_pipe[1],
            new_worker.eintr_pipe[0],
            new_worker.eintr_pipe[1],
        }
        for sibling in self.workers.values():
            for fd in (
                sibling.watchdog_pipe[0],
                sibling.watchdog_pipe[1],
                sibling.eintr_pipe[0],
                sibling.eintr_pipe[1],
            ):
                if fd not in keep:
                    with contextlib.suppress(OSError):
                        os.close(fd)
        # Parent's master wakeup pipe: child never reads or writes it.
        for fd in self.pipe:
            if fd not in keep:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def worker_spawn(self, klass: type, workers_registry: dict) -> Worker | None:
        """Fork a new worker of the given class and register it."""
        self.generation += 1
        worker = klass(self)
        pid = os.fork()
        if pid != 0:
            worker.pid = pid
            self.workers[pid] = worker
            workers_registry[pid] = worker
            return worker
        else:
            # Detach from the master's queueing signal handler BEFORE closing
            # the master's pipe fds: a signal landing in this window would run
            # the inherited ``master.signal_handler``, ``pipe_ping`` a closed
            # fd, and raise ``OSError(EBADF)`` — a sporadic worker death.
            # Termination signals → SIG_DFL (killing a half-started worker is
            # fine; the master respawns).  SIGCHLD/SIGTTIN/SIGTTOU → SIG_IGN
            # (their SIG_DFL for TTIN/TTOU is *Stop*, which would suspend the
            # worker if a stray SIGTTOU leaked from the master).  Worker.start
            # re-installs the real handlers moments later.
            for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(_sig, signal.SIG_DFL)
            for _sig in (signal.SIGCHLD, signal.SIGTTIN, signal.SIGTTOU):
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(_sig, signal.SIG_IGN)
            self._close_inherited_pipe_fds_in_child(worker)
            exit_code = 0
            try:
                worker.run()
            except SystemExit as exc:
                # Translate SystemExit's varied .code semantics to a numeric
                # os._exit code: int → use as-is; None → 0; anything else → 1.
                if isinstance(exc.code, int):
                    exit_code = exc.code
                else:
                    exit_code = 0 if exc.code is None else 1
            except BaseException as exc:
                self.logger.critical(
                    "Worker %s (%d): uncaught error, exiting...",
                    worker.__class__.__name__,
                    os.getpid(),
                    exc_info=exc,
                )
                exit_code = 1
            # ``os._exit`` (not ``sys.exit``): after fork, atexit handlers and
            # stdio flushing share fds with the parent — running them here can
            # double-write logs or trip non-fork-safe destructors.
            os._exit(exit_code)

    def long_polling_spawn(self) -> None:
        """Spawn the evented long-polling subprocess."""
        nargs = stripped_sys_argv()
        cmd = [sys.executable, sys.argv[0], "evented"] + nargs[1:]
        popen = subprocess.Popen(cmd)
        self.long_polling_pid = popen.pid

    def worker_pop(self, pid: int) -> None:
        """Unregister and clean up a worker by PID.

        ``Worker.close`` suppresses per-fd ``OSError`` internally, so the
        bookkeeping pops run to completion even if the kernel has already
        released a pipe's fd on this side.
        """
        if pid == self.long_polling_pid:
            self.long_polling_pid = None
        if pid in self.workers:
            self.logger.debug("worker (%s) unregistered", pid)
            self.workers_http.pop(pid, None)
            self.workers_cron.pop(pid, None)
            self.workers.pop(pid).close()

    def worker_kill(self, pid: int, sig: int) -> None:
        """Send a signal to a worker, unregistering it on ESRCH or SIGKILL."""
        try:
            os.kill(pid, sig)
            if sig == signal.SIGKILL:
                self.worker_pop(pid)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self.worker_pop(pid)

    def process_signals(self) -> None:
        """Drain the signal queue and act on each pending signal.

        Only signals routed through ``self.signal_handler`` reach here.
        ``SIGQUIT``/``SIGUSR1``/``SIGUSR2`` are bound directly to their handlers
        in ``start()`` and never enter the queue.  ``SIGCHLD`` is enqueued only
        to wake the master from ``sleep``; the actual reaping is in
        ``process_zombie``, so it needs no branch here.
        """
        while self.queue:
            sig = self.queue.popleft()
            if sig in [signal.SIGINT, signal.SIGTERM]:
                raise KeyboardInterrupt
            if sig == signal.SIGHUP:
                # restart on kill -HUP.  Write through lifecycle (canonical).
                lifecycle.server_phoenix = True
                raise KeyboardInterrupt
            if sig == signal.SIGTTIN:
                # increase number of workers
                self.population += 1
            elif sig == signal.SIGTTOU:
                # decrease number of workers; clamp at 0 so an over-zealous
                # operator can't drive population negative (which would stop the
                # spawn loop and drain the server to zero workers).
                self.population = max(self.population - 1, 0)

    def process_zombie(self) -> None:
        """Reap dead workers via ``waitpid(-1, WNOHANG)``."""
        while True:
            try:
                wpid, _status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
                self.worker_pop(wpid)
            except OSError as e:
                if e.errno == errno.ECHILD:
                    break
                raise

    def process_timeout(self) -> None:
        """Kill workers that have exceeded their watchdog timeout."""
        now = time.monotonic()
        for pid, worker in list(self.workers.items()):
            if (
                worker.watchdog_timeout is not None
                and (now - worker.watchdog_time) >= worker.watchdog_timeout
            ):
                self.logger.error(
                    "%s (%s) timeout after %ss",
                    worker.__class__.__name__,
                    pid,
                    worker.watchdog_timeout,
                )
                self.worker_kill(pid, signal.SIGKILL)

    def process_spawn(self) -> None:
        # Before spawning any process, check the registry signaling
        registries = Registry.registries.snapshot

        def check_registries():
            # check the registries on the first call only!
            if not registries:
                return
            for registry in registries.values():
                with registry.cursor() as cr:
                    registry.check_signaling(cr)
            registries.clear()
            # Close all opened cursors
            db.close_all()

        if config["http_enable"]:
            while len(self.workers_http) < self.population:
                check_registries()
                self.worker_spawn(WorkerHTTP, self.workers_http)
            if not self.long_polling_pid:
                check_registries()
                self.long_polling_spawn()
        while len(self.workers_cron) < config["max_cron_threads"]:
            check_registries()
            self.worker_spawn(WorkerCron, self.workers_cron)

    def sleep(self) -> None:
        """Wait for worker pings or internal wakeups, updating watchdog timestamps."""
        try:
            # map of fd -> worker
            fds = {w.watchdog_pipe[0]: w for w in self.workers.values()}
            # check for ping or internal wakeups
            with selectors.DefaultSelector() as sel:
                for fd in list(fds) + [self.pipe[0]]:
                    sel.register(fd, selectors.EVENT_READ)
                ready = sel.select(self.beat)
            # update worker watchdogs
            for key, _ in ready:
                fd = key.fileobj
                if fd in fds:
                    fds[fd].watchdog_time = time.monotonic()
                empty_pipe(fd)
        except OSError as e:
            if e.args[0] != errno.EINTR:
                raise

    def start(self) -> None:
        # wakeup pipe, python doesn't throw EINTR when a syscall is interrupted
        # by a signal simulating a pseudo SA_RESTART. We write to a pipe in the
        # signal handler to overcome this behaviour
        self.pipe = self.pipe_new()
        # set signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, self.signal_handler)
        signal.signal(signal.SIGCHLD, self.signal_handler)
        signal.signal(signal.SIGTTIN, self.signal_handler)
        signal.signal(signal.SIGTTOU, self.signal_handler)
        signal.signal(signal.SIGQUIT, dumpstacks)
        signal.signal(signal.SIGUSR1, log_ormcache_stats)
        signal.signal(signal.SIGUSR2, log_ormcache_stats)

        if config["http_enable"]:
            if config.http_socket_activation:
                self.logger.info(
                    "HTTP service (werkzeug) running through socket activation"
                )
            else:
                self.logger.info(
                    "HTTP service (werkzeug) running on %s:%s",
                    self.interface,
                    self.port,
                )

            if os.environ.get("ODOO_HTTP_SOCKET_FD"):
                # reload
                self.socket = socket.socket(
                    fileno=int(os.environ.pop("ODOO_HTTP_SOCKET_FD"))
                )
            elif config.http_socket_activation:
                # socket activation
                SD_LISTEN_FDS_START = 3
                # Use socket.socket(fileno=) — it detects the family via SO_DOMAIN,
                # correctly wrapping an IPv6 systemd socket as AF_INET6 instead of
                # reinterpreting a sockaddr_in6 as sockaddr_in with garbage fields.
                self.socket = socket.socket(fileno=SD_LISTEN_FDS_START)
            else:
                # default
                family = socket.AF_INET
                if ":" in self.interface:
                    family = socket.AF_INET6
                self.socket = socket.socket(family, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setblocking(0)
                self.socket.bind((self.interface, self.port))
                self.socket.listen(8 * self.population)

    def fork_and_reload(self) -> bool:
        """Fork: parent re-execs the new server; child waits for SIGHUP then shuts down.

        Returns True if the new server signalled readiness (SIGHUP) within the
        timeout, False otherwise. The caller uses this to decide whether the
        old server's workers should be terminated — if the new server never
        came up, shutting them down would leave zero listeners on the port.
        """
        self.logger.info("Reloading server")
        pid = os.fork()
        if pid != 0:
            # keep the http listening socket open during _reexec() to ensure uptime
            http_socket_fileno = self.socket.fileno()
            flags = fcntl.fcntl(http_socket_fileno, fcntl.F_GETFD)
            fcntl.fcntl(http_socket_fileno, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
            os.environ["ODOO_HTTP_SOCKET_FD"] = str(http_socket_fileno)
            os.environ["ODOO_READY_SIGHUP_PID"] = str(pid)
            _reexec()  # stops execution

        # child process handles old server shutdown
        self.logger.info("Waiting for new server to start ...")
        phoenix_hatched = False

        def sighup_handler(sig, frame):
            nonlocal phoenix_hatched
            phoenix_hatched = True

        signal.signal(signal.SIGHUP, sighup_handler)

        # How long the old master waits for the new master to signal readiness.
        # Default 60s; big-DB upgrades / asset rebuilds may need more, via
        # ``ODOO_RELOAD_TIMEOUT``.  Floored at 1s so a "0" can't disable the wait.
        timeout_s = env_float(
            "ODOO_RELOAD_TIMEOUT", 60.0, minimum=1.0, logger=self.logger
        )
        self.logger.info("Reload timeout: %.0fs", timeout_s)

        reload_timeout = time.monotonic() + timeout_s
        while not phoenix_hatched and time.monotonic() < reload_timeout:
            time.sleep(0.1)

        if not phoenix_hatched:
            self.logger.error(
                "Server reload timed out after %.0fs (check the updated code; "
                "set ODOO_RELOAD_TIMEOUT for slower start)",
                timeout_s,
            )
        else:
            self.logger.info("New server has started")
        return phoenix_hatched

    def stop_workers_gracefully(self) -> None:
        """Signal all workers to finish their current request then exit."""
        self.logger.info("Stopping workers gracefully")

        if self.long_polling_pid is not None:
            # FIXME make longpolling process handle SIGTERM correctly
            self.worker_kill(self.long_polling_pid, signal.SIGKILL)
            self.long_polling_pid = None

        # Snapshot the keys with ``list``: ``worker_kill`` may ``worker_pop`` an
        # already-dead worker (ESRCH), mutating ``self.workers`` mid-loop.
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGINT)

        is_main_server = (
            self.pid == os.getpid()
        )  # False if server reload, cannot reap children -> use psutil
        if not is_main_server:
            processes = {}
            # Snapshot here too: ``worker_kill`` above may have popped entries.
            for pid in list(self.workers):
                with contextlib.suppress(psutil.NoSuchProcess):
                    processes[pid] = psutil.Process(pid)

        self.beat = 0.1
        while self.workers:
            try:
                self.process_signals()
            except KeyboardInterrupt:
                self.logger.info("Forced shutdown.")
                break

            if is_main_server:
                self.process_zombie()
            else:
                for pid, proc in list(processes.items()):
                    if not proc.is_running():
                        self.worker_pop(pid)
                        processes.pop(pid)

            self.sleep()
            self.process_timeout()

    def stop(self, graceful: bool = True) -> None:
        if lifecycle.server_phoenix:
            # PreforkServer reloads gracefully, disable outdated mechanism.
            # Write through lifecycle (canonical).
            lifecycle.server_phoenix = False

            if not self.fork_and_reload():
                # New server never signalled readiness within the timeout.  Do
                # NOT kill the old workers — that would leave zero listeners on
                # the port.  End state to be aware of: this process is the old
                # master running as the ``fork_and_reload`` child, so it returns
                # here and then exits via ``run()``'s loop break.  The workers
                # are children of the re-exec'd new master (same PID as the
                # original), so they keep serving under its supervision if it
                # eventually binds the socket; if the new master never came up
                # they are orphaned (reparented to init) until the service
                # manager restarts the unit on the dead MAINPID.
                self.logger.error(
                    "Reload aborted: new server failed to come up within timeout. "
                    "Old workers kept alive; this (old) master is exiting."
                )
                return
            self.stop_workers_gracefully()

            self.logger.info("Old server stopped")
            return

        if self.socket:
            self.socket.close()
        if graceful:
            super().stop()
            self.stop_workers_gracefully()
        else:
            self.logger.info("Stopping forcefully")
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGTERM)

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        """Start the prefork server, optionally stopping after preloading registries."""
        self.start()

        rc = preload_registries(preload)

        if stop:
            self.stop()
            return rc

        # Empty the cursor pool, we dont want them to be shared among forked workers.
        db.close_all()

        ready_pid = os.environ.pop("ODOO_READY_SIGHUP_PID", None)
        if ready_pid:
            # Set by ``fork_and_reload``; a corrupt value or stale PID must not
            # crash the freshly-execed master before it comes up on the socket.
            try:
                os.kill(int(ready_pid), signal.SIGHUP)
            except (ValueError, ProcessLookupError, PermissionError) as e:
                self.logger.warning(
                    "ODOO_READY_SIGHUP_PID=%r could not be signaled: %s. "
                    "Old workers may need to be cleaned up manually.",
                    ready_pid,
                    e,
                )

        self.logger.debug("starting")
        while True:
            try:
                self.process_signals()
                self.process_zombie()
                self.process_timeout()
                self.process_spawn()
                self.sleep()
            except KeyboardInterrupt:
                self.logger.debug("clean stop")
                self.stop()
                break
            except SystemExit:
                raise
            except BaseException as exc:
                self.logger.critical(
                    "Uncaught error in main loop, exiting...", exc_info=exc
                )
                self.stop(False)
                return -1
        return None
