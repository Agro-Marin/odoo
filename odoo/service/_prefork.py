"""Prefork (multiprocess) server — extracted from ``server.py``.

``PreforkServer`` (aka Multicorn) forks one ``Worker`` child per HTTP/cron
slot (the ``Worker`` classes live in ``_worker.py``) and supervises them from
a signal-driven master loop.  Subclasses ``CommonServer`` (``_base_server.py``);
``server.py`` re-exports ``PreforkServer`` for backward compatibility.
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
    dispatcher to will parse the first HTTP request line.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        # config
        self.population = config["workers"]
        # ``limit_time_real <= 0`` means "no real-time watchdog" — same as the
        # ``or None`` the cron line below uses.  Without it, a 0 makes every
        # HTTP worker's ``watchdog_timeout`` 0, so ``process_timeout`` SIGKILLs
        # brand-new workers immediately (``now - watchdog_time >= 0``) and the
        # master respawns them in a loop.
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
        # Monotonic counter of worker spawns over this server's lifetime.
        # Currently only used in logs/diagnostics; kept as ``int`` (unbounded
        # in Python) so no rollover concern.  Not reset on reload.
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

    #: Control signals must never be dropped — if the queue is full of
    #: SIGCHLD storms from dying workers, an operator still needs SIGINT /
    #: SIGTERM / SIGHUP to get through. SIGTTIN / SIGTTOU reshape the worker
    #: pool and are also load-bearing, so they share the whitelist.
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

        ``os.pipe2(O_CLOEXEC)`` only closes on ``execve`` — after a bare
        ``fork`` the child still holds every fd the parent had open, including
        the ``watchdog_pipe`` / ``eintr_pipe`` of every existing sibling
        worker plus the parent's own master wakeup pipe. Left alone, those
        fds stay open for the full lifetime of the child: with N=8 workers
        that's 4*7 + 2 = 30 leaked descriptors per child, compounding under
        reload. Close them explicitly here, except for the new worker's own
        pipes which it still needs.
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
            # Detach from the master's queueing signal handler BEFORE we
            # close the master's pipe fds.  Without this, a signal arriving
            # in the child during the window between
            # ``_close_inherited_pipe_fds_in_child`` and Worker.start's own
            # ``signal.signal(...)`` calls would run the inherited
            # ``master.signal_handler`` in the child, hit
            # ``self.pipe_ping(self.pipe)`` against now-closed fds, raise
            # ``OSError(EBADF)`` (not in the ``pipe_ping`` allowlist of
            # EAGAIN/EINTR), and propagate out of bytecode dispatch —
            # observable as a sporadic worker death under
            # ``stop_workers_gracefully`` storms.
            #
            # Termination signals → SIG_DFL: if SIGINT/SIGTERM/SIGHUP
            # arrives mid-startup, terminating the half-initialised worker
            # is the right outcome (the master will respawn).
            # Ignored signals → SIG_IGN: SIGCHLD (workers don't fork),
            # SIGTTIN/SIGTTOU (workers don't read from TTY; the SIG_DFL
            # default for these is *Stop*, which would silently suspend the
            # worker if an operator's SIGTTOU to the master leaked to the
            # child — strictly worse than ignoring it).
            # Worker.start re-installs the worker-side handlers a few
            # microseconds later.
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
            # ``os._exit`` (not ``sys.exit``): the latter runs atexit handlers
            # and flushes stdio, but after fork those file objects share OS
            # fds with the parent — flushing in the child can double-write
            # log lines or trip cleanup destructors that aren't fork-safe
            # (psycopg pool, logging.shutdown, etc.).  Bypass them all.
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

        Only signals routed through ``self.signal_handler`` (the queueing
        path) reach this method.  ``SIGQUIT`` is bound directly to
        ``dumpstacks`` and ``SIGUSR1``/``SIGUSR2`` directly to
        ``log_ormcache_stats`` in ``start()`` — those run in the signal
        handler context and never enter the queue, so previous branches
        for them here were unreachable and have been removed.  ``SIGCHLD``
        is enqueued to wake the master from ``sleep`` but the actual
        reaping happens in ``process_zombie``; popping it here is a no-op
        on purpose (no branch needed).
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
                # operator cannot drive population negative (which silently
                # stops the spawn loop from ever entering — the server would
                # drain to zero workers and refuse new connections).
                self.population = max(self.population - 1, 0)

    def process_zombie(self) -> None:
        """Reap dead workers via ``waitpid(-1, WNOHANG)``.

        The historical ``if (status >> 8) == 3`` branch (an ad-hoc sentinel
        for "worker died unrecoverably") was removed: no path in the fork
        produces exit code 3, the only commit that touched the line was the
        2014 ``openerp`` → ``odoo`` rename, and the comparison was incorrect
        for signal-killed workers (``status >> 8`` is the exit byte for
        normal exits but undefined when ``WIFSIGNALED``).  If a future
        scenario ever needs a "death" signal, use
        ``os.waitstatus_to_exitcode(status)`` which handles both cases.
        """
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
        60-second timeout, False otherwise. The caller uses this to decide
        whether the old server's workers should be terminated — if the new
        server never came up, shutting down the workers leaves zero servers
        listening on the port.
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

        # Reload timeout: how long the old master waits for the new master
        # to signal readiness before giving up.  Default 60s suits most
        # installs, but big-DB upgrades and asset rebuilds can exceed it.
        # Override via ``ODOO_RELOAD_TIMEOUT`` env var.  Float for sub-second
        # tests; clamped to ≥1s to prevent typos like "0" silently disabling
        # the wait.
        # ``env_float`` warns (under this server's logger) and falls back to
        # 60s on a malformed value, and clamps a sub-floor value up to 1s.
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

        # Signal workers to finish their current workload then stop.
        # ``list(self.workers)`` snapshots the keys: ``worker_kill`` may call
        # ``worker_pop`` (on ESRCH for an already-dead worker) which mutates
        # ``self.workers`` mid-loop and would otherwise raise
        # "dictionary changed size during iteration".  Same fix as the SIGTERM
        # path below; the SIGINT path was missed in the original cleanup.
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGINT)

        is_main_server = (
            self.pid == os.getpid()
        )  # False if server reload, cannot reap children -> use psutil
        if not is_main_server:
            processes = {}
            # Snapshot here too: worker_kill above may have already popped
            # entries, and even if it didn't, defensive snapshotting matches
            # the rest of this class.
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
                # New server never signalled readiness; keep the old workers
                # serving rather than leaving zero listeners on the port.
                self.logger.error(
                    "Reload aborted: new server failed to come up within timeout. "
                    "Keeping old workers alive."
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
            # The env var is set by ``fork_and_reload`` and consumed once;
            # a corrupted value (non-integer) or a stale PID (the child
            # waiting for SIGHUP died before re-exec) would otherwise
            # crash the freshly-execed master with a stack trace instead
            # of letting it come up on the listening socket.
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
                # _logger.debug("Multiprocess beat (%s)",time.time())
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
