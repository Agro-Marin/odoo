"""Prefork worker classes.

``PreforkServer`` (``_prefork.py``) forks one of these ``Worker`` subclasses
per child process.  Workers reach the master through their ``multi`` attribute
(typed as ``PreforkServer`` under ``TYPE_CHECKING`` to avoid a runtime import
cycle).

* ``CpuTimeLimitExceeded`` — typed exception so SIGXCPU is log-distinguishable.
* ``Worker`` — base class: signal handling, watchdog pipe, RLIMIT_CPU update,
  and the ``run`` / ``_runloop`` process cycle.
* ``WorkerHTTP`` — accept and serve HTTP requests on the listening socket.
* ``WorkerCron`` — LISTEN/NOTIFY cron processing with exponential-backoff
  reconnect that survives PG outages.
* ``WorkerJob`` — same machinery pointed at the ``job_queue`` channel to
  execute background jobs (``ir.job``).

Tests live in ``tests/service/test_server.py`` (``TestWorker*`` /
``TestWorkerCron*``); they patch names in this module's namespace
(``odoo.service._worker.X``).
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
    import fcntl
    import resource

try:
    from setproctitle import setproctitle
except ImportError:

    def setproctitle(x: str) -> None:
        return None


from odoo import db
from odoo.db import PoolError
from odoo.modules.registry import Registry
from odoo.tools import OrderedSet, config

from ._cron import (
    CRON_TRIGGER_CHANNEL,
    JOB_QUEUE_CHANNEL,
    arm_cron_listen,
    drain_cron_notifies,
    order_notified_first,
)
from ._env import env_int
from ._helpers import (
    CRON_NOTIFY_JITTER_MAX_S,
    SLEEP_INTERVAL,
    capped_backoff,
    cron_database_list,
    empty_pipe,
    over_memory_soft_limit,
)

from .wsgi import BaseWSGIServerNoBind, http_socket_timeout

if TYPE_CHECKING:
    from .server import PreforkServer

_logger = logging.getLogger("odoo.service.server")


class CpuTimeLimitExceeded(Exception):
    """Raised by ``Worker.signal_time_expired_handler`` on SIGXCPU.

    A distinct class so log filters can tell it from a generic failure.  Plain
    ``Exception`` (not ``SystemExit``) so it propagates to ``worker_spawn``'s
    ``except BaseException``, which logs it and exits the child; the master
    then replenishes the worker.
    """


class Worker:
    """Workers"""

    _CPU_LIMIT_JOIN_GRACE_S = 1.0

    def __init__(self, multi: PreforkServer) -> None:
        self.multi = multi
        self.watchdog_time = time.monotonic()
        self.watchdog_pipe = multi.pipe_new()
        try:
            self.eintr_pipe = multi.pipe_new()
        except BaseException:
            for fd in self.watchdog_pipe:
                with contextlib.suppress(OSError):
                    os.close(fd)
            raise
        self.wakeup_fd_r, self.wakeup_fd_w = self.eintr_pipe
        self.watchdog_timeout = multi.timeout
        self.ppid = os.getpid()
        self.pid = None
        self.alive = True
        self.request_max = multi.limit_request
        self.request_count = 0
        self.logger = _logger.getChild(self.__class__.__name__)

    def setproctitle(self, title: str = "") -> None:
        setproctitle(f"odoo: {self.__class__.__name__} {self.pid} {title}")

    def close(self) -> None:
        """Close all pipe file descriptors held by this worker.

        Each ``os.close`` is guarded individually so an already-invalid fd (e.g.
        double-close on a racing shutdown) still lets the other three be released.
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
        raise CpuTimeLimitExceeded(
            f"CPU time limit ({config['limit_time_cpu']}s) exceeded"
        )

    def sleep(self) -> None:
        """Wait for wakeup events or timeout, draining the wakeup pipe."""
        try:
            self._selector.select(timeout=self.multi.beat)
            empty_pipe(self.wakeup_fd_r)
        except OSError as e:
            if e.args[0] != errno.EINTR:
                raise

    def check_limits(self) -> None:
        if self.ppid != os.getppid():
            self.logger.info("Parent changed")
            self.alive = False
        if self.request_max > 0 and self.request_count >= self.request_max:
            self.logger.info("Max request (%s) reached.", self.request_count)
            self.alive = False
        memory = over_memory_soft_limit(
            self._process_handle, config["limit_memory_soft"]
        )
        if memory is not None:
            self.logger.info("RSS memory soft-limit reached: %s bytes.", memory)
            self.alive = False

        limit_time_cpu = config["limit_time_cpu"]
        if limit_time_cpu > 0:
            r = resource.getrusage(resource.RUSAGE_SELF)
            cpu_time = r.ru_utime + r.ru_stime
            _soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            soft = int(cpu_time + limit_time_cpu)
            if hard != resource.RLIM_INFINITY and soft > hard:
                soft = hard
            resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))

    def process_work(self) -> None:
        """Process one unit of work. Subclasses override this."""
        pass

    def start(self) -> None:
        self.pid = os.getpid()
        self.setproctitle()
        self.logger.info("Alive")
        random.seed()
        self._process_handle = psutil.Process(self.pid)
        if self.multi.socket:
            flags = fcntl.fcntl(self.multi.socket, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
            fcntl.fcntl(self.multi.socket, fcntl.F_SETFD, flags)
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

        Wraps the join in try/finally so ``self.stop()`` runs whether the worker
        exits cleanly or is interrupted by SIGXCPU / a runloop fault.
        """
        self.start()
        self._runloop_exc: BaseException | None = None
        t = threading.Thread(
            name=f"Worker {self.__class__.__name__} ({self.pid}) workthread",
            target=self._runloop,
            daemon=True,
        )
        t.start()
        try:
            t.join()
            if self._runloop_exc is not None:
                raise SystemExit(1)
            self.logger.info(
                "Exiting cleanly. request_count: %s, registry count: %s.",
                self.request_count,
                len(Registry.registries),
            )
        except CpuTimeLimitExceeded:
            self.logger.warning(
                "CPU time limit (%ss) exceeded; recycling worker.",
                config["limit_time_cpu"],
            )
            self.alive = False
            t.join(timeout=self._CPU_LIMIT_JOIN_GRACE_S)
            if t.is_alive():
                self.logger.warning(
                    "Work thread still running %.1fs after CPU-limit stop; "
                    "exiting anyway.",
                    self._CPU_LIMIT_JOIN_GRACE_S,
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
            self._runloop_exc = exc


class WorkerHTTP(Worker):
    """HTTP Request workers"""

    def __init__(self, multi: PreforkServer) -> None:
        super().__init__(multi)

        self.sock_timeout = http_socket_timeout()

    def process_request(self, client: socket.socket, addr: tuple[str, int]) -> None:
        client.setblocking(1)
        client.settimeout(self.sock_timeout)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        flags = fcntl.fcntl(client, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(client, fcntl.F_SETFD, flags)
        self.server.socket = client
        try:
            with contextlib.suppress(BrokenPipeError):
                self.server.finish_request(client, addr)
        finally:
            # Split out of socketserver's process_request, which is
            # `finish_request(...)` then `shutdown_request(...)` with NO
            # try/finally: any exception escaping the handler skips the close
            # and leaks the accepted socket for the rest of the worker's life.
            # BrokenPipeError -- suppressed right above, so routine here -- is
            # exactly such an exception. Repeated, it ends at EMFILE, where
            # accept() starts raising and the worker dies and respawns in a
            # loop.
            self.server.shutdown_request(client)
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

    listen_channel = CRON_TRIGGER_CHANNEL

    def __init__(self, multi: PreforkServer) -> None:
        super().__init__(multi)
        self.alive_time = time.monotonic()
        self.watchdog_timeout = multi.cron_timeout
        self.db_queue: deque[str] = deque()
        self.db_count: int = 0
        self._reconnect_attempts: int = 0

    def _sleep_with_watchdog(self, total_seconds: float) -> None:
        """Sleep for ``total_seconds`` while pinging the master watchdog.

        ``_runloop`` pings once per outer cycle, so a long bare ``time.sleep``
        (e.g. a 60s reconnect backoff) would trip the cron watchdog into a
        SIGKILL → re-fork loop.  Splits the wait into ``tick``-sized chunks,
        pinging between each.  Uses a decrementing counter (not
        ``time.monotonic``) so tests that no-op ``time.sleep`` still terminate.
        """
        tick = max(self.multi.beat / 2, 0.5)
        remaining = total_seconds
        while remaining > 0 and self.alive:
            self.multi.pipe_ping(self.watchdog_pipe)
            chunk = min(tick, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _process_db(self, db_name: str) -> None:
        """Run this worker's unit of work for one database.

        Deferred import: base models must not load at service import time.
        """
        from odoo.addons.base.models.ir_cron import IrCron

        IrCron._process_jobs(db_name)

    def sleep(self) -> None:
        if not self.db_queue:
            if self._reconnect_attempts > 0:
                return

            interval = SLEEP_INTERVAL + self.pid % 10

            if self.watchdog_timeout:
                interval = min(interval, max(self.watchdog_timeout / 2, 1))

            try:
                self._pg_selector.select(timeout=interval)
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

    def _backoff_after_failed_connect(
        self, attempt: int, what: str, exc: BaseException
    ) -> None:
        """Warn and sleep with exponential backoff after a failed PG connect.

        Shared by the boot connect loop (``start``) and the per-cycle reconnect
        (``process_work``) so the backoff and watchdog-pinging cadence can't
        drift.  The caller owns the attempt counter and control flow — and both
        callers' counters are unbounded across a sustained outage, which is why
        the exponent is clamped inside :func:`capped_backoff`.
        """
        backoff = capped_backoff(attempt, SLEEP_INTERVAL)
        self.logger.warning(
            "%s failed (attempt %d): %s; sleeping %ds", what, attempt, exc, backoff
        )
        self._sleep_with_watchdog(backoff)

    def _connect_postgres(self) -> None:
        """Open (or reopen) the persistent postgres connection used for LISTEN.

        Atomic: the new cursor and selector are built in locals and published to
        ``self.dbcursor`` / ``self._pg_selector`` only once every step succeeds.
        If any step raises (PG restart mid-``LISTEN``), the half-open cursor is
        torn down and ``self.dbcursor`` keeps its prior (closed) value, so the
        next cycle re-enters the reconnect path — rather than being left with a
        live-but-not-listening connection and a selector on a stale fd.
        """
        dbconn = db.db_connect("postgres")
        cursor = dbconn.cursor()
        try:
            arm_cron_listen(
                cursor,
                self.logger,
                channel=self.listen_channel,
                disable_idle_timeout=True,
            )
            cursor.commit()
            selector = selectors.DefaultSelector()
            selector.register(self.wakeup_fd_r, selectors.EVENT_READ)
            selector.register(cursor.connection, selectors.EVENT_READ)
        except Exception:
            with contextlib.suppress(Exception):
                cursor.connection.close()
            with contextlib.suppress(Exception):
                cursor.close()
            raise
        if hasattr(self, "_pg_selector"):
            self._pg_selector.close()
        self.dbcursor = cursor
        self._pg_selector = selector

    def process_work(self) -> None:
        """Process a single database."""
        self.logger.debug("polling for jobs")

        if not self.db_queue:
            try:
                db_names = OrderedSet(cron_database_list())
                notified = drain_cron_notifies(
                    self.dbcursor.connection, channel=self.listen_channel
                )
            except psycopg.OperationalError, PoolError:
                self.logger.warning("Lost postgres connection, reconnecting...")
                with contextlib.suppress(Exception):
                    self.dbcursor.connection.close()
                with contextlib.suppress(Exception):
                    self.dbcursor.close()
                try:
                    self._connect_postgres()
                    self._reconnect_attempts = 0
                except Exception as exc:
                    self._reconnect_attempts += 1
                    self._backoff_after_failed_connect(
                        self._reconnect_attempts, "Reconnect to postgres", exc
                    )
                return
            self.db_queue.extend(order_notified_first(notified, db_names))
            self.db_count = len(self.db_queue)
            if not self.db_count:
                return

        db_name = self.db_queue.popleft()
        self.setproctitle(db_name)

        try:
            self._process_db(db_name)
        except Exception:
            self.logger.warning(
                "Uncaught error while processing jobs for database %s",
                db_name,
                exc_info=True,
            )

        if self.db_count > 1:
            db.close_db(db_name)

        self.request_count += 1
        if (
            self.request_max > 0
            and self.request_count >= self.request_max
            and self.request_max < self.db_count
        ):
            self.logger.error(
                "There are more databases to process than allowed "
                "by the `limit_request` configuration variable: %s more.",
                self.db_count - self.request_max,
            )

    def start(self) -> None:
        os.nice(10)
        Worker.start(self)
        self._selector.close()
        del self._selector
        if self.multi.socket:
            self.multi.socket.close()
        registries_size = env_int(
            "ODOO_REGISTRY_LRU_SIZE_CRON", 0, minimum=0, logger=self.logger
        )
        if registries_size > 0:
            Registry.registries.count = registries_size

        attempts = 0
        while self.alive:
            try:
                self._connect_postgres()
                break
            except Exception as exc:
                attempts += 1
                self._backoff_after_failed_connect(
                    attempts, "WorkerCron initial PG connect", exc
                )

    def stop(self) -> None:
        super().stop()
        if hasattr(self, "_pg_selector"):
            self._pg_selector.close()
        if hasattr(self, "dbcursor"):
            with contextlib.suppress(Exception):
                self.dbcursor.connection.close()
            with contextlib.suppress(Exception):
                self.dbcursor.close()


class WorkerJob(WorkerCron):
    """Background job (``ir.job``) workers.

    ``WorkerCron`` with the LISTEN channel and per-database unit of work swapped
    out; everything hard (persistent LISTEN connection with backoff reconnect,
    watchdog-pinging sleeps, notified-first queue, max-age recycling) is
    inherited unchanged.  Jobs are claimed from ``ir_job`` with ``SKIP LOCKED``
    and run in-process, each in its own transaction (see ``IrJob._process_jobs``).
    """

    listen_channel = JOB_QUEUE_CHANNEL

    def _process_db(self, db_name: str) -> None:
        from odoo.addons.base.models.ir_job import IrJob

        IrJob._process_jobs(db_name)
