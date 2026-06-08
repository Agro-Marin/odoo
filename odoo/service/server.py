import contextlib
import errno
import logging
import os
import platform
import random
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import psutil
import werkzeug.serving

if os.name == "posix":
    # Unix only for workers
    import fcntl

# Optional process names for workers
try:
    from setproctitle import setproctitle
except ImportError:

    def setproctitle(x: str) -> None:
        return None


from odoo import db
from odoo.modules.registry import Registry
from odoo.tools import OrderedSet, config
from odoo.tools.cache import log_ormcache_stats
from odoo.tools.misc import dumpstacks, stripped_sys_argv

from . import lifecycle  # mutated for ``server_phoenix`` (single source of truth)

# Process-control helpers and cron timing constants live in ``_helpers``
# (extracted to break the prior server.py <-> _worker.py circular import).
# Imported here for own use by ``ThreadedServer.cron_thread`` /
# ``ThreadedServer.process_limit`` etc., AND re-exported as public
# attributes of this module so external callers keep working with
# ``from odoo.service.server import cron_database_list`` etc.
from ._helpers import (
    CRON_NOTIFY_JITTER_MAX_S,
    SLEEP_INTERVAL,
    cron_database_list,
    empty_pipe,
    memory_info,
    set_limit_memory_hard,
)

# ``FSWatcherBase`` is re-exported as a public attribute of this module
# because ``tests/service/test_server.py`` (and any future callers
# extending the watcher) reach it via ``odoo.service.server.FSWatcherBase``.
# The leading-underscore ``odoo.service._watcher`` is the canonical home
# but signals "private"; this re-export gives external callers a stable,
# non-underscored import path.
from ._watcher import FSWatcherBase  # noqa: F401 — public re-export

# Worker classes — re-exported from ``_worker``.  Now that the helpers
# above live in ``_helpers``, ``_worker`` imports them directly from
# there and no longer loops back through ``server.py`` — the
# partial-module-load dance is gone.
from ._worker import (
    CpuTimeLimitExceeded,
    Worker,
    WorkerCron,
    WorkerHTTP,
)

# Lifecycle entry points extracted to a sibling module; re-exported here
# so ``cli/shell.py`` (``server.start(...)``) and ``http/application.py``
# (``from odoo.service.server import load_server_wide_modules``) keep
# working.  The ``server`` and ``server_phoenix`` mutable globals are NOT
# re-imported here (that would capture a snapshot); the module-level
# ``__getattr__`` below forwards reads to ``lifecycle``.
from .lifecycle import (
    _reexec,
    load_server_wide_modules,
    preload_registries,
    restart,
    start,
)

