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
from ._base_server import CommonServer
from ._env import env_float
from ._helpers import empty_pipe
from ._worker import Worker, WorkerCron, WorkerHTTP, WorkerJob
from .lifecycle import _reexec, preload_registries

_logger = logging.getLogger("odoo.service.server")

# Default deadline (seconds) for a graceful worker shutdown: after SIGINT is
# sent, workers get this long to finish their current request and exit before
# the master escalates to SIGKILL.  Without a hard ceiling a worker that ignores
# SIGINT (wedged / uninterruptible) and has no watchdog (``limit_time_real <= 0``
# -> ``watchdog_timeout is None``, so ``process_timeout`` never fires) spins the
# graceful-stop loop forever, hanging both shutdown and reload.  Overridable via
# ``ODOO_GRACEFUL_STOP_TIMEOUT`` (see ``_graceful_stop_timeout``): a deployment
# that allows long requests (``limit_time_real`` > 60) would otherwise have this
# ceiling cut them short on every reload.  Align it with the service manager's
# own stop timeout (systemd ``TimeoutStopSec``) when raising it.
GRACEFUL_STOP_TIMEOUT_S = 60.0


def _graceful_stop_timeout(logger: logging.Logger) -> float:
    """Resolve the graceful-stop SIGKILL deadline, honouring the env override.

    Read at stop time (not import time) so a unit-file ``Environment=`` edit
    takes effect on the next reload without a code change.  Floored at 1 s so
    a "0" cannot disable the escalation and reintroduce the infinite drain
    loop the ceiling exists to prevent.
    """
    return env_float(
        "ODOO_GRACEFUL_STOP_TIMEOUT",
        GRACEFUL_STOP_TIMEOUT_S,
        minimum=1.0,
        logger=logger,
    )


