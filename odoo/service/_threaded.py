"""Threaded and evented HTTP servers — extracted from ``server.py``.

* ``ThreadedServer`` — the default dev/single-process server: a threaded
  werkzeug WSGI server plus in-process cron threads.
* ``EventServer`` — the gevent/evented long-polling server.

Both subclass ``CommonServer`` (``_base_server.py``).  ``server.py`` re-exports
both names for backward compatibility.
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
from ._cron import arm_cron_listen, drain_cron_notifies, order_notified_first
from ._helpers import (
    CRON_NOTIFY_JITTER_MAX_S,
    SLEEP_INTERVAL,
    cron_database_list,
    memory_info,
)
from .lifecycle import preload_registries
from .wsgi import RequestHandler, ThreadedWSGIServerReloadable

_logger = logging.getLogger("odoo.service.server")


class ThreadedServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.main_thread_id = threading.current_thread().ident
        # Variable keeping track of the number of calls to the signal handler defined
        # below. This variable is monitored by ``quit_on_signals()``.
        self.quit_signals_received = 0

        # self.socket = None
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
                # Forced shutdown: write directly to fd 2.  ``sys.stderr.write``
                # can block on the I/O buffer lock if the main thread was
                # mid-write when the signal landed — deadlocking the very
                # escape hatch this path exists to provide.  ``os.write`` is a
                # single async-signal-safe syscall (the prefork ``Worker``
                # handler follows the same rule).  ``logging.shutdown`` already
                # ran, so there is nothing to flush.
                os.write(2, b"Forced shutdown.\n")
                os._exit(0)
            # interrupt run() to start shutdown
            raise KeyboardInterrupt
        if hasattr(signal, "SIGXCPU") and sig == signal.SIGXCPU:
            # async-signal-safe write (see the forced-shutdown note above).
            os.write(2, b"CPU time limit exceeded! Shutting down immediately\n")
            os._exit(0)
        elif _SIGHUP_AVAILABLE and sig == signal.SIGHUP:
            # restart on kill -HUP (POSIX only).  Write through ``lifecycle``
            # (the single source of truth) so every reader — start(), the
            # autoreload watcher — sees the same binding.
            lifecycle.server_phoenix = True
            self.quit_signals_received += 1
            # interrupt run() to start shutdown
            raise KeyboardInterrupt

    def process_limit(self) -> None:
        memory = memory_info(self._process_handle)
        if config["limit_memory_soft"] and memory > config["limit_memory_soft"]:
            self.logger.warning("Server memory limit (%s) reached.", memory)
            self.limits_reached_threads.add(threading.current_thread())

        now = time.monotonic()
        for thread in threading.enumerate():
            thread_type = getattr(thread, "type", None)
            # Apply the limits to cron threads and HTTP requests; websocket
            # requests are excluded.  Match on thread ``type`` explicitly: HTTP
            # request threads are daemon threads, so any ``not thread.daemon``
            # filter would silently drop every HTTP thread and leave
            # ``limit_time_real`` inert in threaded mode.
            if thread_type in ("http", "cron"):
                if getattr(thread, "start_time", None):
                    thread_execution_time = now - thread.start_time
                    thread_limit_time_real = config["limit_time_real"]
                    if (
                        getattr(thread, "type", None) == "cron"
                        and config["limit_time_real_cron"]
                        and config["limit_time_real_cron"] > 0
                    ):
                        thread_limit_time_real = config["limit_time_real_cron"]
                    if (
                        thread_limit_time_real
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

        from odoo.addons.base.models.ir_cron import IrCron

        cron_logger = self.logger.getChild(f"cron{number}")
        cron_logger.info("Alive")

        # Sentinels returned by ``_run_cron`` to let the caller log the
        # actual exit reason rather than always saying "max age reached".
        RECYCLE_MAX_AGE = "max_age"
        RECYCLE_CONN_LOST = "connection_lost"

        def _run_cron(cr):
            pg_conn = cr.connection
            # Arm LISTEN cron_trigger (no-op on a replica).  This connection is
            # recycled on the age limit, so the idle-session timeout is left as
            # configured (unlike WorkerCron's persistent connection).
            arm_cron_listen(cr, cron_logger)
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
                    # Random stagger after wake — spreads concurrent crons
                    # reacting to the same NOTIFY so they don't all poll PG
                    # in the same millisecond (thundering herd).  The previous
                    # form ``number / 100`` was deterministic — for 4 cron
                    # threads it produced staggers of exactly 0, 0.01, 0.02,
                    # 0.03s every cycle, which is not what the docstring's
                    # "thundering herd mitigation" claim promises.  Uses the
                    # shared ``CRON_NOTIFY_JITTER_MAX_S`` constant so this
                    # value cannot drift from ``WorkerCron.sleep``.
                    time.sleep(random.uniform(0, CRON_NOTIFY_JITTER_MAX_S))
                    try:
                        notified = drain_cron_notifies(pg_conn)
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
                            IrCron._process_jobs(db_name)
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
                # No explicit ``cr.connection.close()`` here: ``"postgres"`` is in
                # ``Cursor._close``'s never-pool set, so closing the cursor already
                # discards (closes) the underlying connection via
                # ``pool.give_back(keep_in_pool=False)`` — which IS the recycle we
                # want.  Pre-closing it made ``_close``'s ``rollback()`` throw on
                # the dead connection (caught + DEBUG-logged) on every recycle.
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
        """Start the above runner function in a daemon thread.

        The thread is a typical daemon thread: it will never quit and must be
        terminated when the main process exits - with no consequence (the processing
        threads it spawns are not marked daemon).

        """
        for i in range(config["max_cron_threads"]):
            t = threading.Thread(
                target=self.cron_thread,
                args=(i,),
                name=f"odoo.service.cron.cron{i}",
                daemon=True,
            )
            t.type = "cron"
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
            # SIGCHLD is intentionally NOT installed here. ThreadedServer does
            # not fork worker children (that's PreforkServer); it only spawns
            # short-lived subprocesses for pg_dump / pg_restore during DB admin
            # operations. Those subprocesses are reaped by subprocess.run's
            # internal waitpid. Installing a Python handler would only cause
            # spurious wakeups of the main loop's time.sleep.
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
        """Shutdown the WSGI server, waiting briefly for non-daemon threads.

        All threads spawned by ``ThreadedServer`` itself (HTTP request,
        cron, the WSGI listener, the autoreload watcher) are daemon, so
        they are killed when the process exits and the join loop below
        skips them.  The loop catches *application-spawned* non-daemon
        threads — custom modules that start their own background work —
        so a graceful shutdown gives them up to one second to finish
        before forced termination.  The loop also runs a busy-wait
        (``thread.join(0.05)`` + ``time.sleep(0.05)``) instead of a
        single long ``join()`` so a second SIGINT can still trigger
        ``_force_quit()``: ``Thread.join`` masks signals.
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

        # Manually join() all threads before calling sys.exit() to allow a second signal
        # to trigger _force_quit() in case some non-daemon threads won't exit cleanly.
        # threading.Thread.join() should not mask signals.
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
                    # We wait for requests to finish, up to 1 second.
                    self.logger.debug("join and sleep")
                    # Need a busyloop here as thread.join() masks signals
                    # and would prevent the forced shutdown.
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
                    # ``db_name`` (not ``db``): the module-level ``from odoo import
                    # db`` is in scope here, and a ``db`` loop variable would
                    # shadow it — a footgun if any later edit references the
                    # module within this function.
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
                        # We wait there is no processing requests
                        # other than the ones exceeding the limits, up to 1 min,
                        # before asking for a reload.
                        self.logger.info(
                            "Dumping stacktrace of limit exceeding threads before reloading"
                        )
                        dumpstacks(
                            thread_idents=[
                                thread.ident for thread in self.limits_reached_threads
                            ]
                        )
                        self.reload()
                        # `reload` increments `self.quit_signals_received`
                        # and the loop will end after this iteration,
                        # therefore leading to the server stop.
                        # `reload` also sets the `server_phoenix` flag
                        # to tell the server to restart the server after shutting down.
                    else:
                        time.sleep(1)
                else:
                    time.sleep(SLEEP_INTERVAL)
        except KeyboardInterrupt:
            pass

        self.stop()
        return None

    def _has_other_http_requests(self) -> bool:
        """Return True if an HTTP request that has NOT exceeded a limit is in flight.

        ``run()``'s reload gate uses this to wait (up to ``SLEEP_INTERVAL``)
        for unrelated in-flight requests to drain before reloading, so a
        memory/time-limit breach on one request does not abort others.

        Request threads are tagged ``type == "http"`` and are **daemon**
        threads (``ThreadedWSGIServerReloadable`` sets ``daemon_threads =
        True``).  Identify them by ``type`` only — a ``not t.daemon`` filter
        would exclude every HTTP thread, make this always False, and fire the
        reload immediately, dropping concurrent in-flight requests (the same
        daemon-flag trap guarded against in ``process_limit``).
        ``limits_reached_threads`` membership decides which are "the offenders"
        vs. "others still working".
        """
        return any(
            t not in self.limits_reached_threads
            for t in threading.enumerate()
            if getattr(t, "type", None) == "http"
        )

    def reload(self) -> None:
        """Trigger a graceful reload, picking the right mechanism per OS.

        ``signal.SIGHUP`` does not exist on Windows: a direct
        ``os.kill(self.pid, signal.SIGHUP)`` would raise ``AttributeError``
        when ``ThreadedServer.run`` hits the ``limit_time_real`` reload
        path on a Windows host.  Delegate to ``lifecycle.restart`` which
        already handles both branches: SIGHUP on POSIX, a background
        ``_reexec`` thread on Windows.
        """
        lifecycle.restart()