# WSGI handlers extracted to a sibling module; re-exported here for
# backwards compat (addons/, cli/, bus/ all import from odoo.service.server).
from .wsgi import (
    BaseWSGIServerNoBind,
    CommonRequestHandler,
    LoggingBaseWSGIServerMixIn,
    RequestHandler,
    ThreadedWSGIServerReloadable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ``signal.SIGHUP`` is POSIX-only. On Windows it does not exist on the
# ``signal`` module. Rather than monkey-patching ``signal.SIGHUP = -1``
# into the stdlib module (which pollutes every importer of ``signal`` in
# the process), use a local sentinel and compare via ``hasattr`` at each
# call site where a signal could reach the handler on both platforms.
_SIGHUP_AVAILABLE = hasattr(signal, "SIGHUP")

_logger = logging.getLogger(__name__)


# ``server_phoenix`` lives in ``lifecycle`` (canonical) but is also exposed
# here as a module attribute so existing callers — notably
# ``_watcher._trigger_restart`` and the test suite — can keep doing
# ``from odoo.service.server import server_phoenix``.  Mutations on this
# module (``ThreadedServer.signal_handler``, ``PreforkServer.process_signals``,
# ``PreforkServer.stop``) write through ``lifecycle.server_phoenix = …``
# instead of declaring ``global server_phoenix`` so that every reader sees
# the same binding.
def __getattr__(name: str) -> Any:
    """Module-level fallback so ``server.server_phoenix`` etc. follow the
    canonical binding in ``lifecycle`` instead of a stale snapshot."""
    if name in ("server", "server_phoenix"):
        return getattr(lifecycle, name)
    raise AttributeError(f"module 'odoo.service.server' has no attribute {name!r}")

# ----------------------------------------------------------
# Servers: Threaded, Evented and Prefork
# ----------------------------------------------------------
# (FSWatcher classes have moved to ``odoo.service._watcher``.)


# Module-level registry of on-stop callbacks. Stop hooks are process-global —
# they fire once per process lifetime regardless of which server class is
# running. A class-level list on CommonServer would also be "shared across
# all subclasses" (the same object), but that's incidental to class
# inheritance; the real intent is "one list per process". Keeping it at the
# module level makes that explicit and removes the surprise that different
# server instances share state via their class. The previous
# ``CommonServer._on_stop_funcs`` alias was removed: a reassignment of the
# class attribute would silently desync from this module-level list while
# ``CommonServer.on_stop`` continued appending to the original.
_ON_STOP_FUNCS: list[Callable] = []


class CommonServer:
    def __init__(self, app: Any) -> None:
        self.app = app
        # config
        self.interface: str = config["http_interface"] or "0.0.0.0"
        self.port: int = config["http_port"]
        # runtime
        self.pid: int = os.getpid()
        self.logger = _logger.getChild(self.__class__.__name__)

    def close_socket(self, sock: socket.socket) -> None:
        """Closes a socket instance cleanly
        :param sock: the network socket to close
        :type sock: socket.socket
        """
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError as e:
            if e.errno == errno.EBADF:
                # Werkzeug > 0.9.6 closes the socket itself (see commit
                # https://github.com/mitsuhiko/werkzeug/commit/4d8ca089)
                return
            # On OSX, socket shutdowns both sides if any side closes it
            # causing an error 57 'Socket is not connected' on shutdown
            # of the other side (or something), see
            # http://bugs.python.org/issue4397
            # note: stdlib fixed test, not behavior
            if e.errno != errno.ENOTCONN or platform.system() not in [
                "Darwin",
                "Windows",
            ]:
                raise
        sock.close()

    @classmethod
    def on_stop(cls, func: Callable) -> None:
        """Register a cleanup function to be executed when the server stops."""
        _ON_STOP_FUNCS.append(func)

    def stop(self) -> None:
        for func in _ON_STOP_FUNCS:
            try:
                self.logger.debug("on_close call %s", func)
                func()
            except Exception:
                self.logger.warning("Exception in %s", func.__name__, exc_info=True)


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
                # logging.shutdown was already called at this point.
                sys.stderr.write("Forced shutdown.\n")
                os._exit(0)
            # interrupt run() to start shutdown
            raise KeyboardInterrupt
        if hasattr(signal, "SIGXCPU") and sig == signal.SIGXCPU:
            sys.stderr.write("CPU time limit exceeded! Shutting down immediately\n")
            sys.stderr.flush()
            os._exit(0)
        elif _SIGHUP_AVAILABLE and sig == signal.SIGHUP:
            # restart on kill -HUP (POSIX only).  Write through lifecycle so
            # every reader (start(), the autoreload watcher, this module's
            # __getattr__) sees the same binding.
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
            # We apply the limits on cron threads and HTTP requests,
            # websocket requests excluded.  The previous filter
            # ``(not thread.daemon and thread_type != "websocket") or
            # thread_type == "cron"`` excluded HTTP request threads after
            # they were switched to ``daemon=True`` (commit cf17496) — the
            # ``not thread.daemon`` branch silently dropped every HTTP
            # thread, leaving ``limit_time_real`` inert in threaded mode.
            # Match thread type explicitly instead.
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
                            "Thread %s virtual real time limit (%d/%ds) reached.",
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
            # LISTEN / NOTIFY doesn't work in recovery mode
            cr.execute("SELECT pg_is_in_recovery()")
            in_recovery = cr.fetchone()[0]
            if not in_recovery:
                cr.execute("LISTEN cron_trigger")
            else:
                cron_logger.warning(
                    "PG cluster in recovery mode, cron trigger not activated"
                )
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
                        notified = OrderedSet(
                            notif.payload
                            for notif in pg_conn.notifies(timeout=0)
                            if notif.channel == "cron_trigger"
                        )
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
                        db_names = [
                            *(db for db in notified if db in all_db_names),
                            *(db for db in all_db_names if db not in notified),
                        ]
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
                    cr.connection.close()
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
                    for db, registry in Registry.registries.items():
                        report = registry._assertion_report
                        log = (
                            logger.error
                            if not report.wasSuccessful()
                            else (
                                logger.warning if not report.testsRun else logger.info
                            )
                        )
                        log("%s when loading database %r", report, db)
            self.stop()
            return rc

        self.cron_spawn()

        # Wait for a first signal to be handled. (time.sleep will be interrupted
        # by the signal handler)
        try:
            while self.quit_signals_received == 0:
                self.process_limit()
                if self.limit_reached_time:
                    has_other_valid_requests = any(
                        not t.daemon and t not in self.limits_reached_threads
                        for t in threading.enumerate()
                        if getattr(t, "type", None) == "http"
                    )
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

    def start(self) -> None:
        if os.name == "posix":
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
        self.httpd.shutdown()
        super().stop()

    def run(self, preload: list[str] | None = None, stop: bool = False) -> int | None:
        self.start()
        self.stop()
        return None


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
        self.timeout = config["limit_time_real"]
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
        DEFAULT_RELOAD_TIMEOUT_S = 60.0
        env_value = os.environ.get("ODOO_RELOAD_TIMEOUT")
        if env_value is None:
            timeout_s = DEFAULT_RELOAD_TIMEOUT_S
        else:
            try:
                timeout_s = max(float(env_value), 1.0)
            except ValueError:
                self.logger.warning(
                    "ODOO_RELOAD_TIMEOUT=%r is not a number; using default %.0fs",
                    env_value, DEFAULT_RELOAD_TIMEOUT_S,
                )
                timeout_s = DEFAULT_RELOAD_TIMEOUT_S
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


# ``server`` and ``server_phoenix`` are NOT listed here — they live in
# ``odoo.service.lifecycle`` and are surfaced on this module via
# ``__getattr__`` so reads always reflect the live binding.  Listing them
# in ``__all__`` would cause ``from odoo.service.server import *`` to
# bind a snapshot, defeating the point.
__all__ = (  # noqa: RUF022 — grouped by origin (server/worker/wsgi/lifecycle/helpers); flat alphabetical loses that semantic
    # Server classes
    "CommonServer",
    "EventServer",
    "PreforkServer",
    "ThreadedServer",
    # Worker classes (re-exported from ._worker)
    "CpuTimeLimitExceeded",
    "Worker",
    "WorkerCron",
    "WorkerHTTP",
    # WSGI handlers (re-exported from .wsgi)
    "BaseWSGIServerNoBind",
    "CommonRequestHandler",
    "LoggingBaseWSGIServerMixIn",
    "RequestHandler",
    "ThreadedWSGIServerReloadable",
    # Lifecycle entry points (re-exported from .lifecycle)
    "load_server_wide_modules",
    "preload_registries",
    "restart",
    "start",
    # Module-level helpers + constants
    "CRON_NOTIFY_JITTER_MAX_S",
    "SLEEP_INTERVAL",
    "cron_database_list",
    "empty_pipe",
    "memory_info",
    "set_limit_memory_hard",
)

