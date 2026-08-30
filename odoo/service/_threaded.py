from __future__ import annotations

import logging
import os
import random
import selectors
import signal
import threading
import time
from typing import Any

import psutil
import psycopg
import werkzeug.serving

from odoo import db
from odoo.db import PoolError
from odoo.libs.worker_thread import as_worker_thread, current_worker_thread
from odoo.modules.registry import Registry
from odoo.tools import config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks

from . import _process_state
from ._base_server import _SIGHUP_AVAILABLE, CommonServer
from ._cron import (
    CRON_NOTIFY_JITTER_MAX_S,
    CRON_POLL_INTERVAL_S,
    CRON_TRIGGER_CHANNEL,
    JOB_QUEUE_CHANNEL,
    CronSchedule,
    ReconnectBackoff,
    drain_cron_notifies,
    open_cron_listener,
    release_cron_cursor,
    release_swept_database,
)
from ._env import _IS_POSIX, _IS_WINDOWS
from ._limits import (
    cron_real_time_budget,
    job_max_age,
    job_real_time_budget,
)
from .lifecycle import preload_registries, restart
from .wsgi import RequestHandler, ThreadedWSGIServerReloadable

_logger = logging.getLogger("odoo.service.server")

_RECYCLE_MAX_AGE = "max_age"
_RECYCLE_CONN_LOST = "connection_lost"

LIMIT_MONITOR_INTERVAL_S = 5.0

LIMIT_GRACE_PERIOD_S = 60.0
"""How long a thread over its limit may wait for other requests to finish.

Its own constant.  This borrowed the cron poll interval, which has nothing to
do with how long to let in-flight HTTP requests drain; the two shared a number
and so could not be tuned apart.
"""

_TIME_LIMITED_THREAD_TYPES = ("http", "cron", "job")
"""Thread kinds `check_limits` may recycle the server for.

"websocket" is deliberately absent.  `bus/websocket.py` re-labels the request
thread the moment it starts serving frames, and a websocket is long-lived by
design -- left in this list it would trip `limit_time_real` and reload the
server under every connected client.
"""

_REPORTED_THREAD_TYPES = (*_TIME_LIMITED_THREAD_TYPES, "websocket")
"""Thread kinds `metrics()` counts, which is a different question.

An operator running --workers 0 wants to see the websocket threads precisely
because they are long-lived: they hold a thread and a connection each, and
they were invisible while the two lists were one.
"""

_SIGXCPU_EXIT_CODE = 128 + getattr(signal, "SIGXCPU", 24)


