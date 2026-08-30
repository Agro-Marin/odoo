from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import psutil

if os.name == "posix":
    import fcntl

from odoo import db
from odoo.modules.registry import Registry
from odoo.tools import config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks, stripped_sys_argv

from . import _process_state
from ._base_server import CommonServer
from ._env import _IS_POSIX, env_float
from ._limits import cron_real_time_budget, empty_pipe, job_real_time_budget
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

CENSUS_WRITE_INTERVAL_S = 4.0
"""How often the master rewrites its census.  Matches the default beat."""

CENSUS_MAX_AGE_S = 60.0
"""Older than this and the census is not answered from; see `_read_census`."""


class PreforkServer(CommonServer):
    flavor = "prefork"

    def metrics(self) -> dict[str, Any]:
        """The master's own counts, answered from either side of the fork.

        `/web/metrics` is an HTTP route, so under prefork it is ALWAYS served
        by a worker child -- and a child cannot count its siblings.  This
        method used to return `{}` there, which meant the four metrics that
        exist to describe prefork (`odoo_workers`, `odoo_worker_population`,
        `odoo_worker_generation`, `odoo_long_polling_alive`) were declared by
        `render_prometheus` and could never be emitted by the only server
        flavour that has them.  Measured before the census existed: threaded
        exposed four flavour metrics, prefork exposed none.

        So the master writes what only it knows, and the child reads it.
        """
        if os.getpid() != self.pid:
            return self._read_census()
        return self._census()

    def _census(self) -> dict[str, Any]:
        return {
            "workers": {
                "http": len(self.workers_http),
                "cron": len(self.workers_cron),
                "job": len(self.workers_job),
            },
            "worker_population": self.population,
            "worker_generation": self.generation,
            "long_polling_alive": self.long_polling_pid is not None,
        }

    def _census_path(self) -> Path | None:
        """Both sides derive this from the MASTER's pid.

        `self.pid` is assigned in `CommonServer.__init__`, which runs in the
        master, so a forked child carries the master's pid here while its own
        `os.getpid()` differs.  That difference is what `metrics()` branches
        on, and it is also what lets the child name the file without being
        told where it is.
        """
        try:
            return Path(config["data_dir"]) / f"prefork-census-{self.pid}.json"
        except Exception:
            return None

    def _publish_census(self) -> None:
        """Best-effort by construction: a failure leaves the metrics absent.

        Absent is exactly what they were before this existed, so nothing here
        is allowed to raise into the master's run loop.  Written at most every
        `CENSUS_WRITE_INTERVAL_S`; `stop_workers_gracefully` drops the beat to
        0.1s and must not turn that into ten writes a second.
        """
        try:
            now = time.monotonic()
            if now - self._census_written_at < CENSUS_WRITE_INTERVAL_S:
                return
            self._census_written_at = now
            path = self._census_path()
            if path is None:
                return
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            try:
                tmp.write_text(json.dumps(self._census()))
                tmp.replace(path)
            except Exception:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
        except Exception:
            self.logger.debug("Could not publish the worker census", exc_info=True)

    def _read_census(self) -> dict[str, Any]:
        """A stale census is no census.

        The file outlives a master that was killed rather than stopped, and
        reporting its last counts as current would be worse than reporting
        nothing -- a dashboard would show a full complement of workers for a
        server that is gone.  `CENSUS_MAX_AGE_S` is many multiples of the
        write interval, so a live master is never mistaken for a dead one.
        """
        path = self._census_path()
        if path is None:
            return {}
        try:
            if time.time() - path.stat().st_mtime > CENSUS_MAX_AGE_S:
                return {}
            payload = json.loads(path.read_text())
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _discard_census(self) -> None:
        path = self._census_path()
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink()

    def _sweep_stale_censuses(self) -> None:
        """Collect what a master that was KILLED rather than stopped left behind.

        `_discard_census` only runs on the way out of `stop()`, so a SIGKILLed
        master leaves its file for a pid that will never write again.  The age
        guard in `_read_census` already makes such a file harmless, but
        without this it also makes it permanent -- one more piece of litter in
        `data_dir` per hard kill.  Swept at startup, when there is nothing to
        race with and the cost is one listdir.

        Our own file is not a candidate: it is named for OUR pid and does not
        exist yet at `start()`.
        """
        path = self._census_path()
        if path is None:
            return
        cutoff = time.time() - CENSUS_MAX_AGE_S
        try:
            for stale in path.parent.glob("prefork-census-*.json"):
                if stale != path and stale.stat().st_mtime < cutoff:
                    with contextlib.suppress(OSError):
                        stale.unlink()
        except Exception:
            self.logger.debug("Could not sweep stale censuses", exc_info=True)

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.population = config["workers"]
        self.timeout = (
            config["limit_time_real"] if config["limit_time_real"] > 0 else None
        )
        self.limit_request = config["limit_request"]
        self.cron_timeout = cron_real_time_budget() or None
        self.job_timeout = job_real_time_budget() or None
        self.beat: float = 4
        self.socket: socket.socket | None = None
        self.workers_http: dict[int, WorkerHTTP] = {}
        self.workers_cron: dict[int, WorkerCron] = {}
        self.workers_job: dict[int, WorkerJob] = {}
        self.workers: dict[int, Worker] = {}
        self._drain_procs: dict[int, psutil.Process] = {}
        self._killed_workers: dict[int, Worker] = {}
        self.generation = 0
        self.queue: deque[int] = deque()
        self.long_polling_pid: int | None = None
        self.long_polling_popen: subprocess.Popen | None = None
        self.long_polling_spawn_time = 0.0
        self._consecutive_fast_deaths = 0
        self._respawn_not_before = 0.0
        self._selector: selectors.BaseSelector | None = None
        self._watched: dict[int, Worker] = {}
        self._census_written_at = float("-inf")

    def pipe_new(self) -> tuple[int, int]:
        return os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def _set_socket_cloexec(self) -> None:
        if not _IS_POSIX or self.socket is None:
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
        self._close_watchdog_selector()

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

    def _remember_killed(self, pid: int) -> None:
        """Keep a killed worker reachable for `_note_worker_exit` after the pop.

        `worker_pop` drops it from `self.workers` so the watchdog does not kill
        the same pid twice and its pipes close promptly.  But the exit is only
        *accounted* for later, when `process_zombie` reaps it -- and
        `_note_worker_exit` looks the worker up in `self.workers` to learn how
        long it lived.  Popping first therefore made that lookup fail and the
        function return before doing anything, which took the whole crash
        branch with it: no "died after Xs" line, and no back-off.

        That branch is written for exactly this case -- `crashed_by_signal`
        excludes SIGTERM, the graceful stop, and nothing else, so SIGKILL is
        the signal it means -- and the watchdog is the only thing that sends
        SIGKILL.  It was unreachable by construction.  Measured: a worker the
        watchdog killed left `_consecutive_fast_deaths` at 0, where a worker
        that exited on its own took it to 1 and armed the back-off.

        Entries leave on the next reap.  The one path that pops without
        reaping is the drain child in `stop_workers_gracefully`, which is
        bounded by the worker count and about to exit.
        """
        worker = self.workers.get(pid)
        if worker is not None:
            self._killed_workers[pid] = worker

    def worker_kill(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
            if sig == signal.SIGKILL:
                self._remember_killed(pid)
                self.worker_pop(pid)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self._remember_killed(pid)
                self.worker_pop(pid)

    def process_signals(self) -> None:
        while self.queue:
            sig = self.queue.popleft()
            if sig in [signal.SIGINT, signal.SIGTERM]:
                raise KeyboardInterrupt
            if sig == signal.SIGHUP:
                _process_state.set_phoenix(True)
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
            worker = self.workers.get(pid) or self._killed_workers.pop(pid, None)
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
        checked = False

        def check_registries():
            nonlocal checked
            if checked or not registries:
                return
            checked = True
            for db_name, registry in registries.items():
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

    def _close_watchdog_selector(self) -> None:
        sel, self._selector = getattr(self, "_selector", None), None
        self._watched = {}
        if sel is not None:
            with contextlib.suppress(Exception):
                sel.close()

    def _watchdog_selector(self) -> tuple[selectors.BaseSelector, dict[int, Worker]]:
        """Keep one epoll instance and re-register only what actually moved.

        The watched set changes only when a worker is spawned or reaped, but
        this runs once per beat -- and `stop_workers_gracefully` drops the beat
        to 0.1s, so rebuilding it here meant creating and tearing down an epoll
        instance ten times a second through the whole shutdown.

        What moved is decided per OWNER, not per fd number.  `worker_pop`
        closes a reaped worker's pipe, and the very next `pipe_new()` hands
        the lowest free descriptors straight back -- so the replacement worker
        arrives on the *same fd number* the dead one had.  Diffing fd numbers
        alone sees no change and skips the re-register, leaving the selector's
        map claiming a descriptor that epoll dropped when it was closed.  The
        new worker is then never selected on, its `watchdog_time` never
        advances, and `process_timeout` SIGKILLs it one `limit_time_real`
        later -- every replacement, forever, while it sits idle.
        """
        fds = {w.watchdog_pipe[0]: w for w in self.workers.values()}
        sel = getattr(self, "_selector", None)
        if sel is None:
            sel = self._selector = selectors.DefaultSelector()
            self._watched = {}
        watched = self._watched
        for fd, owner in list(watched.items()):
            if fds.get(fd) is owner:
                continue
            del watched[fd]
            with contextlib.suppress(KeyError, ValueError, OSError):
                sel.unregister(fd)
        for fd, owner in fds.items():
            if fd in watched:
                continue
            with contextlib.suppress(KeyError, ValueError, OSError):
                sel.register(fd, selectors.EVENT_READ)
                watched[fd] = owner
        if self.pipe[0] not in sel.get_map():
            with contextlib.suppress(KeyError, ValueError, OSError):
                sel.register(self.pipe[0], selectors.EVENT_READ)
        return sel, fds

    def sleep(self) -> None:
        sel, fds = self._watchdog_selector()
        ready = sel.select(self.beat)
        for key, _ in ready:
            fd = key.fd
            if fd in fds:
                fds[fd].watchdog_time = time.monotonic()
            empty_pipe(fd)

    def start(self) -> None:
        self.pipe = self.pipe_new()
        self._sweep_stale_censuses()
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
            # Say which of the three it actually was, AFTER doing it.  The
            # message used to be chosen before this branch ran, so a master
            # that had just inherited a listening socket across a SIGHUP
            # reload announced "running on <interface>:<port>" -- the wording
            # for a fresh bind, which is the one thing it had not done.  On a
            # live reload that is the only line an operator gets, and it says
            # the port was rebound when it never closed.
            inherited_fd = os.environ.pop("ODOO_HTTP_SOCKET_FD", None)
            if inherited_fd:
                self.socket = socket.socket(fileno=int(inherited_fd))
                self._set_socket_cloexec()
                self.logger.info(
                    "HTTP service (werkzeug) serving %s:%s on the listening "
                    "socket inherited from the server this one replaced; the "
                    "port was never closed",
                    self.interface,
                    self.port,
                )
            elif config.http_socket_activation:
                SD_LISTEN_FDS_START = 3
                self.socket = socket.socket(fileno=SD_LISTEN_FDS_START)
                self._set_socket_cloexec()
                self.logger.info(
                    "HTTP service (werkzeug) running through socket activation"
                )
            else:
                family = socket.AF_INET
                if ":" in self.interface:
                    family = socket.AF_INET6
                self.socket = socket.socket(family, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setblocking(False)
                self.socket.bind((self.interface, self.port))
                self.socket.listen(8 * self.population)
                self.logger.info(
                    "HTTP service (werkzeug) running on %s:%s",
                    self.interface,
                    self.port,
                )

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
        phoenix_decided = _process_state.server_phoenix
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

        _process_state.set_phoenix(phoenix_decided)

    def _sweep_stale_workers(self) -> None:
        for pid in list(self.workers):
            proc = self._drain_procs.get(pid)
            if proc is None or not proc.is_running():
                self.worker_pop(pid)
                continue
            self.worker_kill(pid, signal.SIGTERM)

    def stop(self, graceful: bool = True) -> None:
        if _process_state.server_phoenix:
            _process_state.set_phoenix(False)

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
        # The on_stop hooks run on every other path, and a crash is when a
        # flush hook matters most -- so the forceful path runs them too, just
        # defensively: one raising hook must not keep the workers alive.
        try:
            super().stop()
        except Exception:
            self.logger.warning("Exception while running stop hooks", exc_info=True)
        if graceful:
            self.stop_workers_gracefully()
        else:
            self.logger.info("Stopping forcefully")
            self._stop_long_polling()
        for pid in list(self.workers):
            self.worker_kill(pid, signal.SIGTERM)
        self._close_watchdog_selector()
        self._discard_census()

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
                self._publish_census()
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
