"""Process-lifecycle entry points: ``start``, ``restart``, ``_reexec``,
``preload_registries``, ``load_server_wide_modules``.

Module-level functions (no class wrapper) because external callers —
``cli/shell.py``, ``http/application.py``, ``_watcher.py`` — invoke them as
plain functions.

Also defines the ``server`` and ``server_phoenix`` module globals.  Other parts
of ``service/`` mutate them as ``lifecycle.server_phoenix = True`` so every
reader sees the same binding.

* ``server`` — current server instance, set by ``start``.
* ``server_phoenix`` — "re-exec after stop?" flag, set ``True`` on SIGHUP and
  read by ``start()`` after ``server.run()`` returns.  The watcher's read is
  racy, but a stale read only costs one extra (idempotent) SIGHUP, so no Lock.
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

from ._env import env_float, env_int

from ._watcher import (
    FSWatcherInotify,
    FSWatcherWatchdog,
    inotify,
    watchdog,
)

_logger = logging.getLogger("odoo.service.server")

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
        rc = subprocess.call(
            f"net stop {nt_service_name} && net start {nt_service_name}",
            shell=True,
        )
        if rc == 0:
            return
        _logger.warning(
            "Service restart via the SCM failed (exit %s); "
            "falling back to an in-place re-exec",
            rc,
        )
    exe = Path(sys.executable).name
    args = stripped_sys_argv()
    if updated_modules:
        args += ["-u", ",".join(updated_modules)]
    if not args or args[0] not in (sys.executable, exe):
        args.insert(0, sys.executable)
    os.execve(sys.executable, args, os.environ)


def _run_post_install_tests(registry: Registry, update_module: bool) -> None:
    """Run the ``post_install`` test suite for a freshly (re)loaded registry.

    Pregenerates QWeb asset bundles first when the suite has an HTTPCase, so the
    first in-test HTTP request doesn't pay the bundle-build cost and time out.
    Runs into ``registry._assertion_report`` (mutated in place; the caller reads
    ``wasSuccessful()``) and logs test/query counts.
    """
    from odoo.db.utils import seed_planner_stats
    from odoo.tests import loader

    try:
        with registry.cursor() as cr:
            seeded = seed_planner_stats(cr)
        if seeded:
            _logger.info("Seeded planner statistics for %d zero-stat tables", seeded)
    except Exception:
        _logger.warning(
            "Planner-stats seeding failed; tests may run slower", exc_info=True
        )

    t0 = time.time()
    t0_sql = db.sql_counter
    module_names = (
        registry.updated_modules if update_module else sorted(registry._init_modules)
    )
    _logger.info("Starting post tests")
    tests_before = registry._assertion_report.testsRun
    post_install_suite = loader.make_suite(module_names, "post_install")
    if post_install_suite.has_http_case():
        with registry.cursor() as cr:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            env["ir.qweb"]._pregenerate_assets_bundles()

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
    dbnames = dbnames or []
    rc = 0

    preload_profiler = contextlib.nullcontext()

    registries_size = env_int("ODOO_REGISTRY_LRU_SIZE", 0, minimum=0, logger=_logger)
    if not registries_size:
        if os.name == "posix":
            avgsz = 15 * 1024 * 1024
            limit_memory_soft = (
                config["limit_memory_soft"]
                if config["limit_memory_soft"] > 0
                else (2048 * 1024 * 1024)
            )
            registries_size = (limit_memory_soft // avgsz) or 1
        if len(dbnames) > max(registries_size, Registry.registries.count):
            registries_size = len(dbnames)
    if registries_size:
        Registry.registries.count = registries_size

    for dbname in dbnames:
        if os.environ.get("ODOO_PROFILE_PRELOAD"):
            interval = env_float("ODOO_PROFILE_PRELOAD_INTERVAL", 0.1, logger=_logger)
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

    glibc's malloc() creates one arena per CPU core [1][2] to reduce contention
    between threads — useless under Python's GIL, and each 64-bit arena reserves
    64M of virtual memory [3], so a threaded worker hits its memory soft limit
    under concurrent requests.  Cap at 2 unless MALLOC_ARENA_MAX is set
    (MALLOC_ARENA_MAX=0 restores glibc's default).

    Skipped on a free-threaded (no-GIL) build, which this fork targets: there
    the HTTP-handler threads ``malloc()`` in genuine parallel and 2 arenas would
    serialize them on 2 mutexes (real contention); the memory rationale also
    weakens, since the RSS soft limit is inflated far less by arenas than VMS.

    [1] https://sourceware.org/glibc/wiki/MallocInternals#Arenas_and_Heaps
    [2] https://www.gnu.org/software/libc/manual/html_node/The-GNU-Allocator.html
    [3] https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c;h=00ce48c;hb=0a8262a#l862
    """
    gil_disabled = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
    if gil_disabled or not (
        platform.system() == "Linux"
        and sys.maxsize > 2**32
        and "MALLOC_ARENA_MAX" not in os.environ
    ):
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        M_ARENA_MAX = -8
        ok = libc.mallopt(ctypes.c_int(M_ARENA_MAX), ctypes.c_int(2)) == 1
    except Exception:
        ok = False
    if not ok:
        _logger.warning("Could not set ARENA_MAX through mallopt()")


def start(preload: list[str] | None = None, stop: bool = False) -> int:
    """Start the odoo http server and cron processor."""
    global server

    load_server_wide_modules()
    import odoo.http

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
        if watcher:
            watcher.stop()
    if server_phoenix:
        _reexec()

    return rc or 0


def restart() -> None:
    """Restart the server.

    No-op if the module-level ``server`` is not yet assigned (e.g. the watcher
    fires before ``start()`` runs), which would otherwise crash on ``.pid``.
    """
    if server is None:
        _logger.warning(
            "restart() called before server.start() assigned the server; ignoring"
        )
        return
    if os.name == "nt":
        threading.Thread(target=_reexec).start()
    else:
        import signal

        os.kill(server.pid, signal.SIGHUP)