class ThreadedServer(CommonServer):
    flavor = "threaded"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.main_thread_id = threading.current_thread().ident
        self.quit_signals_received = 0

        self.httpd: ThreadedWSGIServerReloadable | None = None
        self.limits_reached_threads: set[threading.Thread] = set()
        self.limit_reached_time: float | None = None
        self._stop_after_init = False

    def metrics(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for thread in threading.enumerate():
            kind = getattr(thread, "type", None)
            if kind in _REPORTED_THREAD_TYPES:
                by_type[kind] = by_type.get(kind, 0) + 1
        return {
            "threads": {k: by_type.get(k, 0) for k in _REPORTED_THREAD_TYPES},
            "http_threads_max": getattr(self.httpd, "max_http_threads", 0),
            "limits_reached_threads": len(self.limits_reached_threads),
        }

    def signal_handler(self, sig: int, frame: Any) -> None:
        if sig in [signal.SIGINT, signal.SIGTERM]:
            self.quit_signals_received += 1
            if self.quit_signals_received > 1:
                os.write(2, b"Forced shutdown.\n")
                os._exit(0)
            raise KeyboardInterrupt
        if hasattr(signal, "SIGXCPU") and sig == signal.SIGXCPU:
            os.write(2, b"CPU time limit exceeded! Shutting down immediately\n")
            os._exit(_SIGXCPU_EXIT_CODE)
        elif _SIGHUP_AVAILABLE and sig == signal.SIGHUP:
            if self.quit_signals_received:
                return
            _process_state.set_phoenix(True)
            self.quit_signals_received += 1
            raise KeyboardInterrupt

    def check_limits(self) -> None:
        memory_over_limit = self.check_memory_limit() is not None

        now = time.monotonic()
        for thread in threading.enumerate():
            thread_type = getattr(thread, "type", None)
            if thread_type in _TIME_LIMITED_THREAD_TYPES:
                start_time = getattr(thread, "start_time", None)
                if start_time:
                    thread_execution_time = now - start_time
                    if thread_type == "job":
                        thread_limit_time_real = job_real_time_budget()
                    elif thread_type == "cron":
                        thread_limit_time_real = cron_real_time_budget()
                    else:
                        thread_limit_time_real = config["limit_time_real"]
                    if (
                        thread_limit_time_real > 0
                        and thread_execution_time > thread_limit_time_real
                    ):
                        self.logger.warning(
                            "Thread %s real time limit (%.1f/%ds) reached.",
                            thread,
                            thread_execution_time,
                            thread_limit_time_real,
                        )
                        self.limits_reached_threads.add(thread)
        for thread in list(self.limits_reached_threads):
            if not thread.is_alive():
                self.limits_reached_threads.remove(thread)
        if self.limits_reached_threads or memory_over_limit:
            self.limit_reached_time = self.limit_reached_time or now
        else:
            self.limit_reached_time = None

    def cron_thread(self, number: int) -> None:
        from odoo.addons.base.models.ir_cron import IrCron

        self._listen_thread(
            number,
            channel=CRON_TRIGGER_CHANNEL,
            process_jobs=IrCron._process_jobs,
            label="cron",
        )

    def job_thread(self, number: int) -> None:
        from odoo.addons.base.models.ir_job import IrJob

        self._listen_thread(
            number,
            channel=JOB_QUEUE_CHANNEL,
            process_jobs=IrJob._process_jobs,
            label="job",
        )

    def _run_due_jobs(
        self,
        db_names: list[str],
        process_jobs: Any,
        cron_logger: logging.Logger,
    ) -> None:
        release = len(db_names) > 1
        for db_name in db_names:
            thread = current_worker_thread()
            thread.start_time = time.monotonic()
            try:
                process_jobs(db_name)
            except Exception:
                cron_logger.warning(
                    "Uncaught error for database %s", db_name, exc_info=True
                )
            finally:
                thread.start_time = None
                if release:
                    release_swept_database(db_name)

    def _poll_cron_channel(
        self,
        cr: Any,
        number: int,
        channel: str,
        process_jobs: Any,
        cron_logger: logging.Logger,
        max_age: int,
    ) -> str:
        pg_conn = cr.connection
        schedule = CronSchedule()
        alive_time = time.monotonic()
        first_pass = True
        with selectors.DefaultSelector() as _sel:
            _sel.register(pg_conn, selectors.EVENT_READ)
            while max_age <= 0 or (time.monotonic() - alive_time) <= max_age:
                _sel.select(timeout=0 if first_pass else CRON_POLL_INTERVAL_S + number)
                first_pass = False
                time.sleep(random.uniform(0, CRON_NOTIFY_JITTER_MAX_S))
                try:
                    notified = drain_cron_notifies(pg_conn, channel=channel)
                except Exception:
                    if pg_conn.closed:
                        return _RECYCLE_CONN_LOST
                    raise

                db_names = schedule.due(notified)
                if not db_names:
                    continue

                cron_logger.debug("polling for jobs (notified: %s)", notified)
                self._run_due_jobs(db_names, process_jobs, cron_logger)
        return _RECYCLE_MAX_AGE

    def _listen_thread(
        self,
        number: int,
        *,
        channel: str,
        process_jobs: Any,
        label: str,
    ) -> None:
        max_age = job_max_age() if label == "job" else config["limit_time_worker_cron"]

        cron_logger = self.logger.getChild(f"{label}{number}")
        cron_logger.info("Alive")

        backoff = ReconnectBackoff(cron_logger)
        while True:
            cr = None
            try:
                cr = open_cron_listener(channel, cron_logger)
                reason = self._poll_cron_channel(
                    cr, number, channel, process_jobs, cron_logger, max_age
                )
                backoff.reset()
                if reason == _RECYCLE_CONN_LOST:
                    cron_logger.warning("Postgres connection lost, reconnecting...")
                else:
                    cron_logger.info(
                        "Max age (%ss) reached, recycling pg connection",
                        max_age,
                    )
            except SystemExit:
                raise
            except (psycopg.OperationalError, PoolError) as exc:
                backoff.wait_after("Postgres unavailable", exc)
            except Exception as exc:
                cron_logger.critical("Uncaught error in cron main loop", exc_info=True)
                backoff.wait_after("Cron main loop", exc)
            finally:
                if cr is not None:
                    release_cron_cursor(cr)

    def cron_spawn(self) -> None:
        for i in range(config["max_cron_threads"]):
            t = threading.Thread(
                target=self.cron_thread,
                args=(i,),
                name=f"odoo.service.cron.cron{i}",
                daemon=True,
            )
            as_worker_thread(t).type = "cron"
            t.start()

    def job_spawn(self) -> None:
        for i in range(config["job_workers"]):
            t = threading.Thread(
                target=self.job_thread,
                args=(i,),
                name=f"odoo.service.job.job{i}",
                daemon=True,
            )
            as_worker_thread(t).type = "job"
            t.start()

    def http_spawn(self) -> None:
        try:
            self.httpd = ThreadedWSGIServerReloadable(
                self.interface, self.port, self.app
            )
        except SystemExit:
            self.logger.critical(
                "Failed to bind the HTTP server to %s:%s -- the address is "
                "unavailable (already in use, or not permitted). Nothing will "
                "be served; see the message on stderr for the OS-level cause.",
                self.interface,
                self.port,
            )
            raise
        threading.Thread(
            target=self.httpd.serve_forever,
            name="odoo.service.httpd",
            daemon=True,
        ).start()

    def start(self, stop: bool = False) -> None:
        self.logger.debug("Setting signal handlers")
        if _IS_POSIX:
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
            signal.signal(signal.SIGHUP, self.signal_handler)
            signal.signal(signal.SIGXCPU, self.signal_handler)
            signal.signal(signal.SIGQUIT, dumpstacks)
            signal.signal(signal.SIGUSR1, log_ormcache_stats)
            signal.signal(signal.SIGUSR2, log_ormcache_stats)
        elif _IS_WINDOWS:
            import win32api

            win32api.SetConsoleCtrlHandler(
                lambda sig: self.signal_handler(sig, None), 1
            )

        if _IS_POSIX and config["limit_time_cpu"] > 0:
            self.logger.info(
                "limit_time_cpu=%ss is not enforced with workers=0: the CPU "
                "budget is armed per worker process (RLIMIT_CPU in "
                "odoo.service._worker), and a threaded server has none. Use "
                "limit_time_real, which this server does enforce per thread.",
                config["limit_time_cpu"],
            )

        if config["http_enable"] and (config["test_enable"] or not stop):
            self.http_spawn()

    def stop(self) -> None:
        if _process_state.server_phoenix:
            self.logger.info("Initiating server reload")
        elif self._stop_after_init:
            self.logger.info("Initialization done, shutting down")
        else:
            self.logger.info("Initiating shutdown")
            self.logger.info(
                "Hit CTRL-C again or send a second signal to force the shutdown."
            )

        if self.httpd:
            self.httpd.shutdown()

        super().stop()

        stop_time = time.monotonic()

        me = threading.current_thread()
        self.logger.debug("current thread: %r", me)
        for thread in threading.enumerate():
            self.logger.debug("process %r (%r)", thread, thread.daemon)
            if (
                thread != me
                and not thread.daemon
                and thread.ident != self.main_thread_id
                and thread not in self.limits_reached_threads
            ):
                while thread.is_alive() and (time.monotonic() - stop_time) < 1:
                    self.logger.debug("join and sleep")
                    thread.join(0.05)
                    time.sleep(0.05)

        db.close_all()

        current_process = psutil.Process()
        children = current_process.children(recursive=False)
        for child in children:
            self.logger.info(
                "A child process was found, pid is %s, process may hang", child
            )

        self.logger.debug("--")
        logging.shutdown()

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        rc: int | None = None
        self._stop_after_init = stop
        try:
            self.start(stop=stop)
            rc = preload_registries(preload)

            if stop:
                if config["test_enable"]:
                    from odoo.tests.result import _logger as logger

                    with Registry.registries._lock:
                        for db_name, registry in Registry.registries.items():
                            report = registry._assertion_report
                            log = (
                                logger.error
                                if not report.wasSuccessful()
                                else (
                                    logger.warning
                                    if not report.testsRun
                                    else logger.info
                                )
                            )
                            log("%s when loading database %r", report, db_name)
                return rc

            self.cron_spawn()
            self.job_spawn()

            while self.quit_signals_received == 0:
                self.check_limits()
                if self.limit_reached_time:
                    has_other_valid_requests = self._has_other_http_requests()
                    if (
                        not has_other_valid_requests
                        or (time.monotonic() - self.limit_reached_time)
                        > LIMIT_GRACE_PERIOD_S
                    ):
                        self.logger.info(
                            "Dumping stacktrace of limit exceeding threads before reloading"
                        )
                        dumpstacks(
                            thread_idents={
                                thread.ident
                                for thread in self.limits_reached_threads
                                if thread.ident is not None
                            }
                        )
                        self.reload()
                    else:
                        time.sleep(1)
                else:
                    time.sleep(LIMIT_MONITOR_INTERVAL_S)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
        return rc if stop else None

    def _has_other_http_requests(self) -> bool:
        return any(
            t not in self.limits_reached_threads
            for t in threading.enumerate()
            if getattr(t, "type", None) == "http"
        )

    def reload(self) -> None:
        restart()


class EventServer(CommonServer):
    flavor = "evented"

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.port = config["gevent_port"]
        self.httpd: werkzeug.serving.BaseWSGIServer | None = None
        self.ppid = os.getppid()

    def memory_soft_limit(self) -> int:
        return config["limit_memory_soft_gevent"] or config["limit_memory_soft"]

    def check_limits(self) -> None:
        restart = False
        new_ppid = os.getppid()
        if self.ppid != new_ppid:
            self.logger.warning("Parent changed: %s -> %s", self.ppid, new_ppid)
            restart = True
        if self.check_memory_limit() is not None:
            restart = True
        if restart:
            os.kill(self.pid, signal.SIGTERM)

    def watchdog(self, beat: int = 4) -> None:
        self.ppid = os.getppid()
        while True:
            try:
                self.check_limits()
            except Exception:
                self.logger.warning(
                    "Evented watchdog check failed; retrying in %ss",
                    beat,
                    exc_info=True,
                )
            time.sleep(beat)

    def _quit_signal_handler(self, sig: int, frame: Any) -> None:
        raise KeyboardInterrupt

    def start(self) -> None:
        if _IS_POSIX:
            signal.signal(signal.SIGINT, self._quit_signal_handler)
            signal.signal(signal.SIGTERM, self._quit_signal_handler)
            signal.signal(signal.SIGQUIT, dumpstacks)
            signal.signal(signal.SIGUSR1, log_ormcache_stats)
            signal.signal(signal.SIGUSR2, log_ormcache_stats)
            threading.Thread(
                target=self.watchdog,
                daemon=True,
                name="odoo.service.evented.watchdog",
            ).start()

        try:
            self.httpd = werkzeug.serving.make_server(
                self.interface,
                self.port,
                self.app,
                threaded=True,
                request_handler=RequestHandler,
            )
            self.logger.info(
                "Evented/WebSocket service running on %s:%s",
                self.interface,
                self.port,
            )
            self.httpd.serve_forever()
        except SystemExit:
            raise
        except KeyboardInterrupt:
            pass
        except BaseException as exc:
            self.logger.critical("Uncaught error in main loop", exc_info=True)
            raise SystemExit(1) from exc
        self.logger.info("Evented/WebSocket service stopped")

    def stop(self) -> None:
        if self.httpd:
            self.httpd.server_close()
        super().stop()

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        if preload:
            self.logger.warning(
                "Ignoring --init/--update/database preload (%s): the evented "
                "server does not load registries at startup. Run the module "
                "install through the main server.",
                ",".join(preload),
            )
        if stop:
            self.logger.warning(
                "Ignoring --stop-after-init: the evented server has no "
                "initialisation phase to stop after, and will serve until "
                "signalled."
            )
        try:
            self.start()
        finally:
            self.stop()
        return None
