"""Prefork worker classes — extracted from ``server.py``.

The fork's ``PreforkServer`` (in ``server.py``) instantiates one of the
``Worker`` subclasses per child process.  Workers reference the master
through their ``multi`` attribute (typed as ``PreforkServer`` via
``TYPE_CHECKING`` to avoid a runtime import cycle), and pull the small
process-control helpers (``memory_info``, ``set_limit_memory_hard``,
``empty_pipe``, ``cron_database_list``) from ``_helpers.py`` — a
shared sibling of both this module and ``server.py``.  Putting the
helpers in a third module breaks the prior server <-> _worker
circular import.

What lives here:

* ``CpuTimeLimitExceeded`` — typed exception so SIGXCPU produces a
  log-distinguishable failure mode.
* ``Worker`` — base class with the common signal handling, watchdog
  pipe wiring, RUSAGE_CPU update, and process-cycle ``run`` /
  ``_runloop``.
* ``WorkerHTTP`` — accept-and-serve HTTP requests on the listening
  socket, with the ``ODOO_HTTP_SOCKET_TIMEOUT`` clamp.
* ``WorkerCron`` — LISTEN/NOTIFY-driven cron processing with the
  reconnect-with-backoff path (post H-1/H-2 + Finding C).

Tests: ``tests/service/test_server.py`` — the ``TestWorker*`` and
``TestWorkerCron*`` classes cover ``check_limits``, ``_connect_postgres``,
``process_work`` reconnect, queue scheduling, age limit, and the
``Worker._process_handle`` psutil caching.  Patches in those tests
target ``odoo.service._worker.X`` (this module's namespace) for any
name resolved inside a ``Worker`` / ``WorkerCron`` method body.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import random
import selectors
import signal
import socket
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import psutil
import psycopg

if os.name == "posix":
    # Unix only for workers
    import fcntl
    import resource

# Optional process names for workers
try:
    from setproctitle import setproctitle
except ImportError:

    def setproctitle(x: str) -> None:
        return None


from odoo import db
from odoo.db import PoolError
from odoo.modules.registry import Registry
from odoo.tools import OrderedSet, config

# Process-control helpers and cron timing constants live in ``_helpers``
# (extracted to break the prior server.py <-> _worker.py circular import:
# workers needed these names but they sat above the ``from ._worker import``
# line in server.py, making the partial-module-load load-bearing).  Now
# the dependency flows downward (``_worker → _helpers → db``) without
# looping back through ``server``.
from ._helpers import (
    CRON_NOTIFY_JITTER_MAX_S,
    SLEEP_INTERVAL,
    cron_database_list,
    empty_pipe,
    memory_info,
)

# ``BaseWSGIServerNoBind`` is the no-bind werkzeug server used by
# ``WorkerHTTP.start`` to serve a single accepted connection.  It lives in
# ``odoo.service.wsgi``; importing it from the canonical module rather than
# from ``server.py``'s re-export tuple avoids a useless indirection.
from .wsgi import BaseWSGIServerNoBind

if TYPE_CHECKING:
    from .server import PreforkServer

_logger = logging.getLogger("odoo.service.server")  # preserve operator log filters




class CpuTimeLimitExceeded(Exception):  # noqa: N818 — class name re-exported from ``service.server``; renaming would break external catchers
    """Raised by ``Worker.signal_time_expired_handler`` on SIGXCPU.

    Distinct exception class so that operator log filters and any future
    intermediate handler can discriminate this from a generic failure.
    The worker exits via ``SystemExit(1)`` from ``worker_spawn``; the
    process dying here is by design (CPU budget exhausted).
    """


class Worker:
    """Workers"""

    def __init__(self, multi: PreforkServer) -> None:
        self.multi = multi
        self.watchdog_time = time.monotonic()
        self.watchdog_pipe = multi.pipe_new()
        self.eintr_pipe = multi.pipe_new()
        self.wakeup_fd_r, self.wakeup_fd_w = self.eintr_pipe
        # Can be set to None if no watchdog is desired.
        self.watchdog_timeout = multi.timeout
        self.ppid = os.getpid()
        self.pid = None
        self.alive = True
        # should we rename into lifetime ?
        self.request_max = multi.limit_request
        self.request_count = 0
        self.logger = _logger.getChild(self.__class__.__name__)

    def setproctitle(self, title: str = "") -> None:
        setproctitle(f"odoo: {self.__class__.__name__} {self.pid} {title}")

    def close(self) -> None:
        """Close all pipe file descriptors held by this worker.

        Each ``os.close`` is guarded individually: if one fd is already
        invalid (e.g. double-close via a racing shutdown path) the remaining
        three must still be released, otherwise the parent process leaks up
        to three descriptors per dying worker.
        """
        for fd in (
            self.watchdog_pipe[0],
            self.watchdog_pipe[1],
            self.eintr_pipe[0],
            self.eintr_pipe[1],
        ):
            with contextlib.suppress(OSError):
                os.close(fd)

    def signal_handler(self, sig: int, frame: Any) -> None:
        self.alive = False

    def signal_time_expired_handler(self, n: int, stack: Any) -> None:
        # ASYNC-SIGNAL-SAFETY: this is a signal handler running on the
        # worker's main thread (SIGXCPU is blocked on ``_runloop`` via
        # pthread_sigmask, so the kernel routes it here).  The previous
        # version called ``self.logger.info(...)`` BEFORE raising — but
        # ``_logger`` acquires the logging lock, and if the main thread
        # held that lock at signal-arrival time the handler would
        # deadlock.  Drop the log: the typed ``CpuTimeLimitExceeded``
        # exception carries the cause (its class name appears in the
        # ``except BaseException`` log emitted by ``_runloop``, and again
        # in ``worker_spawn``'s "uncaught error" log), so no information
        # is lost.
        #
        # Lifecycle: the exception propagates out of ``t.join()`` in
        # ``Worker.run``, the run-loop's ``finally`` calls ``self.stop()``,
        # ``worker_spawn`` catches BaseException, exits via ``os._exit(1)``,
        # and the master replenishes via ``process_spawn``.
        raise CpuTimeLimitExceeded(
            f"CPU time limit ({config['limit_time_cpu']}s) exceeded"
        )

    def sleep(self) -> None:
        """Wait for wakeup events or timeout, draining the wakeup pipe."""
        try:
            self._selector.select(timeout=self.multi.beat)
            # clear wakeup pipe if we were interrupted
            empty_pipe(self.wakeup_fd_r)
        except OSError as e:
            if e.args[0] != errno.EINTR:
                raise

    def check_limits(self) -> None:
        # If our parent changed suicide
        if self.ppid != os.getppid():
            self.logger.info("Parent changed")
            self.alive = False
        # check for lifetime
        if self.request_count >= self.request_max:
            self.logger.info("Max request (%s) reached.", self.request_count)
            self.alive = False
        # Reset the worker if it consumes too much memory (e.g. caused by a memory leak).
        memory = memory_info(self._process_handle)
        if config["limit_memory_soft"] and memory > config["limit_memory_soft"]:
            # ``memory_info`` returns RSS (resident memory), not VMS — see the
            # helper's docstring for why VMS is unreliable on Python 3.13+.
            self.logger.info("RSS memory soft-limit reached: %s bytes.", memory)
            self.alive = False  # Commit suicide after the request.

        # update RLIMIT_CPU so limit_time_cpu applies per unit of work
        r = resource.getrusage(resource.RUSAGE_SELF)
        cpu_time = r.ru_utime + r.ru_stime
        _soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (int(cpu_time + config["limit_time_cpu"]), hard),
        )

    def process_work(self) -> None:
        """Process one unit of work. Subclasses override this."""
        pass

    def start(self) -> None:
        self.pid = os.getpid()
        self.setproctitle()
        self.logger.info("Alive")
        # Reseed the random number generator
        random.seed()
        # Cache the psutil.Process handle for self.  ``check_limits`` runs
        # every ``master.beat`` (4s); each call previously did
        # ``psutil.Process(os.getpid())`` which reads /proc/<pid>/stat to
        # validate the PID exists, plus ``.memory_info()`` reads
        # /proc/<pid>/status — two reads per check.  Caching the Process
        # halves that to one read.  PID is process-lifetime constant, so
        # caching is safe.
        self._process_handle = psutil.Process(self.pid)
        if self.multi.socket:
            # Prevent fd inheritance: close_on_exec
            flags = fcntl.fcntl(self.multi.socket, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
            fcntl.fcntl(self.multi.socket, fcntl.F_SETFD, flags)
            # reset blocking status
            self.multi.socket.setblocking(0)

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGXCPU, self.signal_time_expired_handler)

        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGTTIN, signal.SIG_DFL)
        signal.signal(signal.SIGTTOU, signal.SIG_DFL)

        signal.set_wakeup_fd(self.wakeup_fd_w)
        self._selector = selectors.DefaultSelector()
        self._selector.register(self.wakeup_fd_r, selectors.EVENT_READ)

    def stop(self) -> None:
        """Release resources held by this worker after the run loop exits."""
        if hasattr(self, "_selector"):
            self._selector.close()

    def run(self) -> None:
        """Entry point for the forked worker process.

        Wraps the join in try/finally so ``self.stop()`` (selector close,
        pg connection close in ``WorkerCron``) runs whether the worker
        exits cleanly or gets interrupted by SIGXCPU / a runloop fault.
        Without this, the previous code skipped cleanup on every abnormal
        exit — relying on process death to release fds, which works on
        Linux but leaves resource warnings in tests and is one ``except``
        clause away from a real leak.
        """
        self.start()
        t = threading.Thread(
            name=f"Worker {self.__class__.__name__} ({self.pid}) workthread",
            target=self._runloop,
            daemon=True,
        )
        t.start()
        try:
            t.join()
            self.logger.info(
                "Exiting cleanly. request_count: %s, registry count: %s.",
                self.request_count,
                len(Registry.registries),
            )
        finally:
            self.stop()

    def _runloop(self) -> None:
        """Main work loop run in a daemon thread inside the worker process."""
        signal.pthread_sigmask(
            signal.SIG_BLOCK,
            {
                signal.SIGXCPU,
                signal.SIGINT,
                signal.SIGQUIT,
                signal.SIGUSR1,
                signal.SIGUSR2,
            },
        )
        try:
            while self.alive:
                self.check_limits()
                self.multi.pipe_ping(self.watchdog_pipe)
                self.sleep()
                if not self.alive:
                    break
                self.process_work()
        except BaseException as exc:
            self.logger.exception("Exception occurred, exiting...")
            raise SystemExit(1) from exc


class WorkerHTTP(Worker):
    """HTTP Request workers"""

    def __init__(self, multi: PreforkServer) -> None:
        super().__init__(multi)

        # The ODOO_HTTP_SOCKET_TIMEOUT environment variable allows to control socket timeout for
        # extreme latency situations. It's generally better to use a good buffering reverse proxy
        # to quickly free workers rather than increasing this timeout to accommodate high network
        # latencies & b/w saturation. This timeout is also essential to protect against accidental
        # DoS due to idle HTTP connections.
        # ``float()`` raises ``ValueError`` on a non-numeric value (typo in a
        # systemd unit, etc.) and would otherwise crash every worker at start.
        # Mirror the ``ODOO_MAX_HTTP_THREADS`` parsing pattern: log and fall
        # back to the default rather than refusing to come up.
        #
        # Clamp to a minimum of 0.1s: a typo like ``ODOO_HTTP_SOCKET_TIMEOUT=0``
        # (intended as "no timeout") would put the socket in non-blocking mode
        # and break every request; a value like ``0.001`` is unusable in
        # practice (no real client responds within 1ms).  Negative values are
        # rejected by socket.settimeout but produce a confusing OSError at
        # request time rather than a clear startup warning.
        DEFAULT_SOCK_TIMEOUT = 2.0
        MIN_SOCK_TIMEOUT = 0.1
        env_value = os.environ.get("ODOO_HTTP_SOCKET_TIMEOUT")
        if env_value is None:
            self.sock_timeout = DEFAULT_SOCK_TIMEOUT
        else:
            try:
                parsed = float(env_value)
            except ValueError:
                _logger.warning(
                    "ODOO_HTTP_SOCKET_TIMEOUT=%r is not a number; using default %.1fs",
                    env_value,
                    DEFAULT_SOCK_TIMEOUT,
                )
                self.sock_timeout = DEFAULT_SOCK_TIMEOUT
            else:
                if parsed < MIN_SOCK_TIMEOUT:
                    _logger.warning(
                        "ODOO_HTTP_SOCKET_TIMEOUT=%s is below the %.1fs floor; "
                        "clamping to %.1fs.  Use a value ≥ %.1f to opt into a "
                        "shorter timeout intentionally.",
                        parsed, MIN_SOCK_TIMEOUT, MIN_SOCK_TIMEOUT, MIN_SOCK_TIMEOUT,
                    )
                    self.sock_timeout = MIN_SOCK_TIMEOUT
                else:
                    self.sock_timeout = parsed

    def process_request(self, client: socket.socket, addr: tuple[str, int]) -> None:
        client.setblocking(1)
        client.settimeout(self.sock_timeout)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Prevent fd inheritance close_on_exec
        flags = fcntl.fcntl(client, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(client, fcntl.F_SETFD, flags)
        # do request using BaseWSGIServerNoBind monkey patched with socket
        self.server.socket = client
        # tolerate broken pipe when the http client closes the socket before
        # receiving the full reply
        with contextlib.suppress(BrokenPipeError):
            self.server.process_request(client, addr)
        self.request_count += 1

    def process_work(self) -> None:
        try:
            client, addr = self.multi.socket.accept()
            self.process_request(client, addr)
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.ECONNABORTED):
                raise

    def start(self) -> None:
        Worker.start(self)
        self._selector.register(self.multi.socket, selectors.EVENT_READ)
        self.server = BaseWSGIServerNoBind(self.multi.app)


class WorkerCron(Worker):
    """Cron workers"""

    def __init__(self, multi: PreforkServer) -> None:
        super().__init__(multi)
        self.alive_time = time.monotonic()
        self.watchdog_timeout = (
            multi.cron_timeout
        )  # Use a distinct value for CRON Worker
        # process_work() below process a single database per call.
        # self.db_queue keeps track of the databases to process (in order, from left to right).
        self.db_queue: deque[str] = deque()
        self.db_count: int = 0

    def _sleep_with_watchdog(self, total_seconds: float) -> None:
        """Sleep for ``total_seconds`` while pinging the master watchdog.

        Used inside ``process_work`` reconnect backoff and any other path that
        must stall longer than ``master.beat`` (4s default) without letting
        the master mark the worker as stuck.  ``_runloop``'s pipe_ping only
        fires once per outer cycle (before ``sleep``); a 60s ``time.sleep``
        directly inside ``process_work`` would silently exceed the cron
        watchdog and trigger the SIGKILL → re-fork loop the rest of the
        backoff machinery is designed to prevent.

        Splits the wait into ``tick``-sized chunks (default 2s = half of
        ``master.beat``) and pings between each chunk.  Implementation
        explicitly avoids ``time.monotonic`` for the loop guard so unit
        tests that patch ``time.sleep`` to no-op don't have to also patch
        ``time.monotonic`` to make the loop terminate.
        """
        # Half-beat cadence: master polls every ``self.multi.beat`` (4s); a
        # ping at half that frequency guarantees the watchdog sees a fresh
        # timestamp before each master poll.  Floor at 0.5s so a misconfigured
        # ``beat`` near zero doesn't burn CPU on tight pings.
        tick = max(self.multi.beat / 2, 0.5)
        remaining = total_seconds
        while remaining > 0:
            self.multi.pipe_ping(self.watchdog_pipe)
            chunk = min(tick, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def sleep(self) -> None:
        # Really sleep once all the databases have been processed.
        if not self.db_queue:
            interval = SLEEP_INTERVAL + self.pid % 10  # chorus effect

            # Wait for an OS signal (wakeup pipe) or a Postgres NOTIFY.
            try:
                self._pg_selector.select(timeout=interval)
                # Small randomized stagger after wake — spreads concurrent
                # workers reacting to the same NOTIFY so they don't all
                # poll PG in the same millisecond (thundering herd).  The
                # previous form ``self.pid / 100 % 0.1`` collapsed to 0
                # for any pid divisible by 10, which produced exactly the
                # synchronization the comment was trying to avoid.  Uses
                # the shared ``CRON_NOTIFY_JITTER_MAX_S`` constant so this
                # value cannot drift from ``ThreadedServer.cron_thread``.
                time.sleep(random.uniform(0, CRON_NOTIFY_JITTER_MAX_S))
                empty_pipe(self.wakeup_fd_r)
            except OSError as e:
                if e.args[0] != errno.EINTR:
                    raise

    def check_limits(self) -> None:
        super().check_limits()

        if (
            config["limit_time_worker_cron"] > 0
            and (time.monotonic() - self.alive_time) > config["limit_time_worker_cron"]
        ):
            self.logger.info("Max age (%ss) reached.", config["limit_time_worker_cron"])
            self.alive = False

    def _connect_postgres(self) -> None:
        """Open (or reopen) the persistent postgres connection used for LISTEN."""
        dbconn = db.db_connect("postgres")
        self.dbcursor = dbconn.cursor()
        # LISTEN / NOTIFY doesn't work in recovery mode
        self.dbcursor.execute("SELECT pg_is_in_recovery()")
        in_recovery = self.dbcursor.fetchone()[0]
        if not in_recovery:
            # Disable idle_session_timeout for this connection: it stays idle
            # by design (waiting for NOTIFY) and must not be killed by PG18's
            # default timeout.
            self.dbcursor.execute("SET idle_session_timeout = 0")
            self.dbcursor.execute("LISTEN cron_trigger")
        else:
            self.logger.warning(
                "PG cluster in recovery mode, cron trigger not activated"
            )
        self.dbcursor.commit()
        # Rebuild the selector: wakeup pipe (OS signals) + postgres socket (NOTIFY).
        # Called on initial connect and on reconnect after connection loss.
        if hasattr(self, "_pg_selector"):
            self._pg_selector.close()
        self._pg_selector = selectors.DefaultSelector()
        self._pg_selector.register(self.wakeup_fd_r, selectors.EVENT_READ)
        self._pg_selector.register(self.dbcursor.connection, selectors.EVENT_READ)

    def process_work(self) -> None:
        """Process a single database."""
        self.logger.debug("polling for jobs")

        if not self.db_queue:
            # list databases — both ``cron_database_list`` (which goes through
            # ``list_dbs`` -> ``db_connect("postgres")``) and the ``notifies``
            # call below can fail when PG is unreachable.  The H-2 reconnect
            # path originally only covered ``notifies``; a PoolError from the
            # earlier ``list_dbs`` call propagated to ``_runloop``, which
            # raised SystemExit(1), and the master re-forked at master.beat
            # (~4s) — exactly the fork-storm pattern H-2 fixed for the other
            # path.  Wrap both calls and widen the catch to PoolError (the
            # type the pool layer wraps connection failures in; not a
            # subclass of OperationalError).
            try:
                db_names = OrderedSet(cron_database_list())
                notified = OrderedSet(
                    notif.payload
                    for notif in self.dbcursor.connection.notifies(timeout=0)
                    if notif.channel == "cron_trigger"
                )
            except (psycopg.OperationalError, PoolError):
                self.logger.warning("Lost postgres connection, reconnecting...")
                with contextlib.suppress(Exception):
                    self.dbcursor.connection.close()
                with contextlib.suppress(Exception):
                    self.dbcursor.close()
                # Backoff on reconnect failures.  The previous form raised
                # after sleeping, which killed the worker so the master
                # could fork a replacement.  But the master forks
                # immediately (process_spawn loop, master.beat=4s wait),
                # the new worker starts fresh with attempts=0, sleeps 2s,
                # raises again — escalation never happened, the 60s cap
                # was never reached, and a sustained PG outage produced a
                # continuous fork churn at ~6s/cycle.
                #
                # Now: the worker stays alive.  Each consecutive failure
                # escalates the backoff up to 60s.  ``return`` skips this
                # poll cycle; the next ``process_work`` retry picks up the
                # now-elevated counter.  Inside the backoff sleep we ping
                # the watchdog every ``master.beat`` seconds — the outer
                # ``_runloop`` only pings once per cycle (before sleep),
                # so a 60s ``time.sleep`` here would otherwise exceed the
                # default ``limit_time_real_cron`` (-1 → inherits the
                # 120s ``limit_time_real``) once we add the ~70s
                # ``WorkerCron.sleep`` wait that already happened above.
                # Without these intra-backoff pings the master SIGKILLs
                # the worker mid-sleep — the original fork-storm pattern,
                # just slower (every ~120s instead of every ~6s).  The
                # worker only dies when it hits its normal lifetime limit
                # (limit_time_worker_cron).
                try:
                    self._connect_postgres()
                    self._reconnect_attempts = 0
                except Exception:
                    self._reconnect_attempts = getattr(
                        self, "_reconnect_attempts", 0
                    ) + 1
                    backoff = min(2 ** self._reconnect_attempts, 60)
                    self.logger.warning(
                        "Reconnect to postgres failed (attempt %d); sleeping %ds",
                        self._reconnect_attempts,
                        backoff,
                    )
                    self._sleep_with_watchdog(backoff)
                return  # skip this cycle; notifies will be polled on next iteration
            # add notified databases (in order) first in the queue
            self.db_queue.extend(db for db in notified if db in db_names)
            self.db_queue.extend(db for db in db_names if db not in notified)
            self.db_count = len(self.db_queue)
            if not self.db_count:
                return

        # pop the leftmost element (because notified databases appear first)
        db_name = self.db_queue.popleft()
        self.setproctitle(db_name)

        from odoo.addons.base.models.ir_cron import IrCron

        IrCron._process_jobs(db_name)

        # dont keep cursors in multi database mode
        if self.db_count > 1:
            db.close_db(db_name)

        self.request_count += 1
        if self.request_count >= self.request_max and self.request_max < self.db_count:
            self.logger.error(
                "There are more databases to process than allowed "
                "by the `limit_request` configuration variable: %s more.",
                self.db_count - self.request_max,
            )

    def start(self) -> None:
        os.nice(10)  # mommy always told me to be nice with others...
        Worker.start(self)
        # WorkerCron uses _pg_selector for its sleep; _selector (which only
        # has wakeup_fd_r) is redundant here — release it immediately.
        self._selector.close()
        del self._selector
        if self.multi.socket:
            self.multi.socket.close()

        # Retry the initial PG connect with exponential backoff.  Without
        # this, a worker that boots while PG is unreachable raises out of
        # ``Worker.run()`` immediately, the master spawns a replacement at
        # ``master.beat`` (~4s) intervals, and the operator sees a fork
        # storm until PG returns.  ``_sleep_with_watchdog`` pings every
        # half-beat so a 60s backoff still keeps the master from marking
        # this worker as stuck; the cron worker's own lifetime limit
        # (``limit_time_worker_cron``) is the natural escape hatch if PG
        # never returns.
        attempts = 0
        while True:
            try:
                self._connect_postgres()
                break
            except Exception as exc:
                attempts += 1
                backoff = min(2 ** attempts, 60)
                self.logger.warning(
                    "WorkerCron initial PG connect failed (attempt %d): %s; sleeping %ds",
                    attempts, exc, backoff,
                )
                self._sleep_with_watchdog(backoff)

    def stop(self) -> None:
        super().stop()
        if hasattr(self, "_pg_selector"):
            self._pg_selector.close()
        # ``self.dbcursor`` is only assigned once ``_connect_postgres`` succeeds.
        # If ``Worker.start`` was interrupted during the initial backoff loop
        # (PG was unreachable, SIGTERM arrived), the attribute does not exist
        # and an unguarded access here would mask any in-flight exception with
        # an opaque ``AttributeError`` from the run-loop's ``finally`` clause.
        if hasattr(self, "dbcursor"):
            with contextlib.suppress(Exception):
                self.dbcursor.connection.close()
            with contextlib.suppress(Exception):
                self.dbcursor.close()