# Fork-storm throttle.  A worker that raises before serving real work dies
# immediately, and the master otherwise refills its slot every main-loop
# iteration with no delay — a dying child's SIGCHLD wakes ``sleep`` at once, so
# the respawn rate is bounded only by fork+crash+reap latency (measured at
# ~900 forks/s), a CPU-pinning storm plus log flood.  A worker that survives at
# least ``WORKER_MIN_HEALTHY_LIFETIME_S`` counts as a successful boot and clears
# the throttle; consecutive early crashes grow a ``2 ** n`` respawn backoff,
# capped at ``WORKER_RESPAWN_BACKOFF_CAP_S``, during which ``process_spawn``
# holds off refilling slots.
WORKER_MIN_HEALTHY_LIFETIME_S = 30.0
WORKER_RESPAWN_BACKOFF_CAP_S = 30.0


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
        # ``limit_time_real <= 0`` means "no real-time watchdog": a 0 or negative
        # value would make every HTTP worker's ``watchdog_timeout`` non-positive,
        # so ``process_timeout`` would SIGKILL brand-new workers at once and the
        # master would respawn them in a loop. ``or None`` only caught 0, so a
        # negative slipped through; gate on ``> 0`` to match the intent.
        self.timeout = (
            config["limit_time_real"] if config["limit_time_real"] > 0 else None
        )
        self.limit_request = config["limit_request"]
        self.cron_timeout = config["limit_time_real_cron"] or None
        if self.cron_timeout == -1:
            self.cron_timeout = self.timeout
        # working vars
        self.beat = 4
        self.socket = None
        self.workers_http = {}
        self.workers_cron = {}
        self.workers_job = {}
        self.workers = {}
        # Worker spawns over this server's lifetime (logs/diagnostics only).
        self.generation = 0
        self.queue = deque()
        self.long_polling_pid = None
        self.long_polling_spawn_time = 0.0  # for the fork-storm throttle
        # Fork-storm throttle (see the WORKER_* constants and process_spawn):
        # consecutive early worker crashes push an exponential respawn backoff.
        self._consecutive_fast_deaths = 0
        self._respawn_not_before = 0.0  # monotonic deadline; 0.0 => spawn freely

    def pipe_new(self) -> tuple[int, int]:
        """Create a new non-blocking, close-on-exec pipe pair."""
        return os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def _set_socket_cloexec(self) -> None:
        """Set FD_CLOEXEC on ``self.socket`` (POSIX only; no-op elsewhere).

        Used for the reload- and socket-activation-inherited listen sockets,
        which arrive without CLOEXEC; the default bind path gets it for free
        (Python sockets are CLOEXEC by default).
        """
        if os.name != "posix":
            return
        fd = self.socket.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFD, flags)

    def pipe_ping(self, pipe: tuple[int, int]) -> None:
        """Write a single byte to the write end of a pipe to wake the master."""
        try:
            os.write(pipe[1], b".")
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    def signal_handler(self, sig: int, frame: Any) -> None:
        # SIGCHLD is coalesced by the kernel; one pending SIGCHLD drives a
        # full ``waitpid(-1, WNOHANG)`` loop in ``process_zombie``, so a
        # single slot is enough regardless of how many children died.
        if sig == signal.SIGCHLD:
            if signal.SIGCHLD not in self.queue:
                self.queue.append(sig)
                self.pipe_ping(self.pipe)
            return
        # Every other signal routed here (SIGINT/SIGTERM/SIGHUP/SIGTTIN/
        # SIGTTOU — see ``start()``; SIGQUIT/SIGUSR1/SIGUSR2 bypass the queue)
        # is an operator control signal and must never be dropped.  The
        # historical queue cap existed to survive SIGCHLD storms, which the
        # single-slot dedup above already absorbs, so no cap is needed.
        self.queue.append(sig)
        self.pipe_ping(self.pipe)

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
        try:
            pid = os.fork()
        except OSError:
            # ``fork()`` can fail transiently (EAGAIN from RLIMIT_NPROC, ENOMEM).
            # Letting it propagate reaches ``run()``'s catch-all, which stops the
            # master — a momentary resource spike would permanently kill the
            # supervisor.  Release the pipe fds this worker just allocated, log,
            # and return None so ``process_spawn`` skips the refill and the next
            # main-loop iteration retries.
            worker.close()
            self.logger.exception("fork() failed; skipping spawn, will retry")
            return None
        if pid != 0:
            worker.pid = pid
            worker.spawn_time = time.monotonic()  # for the fork-storm throttle
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
        """Spawn the evented long-polling subprocess.

        A transient ``subprocess.Popen`` failure (``OSError`` — EAGAIN from
        RLIMIT_NPROC, ENOMEM, a fork/exec hiccup) must NOT propagate: it would
        reach ``run()``'s catch-all, which stops the master — permanently
        killing the supervisor over a momentary resource spike.  This is the
        same failure mode ``worker_spawn`` guards its ``os.fork()`` against, and
        long-polling was the one spawn path still unprotected.  Leave
        ``long_polling_pid`` unset so the next ``process_spawn`` iteration
        retries once the pressure clears.
        """
        nargs = stripped_sys_argv()
        cmd = [sys.executable, sys.argv[0], "evented"] + nargs[1:]
        try:
            popen = subprocess.Popen(cmd)
        except OSError:
            self.logger.exception(
                "long-polling subprocess spawn failed; will retry next cycle"
            )
            return
        self.long_polling_pid = popen.pid
        self.long_polling_spawn_time = time.monotonic()  # fork-storm throttle

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
            self.workers_job.pop(pid, None)
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
        """Feed a reaped worker's exit into the fork-storm respawn throttle.

        Only an *unexpected, early* death arms the backoff.  A worker that lived
        at least ``WORKER_MIN_HEALTHY_LIFETIME_S`` (a successful boot) clears the
        throttle.  An early death arms it in two cases:

        * a non-zero ``exit`` code (``WIFEXITED``), or
        * a fatal *signal* (``WIFSIGNALED``) other than ``SIGTERM`` — a native
          segfault (``SIGSEGV``), ``SIGABRT`` from a C extension, or a cgroup
          OOM-kill / manual ``kill -9`` (both ``SIGKILL``).  Without this, a
          crash-on-boot storm that dies by signal (rather than a Python
          ``sys.exit(1)``) would refill its slot every main-loop iteration
          undetected.

        Only ``SIGTERM`` is excluded, and only defensively: the master sends it
        to workers exclusively during shutdown (``stop()``), never in the
        ``run()`` loop where the throttle is consulted.  ``SIGKILL`` is NOT
        excluded — a *master-initiated* watchdog SIGKILL (``process_timeout`` ->
        ``worker_kill``) ``worker_pop``s the worker before it is reaped, so it
        bails at the ``worker is None`` check above and never arms.  Any SIGKILL
        that DOES reach here with the worker still registered is therefore
        external (the cgroup OOM-killer and ``kill -9`` both use signal 9) —
        exactly the young-crash storm the throttle exists to damp, and the most
        common early-death cause under a too-tight ``MemoryMax=``.  (The
        graceful-stop escalation also raw-SIGKILLs registered workers, but it
        runs outside ``run()``'s loop, so arming ``_respawn_not_before`` there
        is simply never read.)  A young *clean* exit (``exit 0`` recycle)
        neither arms nor clears: it is not a crash, but a single healthy recycle
        should not reset a genuine crash streak.

        The long-polling (evented) subprocess feeds the same throttle: it has
        no other backoff, so without this a crash-on-boot evented child (e.g.
        ``gevent_port`` already bound) would be exec'd again every main-loop
        cycle forever — a slower storm than a worker fork (each cycle pays a
        full interpreter boot) but the same log flood and CPU burn.  Its EXPECTED
        recycle (the ``EventServer`` watchdog SIGTERMs itself on the memory
        soft-limit) exits gracefully with code 0, which — like a worker's clean
        recycle — neither arms nor clears.  Other non-worker pids (an
        already-popped entry) are ignored.
        """
        if pid == self.long_polling_pid:
            name = "Long-polling (evented) subprocess"
            lifetime = time.monotonic() - self.long_polling_spawn_time
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
        # Fork-storm throttle: while a respawn backoff is active (a worker just
        # crashed young), skip refilling slots this cycle.  The main loop keeps
        # turning, so spawning resumes automatically once the deadline passes.
        if time.monotonic() < self._respawn_not_before:
            return
        # Before spawning any process, check the registry signaling
        registries = Registry.registries.snapshot

        def check_registries():
            # check the registries on the first call only!
            if not registries:
                return
            for db_name, registry in list(registries.items()):
                try:
                    with registry.cursor() as cr:
                        registry.check_signaling(cr)
                except Exception:
                    # A transient PG outage (or an externally-dropped database)
                    # at worker-respawn time must NOT take down the whole
                    # supervisor: registry.cursor() -> pool.borrow can raise
                    # PoolError, which would otherwise propagate to run()'s
                    # catch-all and stop the master permanently.  Freshly forked
                    # workers re-check signaling themselves, so log and continue.
                    _logger.warning(
                        "Could not check signaling for database %r during worker "
                        "spawn; skipping this cycle.",
                        db_name,
                        exc_info=True,
                    )
            registries.clear()
            # Close all opened cursors
            db.close_all()

        if config["http_enable"]:
            while len(self.workers_http) < self.population:
                check_registries()
                # ``worker_spawn`` returns None on a transient ``fork()`` failure
                # without adding to the registry; break so this loop can't spin
                # (len unchanged) — the next main-loop iteration retries.
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
                # ``fork_and_reload`` cleared FD_CLOEXEC so the fd survived
                # execve into this new master; re-set it now so the bound listen
                # socket does not leak into future exec'd subprocesses (any that
                # forgo ``close_fds`` would inherit the port).
                self._set_socket_cloexec()
            elif config.http_socket_activation:
                # socket activation
                SD_LISTEN_FDS_START = 3
                # Use socket.socket(fileno=) — it detects the family via SO_DOMAIN,
                # correctly wrapping an IPv6 systemd socket as AF_INET6 instead of
                # reinterpreting a sockaddr_in6 as sockaddr_in with garbage fields.
                self.socket = socket.socket(fileno=SD_LISTEN_FDS_START)
                # systemd passes the activation fd without FD_CLOEXEC; set it so
                # the socket is not inherited by exec'd subprocesses.
                self._set_socket_cloexec()
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
        # After the graceful-stop timeout the master force-kills any survivor so
        # a worker that ignores SIGINT with no watchdog can't hang this loop.
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
                # Raw SIGKILL, not ``worker_kill`` (which pops the worker before
                # the child is reaped): keep each worker registered so the next
                # ``process_zombie`` / psutil pass reaps and pops it, draining the
                # loop cleanly with no lingering zombie.  SIGKILL is uncatchable,
                # so the survivors die and the loop terminates on the next tick.
                for pid in list(self.workers):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)

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
