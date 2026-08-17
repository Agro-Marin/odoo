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
from odoo.libs.worker_thread import current_worker_thread
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
    if osutil.is_running_as_nt_service(nt_service_name):
        rc = subprocess.call(  # noqa: S602  see comment above
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
    os.execve(sys.executable, args, os.environ)  # noqa: S606  re-exec of ourselves IS the restart


def _run_post_install_tests(registry: Registry, update_module: bool) -> None:
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


def _narrowing_test_spec() -> str:
    tags = (config["test_tags"] or "").strip()
    return "" if tags in {"", "+standard"} else tags


def preload_registries(dbnames: list[str] | None) -> int:
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
                current_worker_thread().dbname = dbname
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
                report = registry._assertion_report
                if report and not report.wasSuccessful():
                    rc += 1
                elif (
                    report and not report.testsRun and (spec := _narrowing_test_spec())
                ):
                    _logger.error(
                        "--test-tags %r matched no test at all: nothing ran, "
                        "yet the run would otherwise have reported success.",
                        spec,
                    )
                    rc += 1
        except Exception:
            _logger.critical(
                "Failed to initialize database `%s`.", dbname, exc_info=True
            )
            return -1
    return rc


def _limit_malloc_arenas() -> None:
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


def _connection_budget_demand() -> tuple[int, int]:
    maxconn = config["db_maxconn"]
    if not config["workers"]:
        return 1, maxconn
    children = config["workers"] + config["max_cron_threads"] + config["job_workers"]
    demand = children * maxconn
    processes = children
    if config["http_enable"]:
        processes += 1
        demand += config["db_maxconn_gevent"] or maxconn
    return processes, demand


def _warn_on_connection_budget() -> None:
    import odoo

    if odoo.evented:
        return
    try:
        processes, demand = _connection_budget_demand()
        configured_port = config["db_port"]
        with contextlib.closing(db.db_connect("postgres").cursor()) as cr:
            cr.execute("SHOW max_connections")
            server_max = int(cr.fetchone()[0])
            cr.execute("SHOW superuser_reserved_connections")
            reserved = int(cr.fetchone()[0])
            cr.execute("SELECT inet_server_port()")
            server_port = cr.fetchone()[0]
    except Exception:
        _logger.debug("Could not check the connection budget", exc_info=True)
        return

    # A pooler makes the comparison below meaningless: the workers contend for
    # its client slots, while max_connections bounds the much smaller server
    # pool it multiplexes, so demand legitimately exceeds it. Its client limit
    # is not readable from here, so report that rather than guess. Detected
    # without naming a vendor: a proxied connection reports the backend's port,
    # not the one we dialed.
    if server_port and configured_port and int(configured_port) != int(server_port):
        _logger.info(
            "Connection budget not checked: connected to port %s but the server "
            "reports port %s, so a connection pooler is in between and its "
            "client limit -- not max_connections=%d -- is what bounds this "
            "deployment. Size db_maxconn x %d process(es) against the pooler.",
            configured_port,
            server_port,
            server_max,
            processes,
        )
        return

    headroom = server_max - reserved
    if demand <= headroom:
        return
    _logger.warning(
        "Connection budget exceeds the primary: %d process(es) x db_maxconn may "
        "check out %d connections, but PostgreSQL allows %d (max_connections=%d "
        "minus superuser_reserved_connections=%d). Under load this surfaces as "
        "'FATAL: sorry, too many clients already'. Lower db_maxconn to %d or "
        "less, reduce the worker count, or raise max_connections. A read replica "
        "is budgeted separately and is not included in this figure.",
        processes,
        demand,
        headroom,
        server_max,
        reserved,
        max(headroom // processes, 1),
    )


def start(preload: list[str] | None = None, stop: bool = False) -> int:
    global server  # noqa: PLW0603  the running server IS a process singleton

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

    _warn_on_connection_budget()

    watcher = None
    if {"reload", "assets"} & set(config["dev_mode"]) and not odoo.evented:
        if inotify or watchdog:
            try:
                watcher = FSWatcherInotify() if inotify else FSWatcherWatchdog()
                watcher.start()
            except Exception:
                watcher = None
                _logger.warning(
                    "Could not start the file watcher — the server runs without "
                    "it, so source edits are NOT picked up. On Linux this is "
                    "usually fs.inotify.max_user_watches being exhausted "
                    "(shared with your editor); raise it, or run fewer servers.",
                    exc_info=True,
                )
        else:
            if os.name == "posix" and platform.system() != "Darwin":
                module = "inotify"
            else:
                module = "watchdog"
            _logger.warning(
                "'%s' module not installed. Code autoreload is disabled%s",
                module,
                (
                    " — with --dev=assets and no watcher, edited asset sources "
                    "are NOT picked up; use --dev=xml instead"
                    if "assets" in config["dev_mode"]
                    else ""
                ),
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
