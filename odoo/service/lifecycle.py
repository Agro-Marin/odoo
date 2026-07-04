"""Process-lifecycle entry points: ``start``, ``restart``, ``_reexec``,
``preload_registries``, ``load_server_wide_modules``.

Module-level functions (no class wrapper) because external callers —
``cli/shell.py``, ``http/application.py``, ``_watcher.py`` — invoke them as
plain functions.

Also defines the ``server`` and ``server_phoenix`` module globals.  Other
parts of ``service/`` mutate them as ``lifecycle.server_phoenix = True`` (not a
``global`` in their own namespace) so every reader sees the same binding.

* ``server`` — current server instance, set by ``start``.
* ``server_phoenix`` — "should we re-exec after stop?" flag, set ``True`` on
  SIGHUP (``ThreadedServer.signal_handler``, ``PreforkServer.process_signals``)
  and cleared in ``PreforkServer.stop``, read by ``start()`` after
  ``server.run()`` returns.
  The watcher's read is racy, but a stale read only costs one extra (idempotent)
  SIGHUP, so no Lock is needed.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from odoo import api, db
from odoo.libs import gc
from odoo.libs.filesystem import osutil
from odoo.modules.module import load_odoo_module
from odoo.modules.registry import Registry
from odoo.release import nt_service_name
from odoo.tools import config, profiler
from odoo.tools.misc import stripped_sys_argv

from ._env import env_float

# Watcher backends, selected in ``_watcher``; surfaced here so ``start()`` can
# dispatch on whichever one actually loaded.
from ._watcher import (
    FSWatcherInotify,
    FSWatcherWatchdog,
    inotify,
    watchdog,
)

_logger = logging.getLogger("odoo.service.server")  # preserve operator log filters

# Module-level state (see module docstring for the mutation invariant).
server = None
server_phoenix = False


def load_server_wide_modules() -> None:
    """Import all server-wide modules listed in the configuration."""
    with gc.disabling_gc():
        for m in config["server_wide_modules"]:
            try:
                load_odoo_module(m)
            except Exception:
                msg = ""
                if m == "web":
                    msg = """
    The `web` module is provided by the addons found in the `odoo-web` project.
    Maybe you forgot to add those addons in your addons_path configuration."""
                _logger.exception("Failed to load server-wide module `%s`.%s", m, msg)


def _reexec(updated_modules: list[str] | None = None) -> None:
    """Reexecute odoo-server process with (nearly) the same arguments."""
    if osutil.is_running_as_nt_service(nt_service_name):
        # Windows-only restart via the SCM. ``shell=True`` is required because
        # ``net`` is a shell built-in/cmd alias on Windows; ``nt_service_name``
        # is a build-time constant from ``odoo.release``, not user input.
        subprocess.call(  # noqa: S602
            f"net stop {nt_service_name} && net start {nt_service_name}",
            shell=True,
        )
    exe = Path(sys.executable).name
    args = stripped_sys_argv()
    if updated_modules:
        args += ["-u", ",".join(updated_modules)]
    # Insert the interpreter as argv[0] unless already present in either form
    # (full path or basename).  Checking both avoids a double-insert when
    # ``sys.argv[0] == sys.executable``, which would make ``os.execve`` treat
    # the python binary as a script.
    if not args or args[0] not in (sys.executable, exe):
        args.insert(0, sys.executable)
    # ``os.execve`` (no shell): replaces the process in place, preserving the
    # LISTEN_* env vars systemd socket activation needs.  ``args`` comes from
    # ``stripped_sys_argv`` (sanitised).
    os.execve(sys.executable, args, os.environ)  # noqa: S606


def _run_post_install_tests(registry: Registry, update_module: bool) -> None:
    """Run the ``post_install`` test suite for a freshly (re)loaded registry.

    Pregenerates QWeb asset bundles first when the suite contains an HTTPCase,
    so the first in-test HTTP request doesn't pay the bundle-build cost and time
    out.  Runs the suite into ``registry._assertion_report`` (mutated in place —
    the caller reads ``wasSuccessful()`` for its return code) and logs the
    test/query counts.
    """
    from odoo.tests import loader

    t0 = time.time()
    t0_sql = db.sql_counter
    module_names = (
        registry.updated_modules
        if update_module
        else sorted(registry._init_modules)
    )
    _logger.info("Starting post tests")
    tests_before = registry._assertion_report.testsRun
    post_install_suite = loader.make_suite(module_names, "post_install")
    if post_install_suite.has_http_case():
        with registry.cursor() as cr:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            env["ir.qweb"]._pregenerate_assets_bundles()

    # The threaded server enters preload holding ``Registry._lock`` (see
    # ``ThreadedServer.run``: requests must not build registries while preload
    # is in flight — upstream odoo/odoo#161438). By this point the registry IS
    # fully loaded, and keeping the lock through the suite deadlocks any HTTP
    # request from a test that does NOT enter registry test mode (BaseCase
    # suites exercising real registry loading, e.g. test_http's
    # ``database_breaking``): the worker blocks in ``Registry.__new__`` while
    # this thread waits for its HTTP response. Release our holds for the
    # duration of the suite and restore them after. HttpCase suites are
    # unaffected either way (test mode swaps in ``DummyRLock``); the prefork
    # path calls this without holding the lock (``held == 0``).
    lock = Registry._lock
    held = 0
    while getattr(lock, "_is_owned", bool)():
        lock.release()
        held += 1
    try:
        result = loader.run_suite(
            post_install_suite,
            global_report=registry._assertion_report,
        )
    finally:
        for _ in range(held):
            lock.acquire()
    registry._assertion_report.update(result)
    _logger.info(
        "%d post-tests in %.2fs, %s queries",
        registry._assertion_report.testsRun - tests_before,
        time.time() - t0,
        db.sql_counter - t0_sql,
    )
    registry._assertion_report.log_stats()


def preload_registries(dbnames: list[str] | None) -> int:
    """Preload registries for ``dbnames``, optionally running post-install tests."""
    # TODO: move all config checks to args dont check tools.config here
    dbnames = dbnames or []
    rc = 0

    preload_profiler = contextlib.nullcontext()

    registries_size = int(os.environ.get("ODOO_REGISTRY_LRU_SIZE") or 0)
    if not registries_size and os.name == "posix":
        # Size the LRU depending of the memory limits
        # A registry takes 10MB of memory on average, so we reserve
        # 10Mb (registry) + 5Mb (working memory) per registry
        avgsz = 15 * 1024 * 1024
        limit_memory_soft = (
            config["limit_memory_soft"]
            if config["limit_memory_soft"] > 0
            else (2048 * 1024 * 1024)
        )
        registries_size = (limit_memory_soft // avgsz) or 1
    elif not registries_size and len(dbnames) > Registry.registries.count:
        # If we give a list of databases higher and did not specify the size,
        # use the number of preloaded databases as the limit.
        registries_size = len(dbnames)
    if registries_size:
        Registry.registries.count = registries_size

    for dbname in dbnames:
        if os.environ.get("ODOO_PROFILE_PRELOAD"):
            # Guarded parse: a malformed interval warns and falls back to 0.1s
            # instead of aborting the preload run.
            interval = env_float(
                "ODOO_PROFILE_PRELOAD_INTERVAL", 0.1, logger=_logger
            )
            collectors = [profiler.PeriodicCollector(interval=interval)]
            if os.environ.get("ODOO_PROFILE_PRELOAD_SQL"):
                collectors.append("sql")
            preload_profiler = profiler.Profiler(db=dbname, collectors=collectors)
        try:
            with preload_profiler:
                threading.current_thread().dbname = dbname
                update_module = config["init"] or config["update"] or config["reinit"]

                registry = Registry.new(
                    dbname,
                    update_module=update_module,
                    install_modules=config["init"],
                    upgrade_modules=config["update"],
                    reinit_modules=config["reinit"],
                )

                # run post-install tests
                if config["test_enable"]:
                    _run_post_install_tests(registry, update_module)
                if (
                    registry._assertion_report
                    and not registry._assertion_report.wasSuccessful()
                ):
                    rc += 1
        except Exception:
            _logger.critical(
                "Failed to initialize database `%s`.", dbname, exc_info=True
            )
            return -1
    return rc


def _limit_malloc_arenas() -> None:
    """Cap glibc's malloc arenas at 2 on 64-bit Linux (threaded server only).

    glibc's malloc() uses arenas [1] to efficiently handle memory allocation of
    multi-threaded applications, allowing better allocation handling when
    several threads call malloc() concurrently [2].  Due to Python's GIL this
    optimization has no effect on multithreaded Python programs.  Unfortunately,
    a downside of creating one arena per CPU core is an increase in virtual
    memory — which Odoo relies upon to limit the memory usage of threaded
    workers.  On 32-bit systems an arena defaults to 512K, on 64-bit to 64M [3],
    so a threaded worker quickly reaches its memory soft limit under concurrent
    requests.  We therefore cap arenas at 2 unless MALLOC_ARENA_MAX is set
    (MALLOC_ARENA_MAX=0 restores glibc's default behaviour).

    [1] https://sourceware.org/glibc/wiki/MallocInternals#Arenas_and_Heaps
    [2] https://www.gnu.org/software/libc/manual/html_node/The-GNU-Allocator.html
    [3] https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c;h=00ce48c;hb=0a8262a#l862
    """
    if not (
        platform.system() == "Linux"
        and sys.maxsize > 2**32
        and "MALLOC_ARENA_MAX" not in os.environ
    ):
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        M_ARENA_MAX = -8
        # Explicit check, NOT ``assert``: under ``python -O`` an ``assert``
        # statement — and the ``mallopt()`` call inside it — is stripped, so the
        # arena cap would silently never be applied and the threaded worker's
        # virtual-memory soft-limit accounting would degrade.  ``mallopt``
        # returns 1 on success, 0 on failure.
        ok = libc.mallopt(ctypes.c_int(M_ARENA_MAX), ctypes.c_int(2)) == 1
    except Exception:
        ok = False
    if not ok:
        _logger.warning("Could not set ARENA_MAX through mallopt()")


def start(preload: list[str] | None = None, stop: bool = False) -> int:
    """Start the odoo http server and cron processor."""
    # ``server`` is the canonical handle other modules read as
    # ``lifecycle.server`` (see module docstring); the global binding is the
    # design, hence the PLW0603 suppression.
    global server  # noqa: PLW0603

    load_server_wide_modules()
    import odoo.http

    # Imported lazily (not at module top) so ``server.py`` can do
    # ``from . import lifecycle`` without a top-level cycle.
    from .server import EventServer, PreforkServer, ThreadedServer

    if odoo.evented:
        server = EventServer(odoo.http.root)
    elif config["workers"]:
        if config["test_enable"]:
            _logger.warning("Unit testing in workers mode could fail; use --workers 0.")

        server = PreforkServer(odoo.http.root)
    else:
        _limit_malloc_arenas()
        server = ThreadedServer(odoo.http.root)

    watcher = None
    if "reload" in config["dev_mode"] and not odoo.evented:
        if inotify:
            watcher = FSWatcherInotify()
            watcher.start()
        elif watchdog:
            watcher = FSWatcherWatchdog()
            watcher.start()
        else:
            if os.name == "posix" and platform.system() != "Darwin":
                module = "inotify"
            else:
                module = "watchdog"
            _logger.warning(
                "'%s' module not installed. Code autoreload feature is disabled",
                module,
            )

    try:
        rc = server.run(preload, stop)
    finally:
        # Stop the watcher on every exit path, including an exception out of
        # ``server.run`` (e.g. a port-bind ``OSError`` raised from
        # ``http_spawn``).  Otherwise the inotify thread and its kernel watches
        # leak, and ``FSWatcherInotify.stop``'s ``del self.watcher`` — which
        # frees those watches before a reexec — never runs.
        if watcher:
            watcher.stop()
    # like the legend of the phoenix, all ends with beginnings
    if server_phoenix:
        _reexec()

    return rc or 0


def restart() -> None:
    """Restart the server.

    No-op if the module-level ``server`` has not been assigned yet —
    e.g. an addon importing the autoreload watcher before ``start()`` runs
    would otherwise crash with ``AttributeError: 'NoneType' has no attribute 'pid'``.
    """
    if server is None:
        _logger.warning(
            "restart() called before server.start() assigned the server; ignoring"
        )
        return
    if os.name == "nt":
        # Windows has no SIGHUP; do the re-exec on a background thread so the
        # caller can return its response (the Odoo HTTP /restart endpoint, the
        # database manager UI, etc.) before the current process replaces itself.
        threading.Thread(target=_reexec).start()
    else:
        # POSIX: send SIGHUP to ourselves; the server's signal handler sets
        # ``server_phoenix = True`` and breaks the main loop, then ``start()``
        # calls ``_reexec`` after ``server.run`` returns.
        import signal
        os.kill(server.pid, signal.SIGHUP)
