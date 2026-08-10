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

from . import lifecycle
from ._base_server import CommonServer
from ._env import env_float
from ._helpers import empty_pipe
from ._worker import Worker, WorkerCron, WorkerHTTP, WorkerJob
from .lifecycle import _reexec, preload_registries

_logger = logging.getLogger("odoo.service.server")

GRACEFUL_STOP_TIMEOUT_S = 60.0


def _graceful_stop_timeout(logger: logging.Logger) -> float:
    return env_float(
        "ODOO_GRACEFUL_STOP_TIMEOUT",
        GRACEFUL_STOP_TIMEOUT_S,
        minimum=1.0,
        logger=logger,
    )


WORKER_MIN_HEALTHY_LIFETIME_S = 30.0
WORKER_RESPAWN_BACKOFF_CAP_S = 30.0

EVENTED_STOP_TIMEOUT_S = 5.0


class PreforkServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.population = config["workers"]
        self.timeout = (
            config["limit_time_real"] if config["limit_time_real"] > 0 else None
        )
        self.limit_request = config["limit_request"]
        cron_timeout = config["limit_time_real_cron"]
        self.cron_timeout = self.timeout if cron_timeout < 0 else cron_timeout or None
        self.beat = 4
        self.socket = None
        self.workers_http = {}
        self.workers_cron = {}
        self.workers_job = {}
        self.workers = {}
        self._drain_procs: dict[int, psutil.Process] = {}
        self.generation = 0
        self.queue = deque()
        self.long_polling_pid = None
        self.long_polling_popen: subprocess.Popen | None = None
        self.long_polling_spawn_time = 0.0
        self._consecutive_fast_deaths = 0
        self._respawn_not_before = 0.0

    def pipe_new(self) -> tuple[int, int]:
        return os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def _set_socket_cloexec(self) -> None:
        if os.name != "posix":
            return
        fd = self.socket.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFD, flags)

    def pipe_ping(self, pipe: tuple[int, int]) -> None:
        try:
            os.write(pipe[1], b".")
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    def signal_handler(self, sig: int, frame: Any) -> None:
        if sig == signal.SIGCHLD:
            if signal.SIGCHLD not in self.queue:
                self.queue.append(sig)
                self.pipe_ping(self.pipe)
            return
        self.queue.append(sig)
        self.pipe_ping(self.pipe)

    def _close_inherited_pipe_fds_in_child(self, new_worker: Worker) -> None:
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
        for fd in self.pipe:
            if fd not in keep:
                with contextlib.suppress(OSError):
                    os.close(fd)

    def _note_spawn_failure(self) -> None:
        self._consecutive_fast_deaths += 1
        backoff = min(2.0**self._consecutive_fast_deaths, WORKER_RESPAWN_BACKOFF_CAP_S)
        self._respawn_not_before = time.monotonic() + backoff
        self.logger.warning(
            "worker spawn failed before fork (attempt %d); holding respawn for %.0fs",
            self._consecutive_fast_deaths,
            backoff,
        )

    def worker_spawn(self, klass: type, workers_registry: dict) -> Worker | None:
        self.generation += 1
        worker = None
        try:
            worker = klass(self)
            pid = os.fork()
        except OSError:
            if worker is not None:
                worker.close()
            self.logger.debug(
                "worker spawn failed (pipe/fork); skipping, will retry",
                exc_info=True,
            )
            self._note_spawn_failure()
            return None
        if pid != 0:
            worker.pid = pid
            worker.spawn_time = time.monotonic()
            self.workers[pid] = worker
            workers_registry[pid] = worker
            return worker
        else:
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
            os._exit(exit_code)

    def long_polling_spawn(self) -> None:
        nargs = stripped_sys_argv()
        cmd = [sys.executable, sys.argv[0], "evented"] + nargs[1:]
        try:
            popen = subprocess.Popen(cmd)
        except OSError:
            self.logger.debug(
                "long-polling subprocess spawn failed; will retry",
                exc_info=True,
            )
            self._note_spawn_failure()
            return
        self.long_polling_pid = popen.pid
        self.long_polling_popen = popen
        self.long_polling_spawn_time = time.monotonic()

    def _reconcile_long_polling_popen(self, returncode: int | None) -> None:
        popen = self.long_polling_popen
        self.long_polling_popen = None
        if popen is not None and popen.returncode is None:
            popen.returncode = returncode if returncode is not None else -signal.SIGKILL

    def worker_pop(self, pid: int) -> None:
        if pid == self.long_polling_pid:
            self.long_polling_pid = None
        if pid in self.workers:
            self.logger.debug("worker (%s) unregistered", pid)
            self.workers_http.pop(pid, None)
            self.workers_cron.pop(pid, None)
            self.workers_job.pop(pid, None)
            self.workers.pop(pid).close()

    def worker_kill(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
            if sig == signal.SIGKILL:
                self.worker_pop(pid)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self.worker_pop(pid)

    def process_signals(self) -> None:
        while self.queue:
            sig = self.queue.popleft()
            if sig in [signal.SIGINT, signal.SIGTERM]:
                raise KeyboardInterrupt
            if sig == signal.SIGHUP:
                lifecycle.server_phoenix = True
                raise KeyboardInterrupt
            if sig == signal.SIGTTIN:
                self.population += 1
            elif sig == signal.SIGTTOU:
                self.population = max(self.population - 1, 0)

    def process_zombie(self) -> None:
        while True:
            try:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
                self._note_worker_exit(wpid, status)
                self.worker_pop(wpid)
            except OSError as e:
                if e.errno == errno.ECHILD:
                    break
                raise

    def _note_worker_exit(self, pid: int, status: int) -> None:
        if pid == self.long_polling_pid:
            name = "Long-polling (evented) subprocess"
            lifetime = time.monotonic() - self.long_polling_spawn_time
            self._reconcile_long_polling_popen(os.waitstatus_to_exitcode(status))
        else:
            worker = self.workers.get(pid)
            if worker is None:
                return
            name = worker.__class__.__name__
            lifetime = time.monotonic() - getattr(worker, "spawn_time", 0.0)
        if lifetime >= WORKER_MIN_HEALTHY_LIFETIME_S:
            self._consecutive_fast_deaths = 0
            self._respawn_not_before = 0.0
            return
        exited_nonzero = os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0
        crashed_by_signal = (
            os.WIFSIGNALED(status) and os.WTERMSIG(status) != signal.SIGTERM
        )
        if exited_nonzero or crashed_by_signal:
            self._consecutive_fast_deaths += 1
            backoff = min(
                2.0**self._consecutive_fast_deaths, WORKER_RESPAWN_BACKOFF_CAP_S
            )
            self._respawn_not_before = time.monotonic() + backoff
            cause = (
                f"exit {os.WEXITSTATUS(status)}"
                if exited_nonzero
                else f"signal {os.WTERMSIG(status)}"
            )
            self.logger.warning(
                "%s (%s) died after %.1fs (%s); holding respawn for %.0fs "
                "(%d consecutive early crashes)",
                name,
                pid,
                lifetime,
                cause,
                backoff,
                self._consecutive_fast_deaths,
            )

    def process_timeout(self) -> None:
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
        if time.monotonic() < self._respawn_not_before:
            return
        registries = Registry.registries.snapshot

        def check_registries():
            if not registries:
                return
            for db_name, registry in list(registries.items()):
                try:
                    with registry.cursor() as cr:
                        registry.check_signaling(cr)
                except Exception:
                    _logger.warning(
                        "Could not check signaling for database %r during worker "
                        "spawn; skipping this cycle.",
                        db_name,
                        exc_info=True,
                    )
            registries.clear()
            db.close_all()

        if config["http_enable"]:
            while len(self.workers_http) < self.population:
                check_registries()
                if self.worker_spawn(WorkerHTTP, self.workers_http) is None:
                    return
            if not self.long_polling_pid:
                check_registries()
                self.long_polling_spawn()
        while len(self.workers_cron) < config["max_cron_threads"]:
            check_registries()
            if self.worker_spawn(WorkerCron, self.workers_cron) is None:
                return
        while len(self.workers_job) < config["job_workers"]:
            check_registries()
            if self.worker_spawn(WorkerJob, self.workers_job) is None:
                return

    def sleep(self) -> None:
        try:
            fds = {w.watchdog_pipe[0]: w for w in self.workers.values()}
            with selectors.DefaultSelector() as sel:
                for fd in list(fds) + [self.pipe[0]]:
                    sel.register(fd, selectors.EVENT_READ)
                ready = sel.select(self.beat)
            for key, _ in ready:
                fd = key.fileobj
                if fd in fds:
                    fds[fd].watchdog_time = time.monotonic()
                empty_pipe(fd)
        except OSError as e:
            if e.args[0] != errno.EINTR:
                raise

    def start(self) -> None:
        self.pipe = self.pipe_new()
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
                self.socket = socket.socket(
                    fileno=int(os.environ.pop("ODOO_HTTP_SOCKET_FD"))
                )
                self._set_socket_cloexec()
            elif config.http_socket_activation:
                SD_LISTEN_FDS_START = 3
                self.socket = socket.socket(fileno=SD_LISTEN_FDS_START)
                self._set_socket_cloexec()
            else:
                family = socket.AF_INET
                if ":" in self.interface:
                    family = socket.AF_INET6
                self.socket = socket.socket(family, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setblocking(0)
                self.socket.bind((self.interface, self.port))
                self.socket.listen(8 * self.population)

    def fork_and_reload(self) -> bool:
        self.logger.info("Reloading server")
        pid = os.fork()
        if pid != 0:
            if self.socket is not None:
                http_socket_fileno = self.socket.fileno()
                flags = fcntl.fcntl(http_socket_fileno, fcntl.F_GETFD)
                fcntl.fcntl(
                    http_socket_fileno, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC
                )
                os.environ["ODOO_HTTP_SOCKET_FD"] = str(http_socket_fileno)
            os.environ["ODOO_READY_SIGHUP_PID"] = str(pid)
            try:
                super().stop()
            except Exception:
                self.logger.warning(
                    "Exception while running stop hooks before reload", exc_info=True
                )
            _reexec()

        self.logger.info("Waiting for new server to start ...")
        phoenix_hatched = False

        def sighup_handler(sig, frame):
            nonlocal phoenix_hatched
            phoenix_hatched = True

        signal.signal(signal.SIGHUP, sighup_handler)

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

    def _stop_long_polling(self) -> None:
        pid = self.long_polling_pid
        if pid is None:
            return
        self.long_polling_pid = None
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self._reconcile_long_polling_popen(None)
            return
        timeout_s = env_float(
            "ODOO_EVENTED_STOP_TIMEOUT",
            EVENTED_STOP_TIMEOUT_S,
            minimum=0.0,
            logger=self.logger,
        )
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        code: int | None = None
        try:
            code = proc.wait(timeout=timeout_s)
        except psutil.TimeoutExpired:
            self.logger.warning(
                "Evented subprocess (%s) still alive %.0fs after SIGTERM; "
                "sending SIGKILL",
                pid,
                timeout_s,
            )
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(psutil.TimeoutExpired):
                code = proc.wait(timeout=5)
        finally:
            self._reconcile_long_polling_popen(code)

    def stop_workers_gracefully(self) -> None:
        self.logger.info("Stopping workers gracefully")

        self._stop_long_polling()

        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGINT)

        is_main_server = self.pid == os.getpid()
        processes = {}
        if not is_main_server:
            for pid in list(self.workers):
                with contextlib.suppress(psutil.NoSuchProcess):
                    processes[pid] = psutil.Process(pid)
        self._drain_procs = processes

        self.beat = 0.1
        phoenix_decided = lifecycle.server_phoenix
        stop_timeout = _graceful_stop_timeout(self.logger)
        deadline = time.monotonic() + stop_timeout
        escalated = False
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

            if not escalated and time.monotonic() >= deadline:
                escalated = True
                self.logger.warning(
                    "Workers still alive %.0fs after SIGINT; escalating to SIGKILL: %s",
                    stop_timeout,
                    list(self.workers),
                )
                for pid in list(self.workers):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)

            self.sleep()
            self.process_timeout()

        lifecycle.server_phoenix = phoenix_decided

    def _sweep_stale_workers(self) -> None:
        for pid in list(self.workers):
            proc = self._drain_procs.get(pid)
            if proc is None or not proc.is_running():
                self.worker_pop(pid)
                continue
            self.worker_kill(pid, signal.SIGTERM)

    def stop(self, graceful: bool = True) -> None:
        if lifecycle.server_phoenix:
            lifecycle.server_phoenix = False

            try:
                if not self.fork_and_reload():
                    self.logger.error(
                        "Reload aborted: new server failed to come up within "
                        "timeout. Old workers kept alive; this (old) master is "
                        "exiting."
                    )
                    return
                self.stop_workers_gracefully()
                self._sweep_stale_workers()

                self.logger.info("Old server stopped")
                return
            finally:
                super().stop()

        if self.socket:
            self.socket.close()
        if graceful:
            super().stop()
            self.stop_workers_gracefully()
        else:
            self.logger.info("Stopping forcefully")
            self._stop_long_polling()
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGTERM)

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        self.start()

        rc = preload_registries(preload)

        if stop:
            self.stop()
            return rc

        db.close_all()

        ready_pid = os.environ.pop("ODOO_READY_SIGHUP_PID", None)
        if ready_pid:
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
