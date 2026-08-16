"""Threaded and evented HTTP servers.

* ``ThreadedServer`` — the default single-process server: a threaded werkzeug
  WSGI server plus in-process cron threads.
* ``EventServer`` — the evented/websocket long-polling server, run as the
  dedicated ``odoo-bin evented`` subprocess in prefork mode.  Despite the legacy
  naming (``gevent_port``, ``limit_memory_soft_gevent`` — kept for config
  compatibility), this fork dropped gevent: it is a plain threaded werkzeug
  server whose requests hold the socket open for websocket traffic.

Both subclass ``CommonServer`` (``_base_server.py``).
"""

from __future__ import annotations

import contextlib
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
from odoo.modules.registry import Registry
from odoo.tools import OrderedSet, config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks

from . import lifecycle
from ._base_server import _SIGHUP_AVAILABLE, CommonServer
from ._cron import (
    CRON_TRIGGER_CHANNEL,
    JOB_QUEUE_CHANNEL,
    arm_cron_listen,
    drain_cron_notifies,
    order_notified_first,
)
from ._helpers import (
    CRON_NOTIFY_JITTER_MAX_S,
    SLEEP_INTERVAL,
    capped_backoff,
    cron_database_list,
    over_memory_soft_limit,
)
from .lifecycle import preload_registries
from .wsgi import RequestHandler, ThreadedWSGIServerReloadable

_logger = logging.getLogger("odoo.service.server")

LIMIT_MONITOR_INTERVAL_S = 5.0


class ThreadedServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.main_thread_id = threading.current_thread().ident
        self.quit_signals_received = 0

        self.httpd = None
        self.limits_reached_threads = set()
        self.limit_reached_time = None
        self._stop_after_init = False
        self._process_handle = psutil.Process(os.getpid())

    def signal_handler(self, sig: int, frame: Any) -> None:
        if sig in [signal.SIGINT, signal.SIGTERM]:
            self.quit_signals_received += 1
            if self.quit_signals_received > 1:
                os.write(2, b"Forced shutdown.\n")
                os._exit(0)
            raise KeyboardInterrupt
        if hasattr(signal, "SIGXCPU") and sig == signal.SIGXCPU:
            os.write(2, b"CPU time limit exceeded! Shutting down immediately\n")
            os._exit(0)
        elif _SIGHUP_AVAILABLE and sig == signal.SIGHUP:
            lifecycle.server_phoenix = True
            self.quit_signals_received += 1
            raise KeyboardInterrupt

    def process_limit(self) -> None:
        memory = over_memory_soft_limit(
            self._process_handle, config["limit_memory_soft"]
        )
        memory_over_limit = memory is not None
        if memory_over_limit:
            self.logger.warning("Server memory limit (%s) reached.", memory)

        now = time.monotonic()
        for thread in threading.enumerate():
            thread_type = getattr(thread, "type", None)
            if thread_type in ("http", "cron", "job"):
                start_time = getattr(thread, "start_time", None)
                if start_time:
                    thread_execution_time = now - start_time
                    thread_limit_time_real = config["limit_time_real"]
                    if (
                        thread_type in ("cron", "job")
                        and config["limit_time_real_cron"]
                        and config["limit_time_real_cron"] > 0
                    ):
                        thread_limit_time_real = config["limit_time_real_cron"]
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

    def _listen_thread(
        self,
        number: int,
        *,
        channel: str,
        process_jobs: Any,
        label: str,
    ) -> None:
        """Shared LISTEN/NOTIFY worker loop of the cron and job threads.

        ``process_jobs(db_name)`` is the per-database unit of work
        (``IrCron._process_jobs`` / ``IrJob._process_jobs``); ``channel`` the
        PG NOTIFY channel armed on the recycled ``postgres`` connection.
        """

        cron_logger = self.logger.getChild(f"{label}{number}")
        cron_logger.info("Alive")

        RECYCLE_MAX_AGE = "max_age"
        RECYCLE_CONN_LOST = "connection_lost"

        def _run_cron(cr):
            pg_conn = cr.connection
            arm_cron_listen(
                cr,
                cron_logger,
                channel=channel,
                disable_idle_timeout=True,
            )
            cr.commit()
            check_all_time = float("-inf")
            all_db_names = []
            alive_time = time.monotonic()
            first_pass = True
            with selectors.DefaultSelector() as _sel:
                _sel.register(pg_conn, selectors.EVENT_READ)
                while (
                    config["limit_time_worker_cron"] <= 0
                    or (time.monotonic() - alive_time)
                    <= config["limit_time_worker_cron"]
                ):
                    _sel.select(timeout=0 if first_pass else SLEEP_INTERVAL + number)
                    first_pass = False
                    time.sleep(random.uniform(0, CRON_NOTIFY_JITTER_MAX_S))
                    try:
                        notified = drain_cron_notifies(pg_conn, channel=channel)
                    except Exception:
                        if pg_conn.closed:
                            return RECYCLE_CONN_LOST
                        raise

                    if time.monotonic() - SLEEP_INTERVAL > check_all_time:
                        check_all_time = time.monotonic()
                        all_db_names = OrderedSet(cron_database_list())
                        db_names = order_notified_first(notified, all_db_names)
                    else:
                        db_names = notified.intersection(all_db_names)
                        if not db_names:
                            continue

                    cron_logger.debug("polling for jobs (notified: %s)", notified)
                    for db_name in db_names:
                        thread = threading.current_thread()
                        thread.start_time = time.monotonic()
                        try:
                            process_jobs(db_name)
                        except Exception:
                            cron_logger.warning(
                                "Uncaught error for database %s",
                                db_name,
                                exc_info=True,
                            )
                        finally:
                            thread.start_time = None
            return RECYCLE_MAX_AGE

        reconnect_attempts = 0
        while True:
            try:
                conn = db.db_connect("postgres")
                with contextlib.closing(conn.cursor()) as cr:
                    reason = _run_cron(cr)
                reconnect_attempts = 0
                if reason == RECYCLE_CONN_LOST:
                    cron_logger.warning("Postgres connection lost, reconnecting...")
                else:
                    cron_logger.info(
                        "Max age (%ss) reached, recycling pg connection",
                        config["limit_time_worker_cron"],
                    )
            except SystemExit:
                raise
            except (psycopg.OperationalError, PoolError) as exc:
                reconnect_attempts += 1
                backoff = capped_backoff(reconnect_attempts)
                cron_logger.warning(
                    "Postgres unavailable (attempt %d): %s; retrying in %ds",
                    reconnect_attempts,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
            except Exception:
                reconnect_attempts += 1
                backoff = capped_backoff(reconnect_attempts)
                cron_logger.critical(
                    "Uncaught error in cron main loop; retrying in %ds...",
                    backoff,
                    exc_info=True,
                )
                time.sleep(backoff)

    def cron_spawn(self) -> None:
        """Start ``max_cron_threads`` daemon threads, each running ``cron_thread``."""
        for i in range(config["max_cron_threads"]):
            t = threading.Thread(
                target=self.cron_thread,
                args=(i,),
                name=f"odoo.service.cron.cron{i}",
                daemon=True,
            )
            t.type = "cron"
            t.start()

    def job_spawn(self) -> None:
        """Start ``job_workers`` daemon threads, each running ``job_thread``."""
        for i in range(config["job_workers"]):
            t = threading.Thread(
                target=self.job_thread,
                args=(i,),
                name=f"odoo.service.job.job{i}",
                daemon=True,
            )
            t.type = "job"
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
        if os.name == "posix":
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
            signal.signal(signal.SIGHUP, self.signal_handler)
            signal.signal(signal.SIGXCPU, self.signal_handler)
            signal.signal(signal.SIGQUIT, dumpstacks)
            signal.signal(signal.SIGUSR1, log_ormcache_stats)
            signal.signal(signal.SIGUSR2, log_ormcache_stats)
        elif os.name == "nt":
            import win32api

            win32api.SetConsoleCtrlHandler(
                lambda sig: self.signal_handler(sig, None), 1
            )

        if config["http_enable"] and (config["test_enable"] or not stop):
            self.http_spawn()

    def stop(self) -> None:
        """Shut down the WSGI server, waiting briefly for non-daemon threads.

        Every thread ``ThreadedServer`` spawns is daemon, so the join loop is
        there to give application-spawned non-daemon threads up to one second.
        It busy-waits (``join(0.05)`` + ``sleep(0.05)``) rather than one long
        ``join()`` because ``Thread.join`` masks signals, and a second SIGINT
        must still force the shutdown.
        """
        if lifecycle.server_phoenix:
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
        """Start the http server and the cron thread, then wait for a signal.

        A first SIGINT or SIGTERM starts a graceful shutdown; a second forces
        an immediate exit.

        The whole body runs under one ``try/except KeyboardInterrupt`` with
        ``stop()`` in a ``finally``: this server raises ``KeyboardInterrupt``
        from its signal handler, so a quit signal (INT/TERM/HUP) arriving during
        ``preload_registries`` — common under ``--dev=reload`` when a file is
        saved mid-startup — or during the drain must still route into the normal
        shutdown, run the on-stop hooks, and (for SIGHUP, which also set
        ``server_phoenix``) let ``lifecycle.start`` re-exec.  A bare escape would
        skip cleanup and silently downgrade a reload to a crash.
        """
        rc: int | None = None
        self._stop_after_init = stop
        try:
            with Registry._lock:
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
                self.process_limit()
                if self.limit_reached_time:
                    has_other_valid_requests = self._has_other_http_requests()
                    if (
                        not has_other_valid_requests
                        or (time.monotonic() - self.limit_reached_time) > SLEEP_INTERVAL
                    ):
                        self.logger.info(
                            "Dumping stacktrace of limit exceeding threads before reloading"
                        )
                        dumpstacks(
                            thread_idents=[
                                thread.ident for thread in self.limits_reached_threads
                            ]
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
        """Return True if a non-limit-exceeding HTTP request is in flight.

        ``run()``'s reload gate uses this to wait for unrelated requests to drain
        so a limit breach on one doesn't abort others.  HTTP threads are matched
        by ``type == "http"`` (they ARE daemon, so a ``not daemon`` filter would
        always be False); ``limits_reached_threads`` separates the offenders.
        """
        return any(
            t not in self.limits_reached_threads
            for t in threading.enumerate()
            if getattr(t, "type", None) == "http"
        )

    def reload(self) -> None:
        """Trigger a graceful reload via ``lifecycle.restart``.

        Delegates rather than ``os.kill(self.pid, SIGHUP)`` (no SIGHUP on
        Windows); ``lifecycle.restart`` handles both platforms.
        """
        lifecycle.restart()


class EventServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.port = config["gevent_port"]
        self.httpd = None
        self.ppid = os.getppid()
        self._process_handle = psutil.Process(self.pid)

    def process_limits(self) -> None:
        restart = False
        new_ppid = os.getppid()
        if self.ppid != new_ppid:
            self.logger.warning("Parent changed: %s -> %s", self.ppid, new_ppid)
            restart = True
        limit_memory_soft = (
            config["limit_memory_soft_gevent"] or config["limit_memory_soft"]
        )
        memory = over_memory_soft_limit(self._process_handle, limit_memory_soft)
        if memory is not None:
            self.logger.warning("RSS memory soft-limit reached: %s bytes", memory)
            restart = True
        if restart:
            os.kill(self.pid, signal.SIGTERM)

    def watchdog(self, beat: int = 4) -> None:
        """Periodically check memory and parent PID; send SIGTERM if limits exceeded."""
        self.ppid = os.getppid()
        while True:
            try:
                self.process_limits()
            except Exception:
                self.logger.warning(
                    "Evented watchdog check failed; retrying in %ss",
                    beat,
                    exc_info=True,
                )
            time.sleep(beat)

    def _quit_signal_handler(self, sig: int, frame: Any) -> None:
        """Turn SIGINT/SIGTERM into a graceful shutdown of the evented server.

        ``serve_forever()`` runs on the main thread, so calling
        ``self.httpd.shutdown()`` here would deadlock (it waits for the
        serve_forever this handler suspends).  Raise ``KeyboardInterrupt``
        instead: serve_forever doesn't catch it, so it propagates to ``start()``
        which handles it as a clean stop and lets ``run()``'s ``finally`` run the
        ``on_stop`` hooks — otherwise a routine SIGTERM logs as a fatal crash.
        """
        raise KeyboardInterrupt

    def start(self) -> None:
        if os.name == "posix":
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
        try:
            self.start()
        finally:
            self.stop()
        return None
