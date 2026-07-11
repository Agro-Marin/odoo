"""Threaded and evented HTTP servers.

* ``ThreadedServer`` — the default single-process server: a threaded werkzeug
  WSGI server plus in-process cron threads.
* ``EventServer`` — the evented/websocket long-polling server, run as the
  dedicated ``odoo-bin evented`` subprocess in prefork mode.  Despite the
  legacy naming around it (``gevent_port``, ``limit_memory_soft_gevent`` —
  kept for operator-config compatibility), this fork dropped gevent: it is a
  plain threaded werkzeug server whose requests hold the socket open for
  websocket traffic.

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
import werkzeug.serving

from odoo import db
from odoo.modules.registry import Registry
from odoo.tools import OrderedSet, config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks

from . import lifecycle  # mutated for ``server_phoenix`` (single source of truth)
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
    cron_database_list,
    over_memory_soft_limit,
)
from .lifecycle import preload_registries
from .wsgi import RequestHandler, ThreadedWSGIServerReloadable

_logger = logging.getLogger("odoo.service.server")

# Cadence of the main-loop limit monitor (``process_limit``) while no limit is
# currently breached.  Decoupled from ``SLEEP_INTERVAL`` (60 s), which made
# ``limit_time_real`` / memory-soft-limit enforcement up to a full minute late
# in threaded mode; the check itself is microseconds (``threading.enumerate``
# plus one ``/proc`` RSS read), so a 5 s cadence costs nothing measurable —
# the prefork master polls its workers every 4 s (``beat``) for the same job.
# Once a breach IS detected, ``run()`` switches to its own 1 s drain loop.
LIMIT_MONITOR_INTERVAL_S = 5.0


class ThreadedServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.main_thread_id = threading.current_thread().ident
        # Number of quit signals received; ``run()`` exits its loop once > 0.
        self.quit_signals_received = 0

        self.httpd = None
        self.limits_reached_threads = set()
        self.limit_reached_time = None
        # Cached psutil.Process — see Worker.start for rationale.
        self._process_handle = psutil.Process(os.getpid())

    def signal_handler(self, sig: int, frame: Any) -> None:
        if sig in [signal.SIGINT, signal.SIGTERM]:
            # shutdown on kill -INT or -TERM
            self.quit_signals_received += 1
            if self.quit_signals_received > 1:
                # Forced shutdown.  ``os.write`` to fd 2 is a single
                # async-signal-safe syscall; ``sys.stderr.write`` could deadlock
                # on the buffer lock if the signal landed mid-write.
                os.write(2, b"Forced shutdown.\n")
                os._exit(0)
            # interrupt run() to start shutdown
            raise KeyboardInterrupt
        if hasattr(signal, "SIGXCPU") and sig == signal.SIGXCPU:
            # async-signal-safe write (see the forced-shutdown note above).
            os.write(2, b"CPU time limit exceeded! Shutting down immediately\n")
            os._exit(0)
        elif _SIGHUP_AVAILABLE and sig == signal.SIGHUP:
            # restart on kill -HUP (POSIX only); write through ``lifecycle`` so
            # every reader sees the same binding.
            lifecycle.server_phoenix = True
            self.quit_signals_received += 1
            # interrupt run() to start shutdown
            raise KeyboardInterrupt

    def process_limit(self) -> None:
        memory = over_memory_soft_limit(
            self._process_handle, config["limit_memory_soft"]
        )
        if memory is not None:
            self.logger.warning("Server memory limit (%s) reached.", memory)
            self.limits_reached_threads.add(threading.current_thread())

        now = time.monotonic()
        for thread in threading.enumerate():
            thread_type = getattr(thread, "type", None)
            # Limit cron, job and HTTP threads (websockets excluded).  Match on
            # ``type``, not ``daemon``: HTTP threads are daemon, so a
            # ``not daemon`` filter would drop them and make ``limit_time_real``
            # inert.
            if thread_type in ("http", "cron", "job"):
                # Snapshot start_time once: the worker sets it to None between
                # units of work, so reading it twice (guard + subtraction) can
                # race into ``now - None`` -> TypeError, which would crash the
                # monitor loop (and the whole --workers=0 server) since it only
                # catches KeyboardInterrupt.  The race window is wide on the
                # free-threaded build this fork targets.
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
        # Clean-up threads that are no longer alive
        # e.g. threads that exceeded their real time,
        # but which finished before the server could restart.
        for thread in list(self.limits_reached_threads):
            if not thread.is_alive():
                self.limits_reached_threads.remove(thread)
        if self.limits_reached_threads:
            self.limit_reached_time = self.limit_reached_time or time.monotonic()
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
        # Steve Reich timing style with thundering herd mitigation.
        #
        # On startup, all workers bind on a notification channel in
        # postgres so they can be woken up at will. At worst they wake
        # up every SLEEP_INTERVAL with a jitter. The jitter creates a
        # chorus effect that helps distribute on the timeline the moment
        # when individual worker wake up.
        #
        # On NOTIFY, all workers are awaken at the same time, sleeping
        # just a bit prevents they all poll the database at the exact
        # same time. This is known as the thundering herd effect.

        cron_logger = self.logger.getChild(f"{label}{number}")
        cron_logger.info("Alive")

        # Sentinels returned by ``_run_cron`` to let the caller log the
        # actual exit reason rather than always saying "max age reached".
        RECYCLE_MAX_AGE = "max_age"
        RECYCLE_CONN_LOST = "connection_lost"

        def _run_cron(cr):
            pg_conn = cr.connection
            # Arm LISTEN on our channel (no-op on a replica).  This connection
            # is recycled on the age limit, so the idle-session timeout is left
            # as configured (unlike the prefork workers' persistent connection).
            arm_cron_listen(cr, cron_logger, channel=channel)
            cr.commit()
            # Both timestamps are monotonic: wall-clock jumps (NTP slew, DST,
            # manual clock correction) would otherwise mis-schedule the
            # full-scan pass. Initialized far in the past so the first tick
            # always triggers a full scan.
            check_all_time = float("-inf")
            all_db_names = []
            alive_time = time.monotonic()
            with selectors.DefaultSelector() as _sel:
                _sel.register(pg_conn, selectors.EVENT_READ)
                while (
                    config["limit_time_worker_cron"] <= 0
                    or (time.monotonic() - alive_time)
                    <= config["limit_time_worker_cron"]
                ):
                    _sel.select(timeout=SLEEP_INTERVAL + number)
                    # Random stagger after wake so concurrent crons reacting to
                    # the same NOTIFY don't all poll PG at once (thundering
                    # herd).  Shared constant keeps it in sync with
                    # ``WorkerCron.sleep``.
                    time.sleep(random.uniform(0, CRON_NOTIFY_JITTER_MAX_S))
                    try:
                        notified = drain_cron_notifies(pg_conn, channel=channel)
                    except Exception:
                        if pg_conn.closed:
                            # connection closed, exit the loop with an
                            # explicit sentinel so the outer loop can log
                            # "connection lost" instead of "max age reached".
                            return RECYCLE_CONN_LOST
                        raise

                    if time.monotonic() - SLEEP_INTERVAL > check_all_time:
                        # check all databases
                        # last time we checked them was `now - SLEEP_INTERVAL`
                        check_all_time = time.monotonic()
                        # process notified databases first, then the other ones
                        all_db_names = OrderedSet(cron_database_list())
                        db_names = order_notified_first(notified, all_db_names)
                    else:
                        # restrict to notified databases only
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
                        thread.start_time = None
            return RECYCLE_MAX_AGE

        while True:
            try:
                conn = db.db_connect("postgres")
                with contextlib.closing(conn.cursor()) as cr:
                    reason = _run_cron(cr)
                # No explicit ``cr.connection.close()``: ``"postgres"`` is in
                # ``Cursor._close``'s never-pool set, so closing the cursor
                # already discards the connection (``give_back(keep_in_pool=
                # False)``) — which is the recycle we want.
                if reason == RECYCLE_CONN_LOST:
                    cron_logger.warning("Postgres connection lost, reconnecting...")
                else:
                    cron_logger.info(
                        "Max age (%ss) reached, recycling pg connection",
                        config["limit_time_worker_cron"],
                    )
            except SystemExit:
                raise
            except BaseException:
                cron_logger.critical(
                    "Uncaught error in main loop, retrying in 5s...",
                    exc_info=True,
                )
                time.sleep(5)

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
        self.httpd = ThreadedWSGIServerReloadable(self.interface, self.port, self.app)
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
            # SIGCHLD is intentionally NOT installed: ThreadedServer forks no
            # worker children (only short-lived pg_dump/pg_restore subprocesses,
            # reaped by ``subprocess.run``).  A handler would only cause spurious
            # wakeups of the main loop's ``time.sleep``.
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

        if config["test_enable"] or (config["http_enable"] and not stop):
            # some tests need the http daemon to be available...
            self.http_spawn()

    def stop(self) -> None:
        """Shut down the WSGI server, waiting briefly for non-daemon threads.

        Every thread ``ThreadedServer`` spawns (HTTP, cron, WSGI listener,
        watcher) is daemon and dies with the process, so the join loop skips
        them; it exists to give *application-spawned* non-daemon threads up to
        one second to finish.  It busy-waits (``join(0.05)`` + ``sleep(0.05)``)
        rather than one long ``join()`` because ``Thread.join`` masks signals,
        and a second SIGINT must still force the shutdown.
        """
        if lifecycle.server_phoenix:
            self.logger.info("Initiating server reload")
        else:
            self.logger.info("Initiating shutdown")
            self.logger.info(
                "Hit CTRL-C again or send a second signal to force the shutdown."
            )

        stop_time = time.monotonic()

        if self.httpd:
            self.httpd.shutdown()

        super().stop()

        # Join non-daemon threads before exit, busy-waiting so a second signal
        # can still force shutdown (``Thread.join`` masks signals).
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
                    # Busy-wait (join masks signals) for requests to finish, up to 1s.
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
        """Start the http server and the cron thread then wait for a signal.

        The first SIGINT or SIGTERM signal will initiate a graceful shutdown while
        a second one if any will force an immediate exit.
        """
        with Registry._lock:
            self.start(stop=stop)
            rc = preload_registries(preload)

        if stop:
            if config["test_enable"]:
                from odoo.tests.result import _logger as logger

                with Registry.registries._lock:
                    # ``db_name`` not ``db``: avoid shadowing the module-level
                    # ``from odoo import db`` in scope here.
                    for db_name, registry in Registry.registries.items():
                        report = registry._assertion_report
                        log = (
                            logger.error
                            if not report.wasSuccessful()
                            else (
                                logger.warning if not report.testsRun else logger.info
                            )
                        )
                        log("%s when loading database %r", report, db_name)
            self.stop()
            return rc

        self.cron_spawn()
        self.job_spawn()

        # Wait for a first signal to be handled. (time.sleep will be interrupted
        # by the signal handler)
        try:
            while self.quit_signals_received == 0:
                self.process_limit()
                if self.limit_reached_time:
                    has_other_valid_requests = self._has_other_http_requests()
                    if (
                        not has_other_valid_requests
                        or (time.monotonic() - self.limit_reached_time) > SLEEP_INTERVAL
                    ):
                        # Wait (up to 1 min) until only the limit-exceeding
                        # requests remain, then reload.
                        self.logger.info(
                            "Dumping stacktrace of limit exceeding threads before reloading"
                        )
                        dumpstacks(
                            thread_idents=[
                                thread.ident for thread in self.limits_reached_threads
                            ]
                        )
                        self.reload()
                        # ``reload`` sends SIGHUP: the handler sets
                        # ``server_phoenix`` and bumps ``quit_signals_received``,
                        # so the loop exits and the server restarts after stop.
                    else:
                        time.sleep(1)
                else:
                    time.sleep(LIMIT_MONITOR_INTERVAL_S)
        except KeyboardInterrupt:
            pass

        self.stop()
        return None

    def _has_other_http_requests(self) -> bool:
        """Return True if an HTTP request that has NOT exceeded a limit is in flight.

        ``run()``'s reload gate waits (up to ``SLEEP_INTERVAL``) for unrelated
        in-flight requests to drain, so a limit breach on one request doesn't
        abort others.  HTTP threads are identified by ``type == "http"``, never
        ``not t.daemon`` (they ARE daemon — that filter would make this always
        False and reload immediately); ``limits_reached_threads`` membership
        separates the offenders from the others.
        """
        return any(
            t not in self.limits_reached_threads
            for t in threading.enumerate()
            if getattr(t, "type", None) == "http"
        )

    def reload(self) -> None:
        """Trigger a graceful reload via ``lifecycle.restart``.

        Delegates rather than calling ``os.kill(self.pid, SIGHUP)`` directly,
        which would raise on Windows (no SIGHUP).  ``lifecycle.restart`` handles
        both: SIGHUP on POSIX, a background ``_reexec`` thread on Windows.
        """
        lifecycle.restart()


class EventServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.port = config["gevent_port"]
        self.httpd = None
        # Set here (not lazily in ``watchdog``) so ``process_limits`` can't hit
        # an ``AttributeError`` if call order changes.
        self.ppid = os.getppid()
        # Cached psutil.Process — see Worker.start for rationale.
        self._process_handle = psutil.Process(self.pid)

    def process_limits(self) -> None:
        restart = False
        new_ppid = os.getppid()
        if self.ppid != new_ppid:
            # Log the reparenting itself (old -> new ppid), not ``self.pid``
            # which is unchanged and useless for diagnosing what happened.
            self.logger.warning("Parent changed: %s -> %s", self.ppid, new_ppid)
            restart = True
        limit_memory_soft = (
            config["limit_memory_soft_gevent"] or config["limit_memory_soft"]
        )
        memory = over_memory_soft_limit(self._process_handle, limit_memory_soft)
        if memory is not None:
            # RSS not VMS: see the ``memory_info`` docstring.
            self.logger.warning("RSS memory soft-limit reached: %s bytes", memory)
            restart = True
        if restart:
            os.kill(self.pid, signal.SIGTERM)

    def watchdog(self, beat: int = 4) -> None:
        """Periodically check memory and parent PID; send SIGTERM if limits exceeded."""
        self.ppid = os.getppid()
        while True:
            self.process_limits()
            time.sleep(beat)

    def _quit_signal_handler(self, sig: int, frame: Any) -> None:
        """Turn SIGINT/SIGTERM into a graceful shutdown of the evented server.

        ``serve_forever()`` runs on the main thread, so the handler must NOT
        call ``self.httpd.shutdown()`` directly — it would block waiting for
        ``serve_forever``, which is suspended in this handler (deadlock).
        Instead raise ``KeyboardInterrupt``.  ``serve_forever()`` does NOT catch
        it (verified) — it propagates out and ``start()`` handles it as a clean
        shutdown, so ``run()``'s ``finally`` reaches ``stop()`` and the
        ``on_stop`` hooks run (the bus websocket ``_kick_all`` /
        ``_close_notify_conn``, the dart-sass compiler).  Without that handling,
        the SIGTERM that systemd and the watchdog send would be logged as a
        fatal crash (CRITICAL + ``exit(1)``) instead of a graceful stop.
        """
        raise KeyboardInterrupt

    def start(self) -> None:
        if os.name == "posix":
            # SIGINT/SIGTERM → graceful stop (see ``_quit_signal_handler``).
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
        try:
            self.httpd.serve_forever()
        except SystemExit:
            raise
        except KeyboardInterrupt:
            # SIGINT/SIGTERM via ``_quit_signal_handler`` — a graceful shutdown,
            # NOT a crash.  ``serve_forever()`` does not catch KeyboardInterrupt,
            # so without this arm it would fall through to ``except BaseException``
            # and every normal stop (systemd, watchdog recycle) would log CRITICAL
            # and ``exit(1)`` — restart flapping and false alerts.  ``run()``'s
            # ``finally`` still calls ``stop()``, so the on_stop hooks run.
            self.logger.info("Evented/WebSocket service stopped")
        except BaseException as exc:
            self.logger.critical("Uncaught error in main loop", exc_info=True)
            raise SystemExit(1) from exc

    def stop(self) -> None:
        # ``self.httpd`` is ``None`` until ``start()`` builds it; guard so a
        # ``stop()`` from ``run()``'s ``finally`` after an early ``start()``
        # failure doesn't mask the real error.  After ``serve_forever`` returns,
        # ``shutdown()`` is a no-op (the shut-down event is already set).
        if self.httpd:
            self.httpd.shutdown()
        super().stop()

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        # ``finally`` guarantees ``stop()``'s ``on_stop`` hooks run on every
        # exit path from ``start()`` (signal, watchdog recycle, uncaught error).
        try:
            self.start()
        finally:
            self.stop()
        return None