class EventServer(CommonServer):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.port = config["gevent_port"]
        self.httpd = None
        # Initialized here (not lazily in ``watchdog``) so ``process_limits``
        # can never hit an ``AttributeError`` if its call order changes.
        # ``watchdog`` re-reads it once more before the loop; same value in the
        # same process.
        self.ppid = os.getppid()
        # Cached psutil.Process — see Worker.start for rationale.
        # ``self.pid`` was set by CommonServer.__init__.
        self._process_handle = psutil.Process(self.pid)

    def process_limits(self) -> None:
        restart = False
        if self.ppid != os.getppid():
            self.logger.warning("Parent changed: %s", self.pid)
            restart = True
        memory = memory_info(self._process_handle)
        limit_memory_soft = (
            config["limit_memory_soft_gevent"] or config["limit_memory_soft"]
        )
        if limit_memory_soft and memory > limit_memory_soft:
            # ``memory_info`` returns RSS (resident memory), not VMS — VMS is
            # unreliable on Python 3.13+ because the new allocator/GC reserves
            # large virtual ranges that never become resident.  See the
            # ``memory_info`` helper docstring.
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

        ``serve_forever()`` runs on THIS (main) thread, so the handler must
        NOT call ``self.httpd.shutdown()`` directly: ``shutdown()`` blocks
        until ``serve_forever`` acknowledges, but ``serve_forever`` is
        suspended executing this very handler — a deadlock.  Instead raise
        ``KeyboardInterrupt``, which werkzeug's ``serve_forever`` catches and
        returns from, so ``start()`` returns and ``run()`` reaches ``stop()``
        → ``super().stop()`` — running the ``on_stop`` hooks that matter to
        the longpolling process (``bus`` websocket ``_kick_all``,
        ``_close_notify_conn``, the dart-sass compiler).

        SIGINT already did this via the interpreter's default disposition;
        SIGTERM (what systemd/docker/k8s send, and what this server's own
        ``watchdog`` sends to recycle) previously had NO handler and hard-
        killed the process, skipping every ``on_stop`` hook.  Mirrors
        ``ThreadedServer.signal_handler``.
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
        except BaseException as exc:
            self.logger.critical("Uncaught error in main loop", exc_info=True)
            raise SystemExit(1) from exc

    def stop(self) -> None:
        # ``self.httpd`` is ``None`` until ``start()`` builds it; guard so a
        # ``stop()`` reached via the ``finally`` in ``run()`` after an early
        # ``start()`` failure doesn't mask the real error with an
        # ``AttributeError``.  Safe to call after ``serve_forever`` returned:
        # socketserver's ``finally`` already set the shut-down event, so this
        # ``shutdown()`` returns immediately rather than blocking.
        if self.httpd:
            self.httpd.shutdown()
        super().stop()

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        # ``finally`` guarantees the ``on_stop`` cleanup hooks run on every
        # exit path from ``start()`` — graceful signal, watchdog recycle, or
        # an uncaught error re-raised as ``SystemExit`` — not just the lucky
        # ones where ``serve_forever`` happened to return.
        try:
            self.start()
        finally:
            self.stop()
        return None


