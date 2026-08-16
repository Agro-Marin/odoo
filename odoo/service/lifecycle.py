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


def _narrowing_test_spec() -> str:
    """Return the ``--test-tags`` spec when the user narrowed the run, else ``""``.

    A selection that matches nothing has to fail the run: the spec grammar is
    unforgiving (``odoo/tests/tag_selector.py``), and near-misses are the norm
    rather than the exception -- ``:WebSuite.test_core.@web/core/domain`` instead
    of ``:WebSuite.test_core[@web/core/domain]``, a renamed class, a method typo.
    All three collected zero tests and exited ``0``, so the caller reads a clean
    run as proof its change is green when nothing was executed at all.

    Only an *explicit* narrowing counts. ``config`` fills ``test_tags`` with
    ``+standard`` when only ``--test-enable`` is given, and installing a module
    that ships no tests legitimately runs zero under it.
    """
    tags = (config["test_tags"] or "").strip()
    return "" if tags in {"", "+standard"} else tags


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


def _connection_budget_demand() -> tuple[int, int]:
    """Return ``(processes, connections)`` this deployment may demand at once.

    ``db_maxconn`` is a PER-PROCESS, PER-SERVER budget, so prefork multiplies it
    by every child that opens pools: the HTTP workers, the cron and job workers,
    and the evented subprocess (which uses ``db_maxconn_gevent`` when set).  The
    master is excluded — it calls ``db.close_all()`` before its supervision loop.

    The figure returned is the demand on the **primary**, which is the server
    this check can reach.  A configured read replica carries its own budget
    against its own ``max_connections`` (see :func:`odoo.db._budget_for`) and is
    not counted here: probing it would mean a connect to a possibly-absent host
    on the boot path, which is not a trade a diagnostic should make.
    """
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
    """Warn when this deployment can demand more PG connections than exist.

    ``db_maxconn``'s own help text already states the arithmetic — size
    ``max_connections`` against it "multiplied by the worker count" — but
    nothing checked it, so the failure surfaced as ``FATAL: sorry, too many
    clients already`` from whichever worker happened to lose the race, at the
    moment of peak load rather than at boot.

    Advisory only: the numbers are ceilings, not reservations, and a deployment
    that never saturates every worker at once is fine.  It therefore warns and
    continues, and stays silent when PostgreSQL cannot be asked.

    Every read it makes — config included, not just the two ``SHOW`` queries —
    is inside the guard.  This runs on the boot path, so a check that exists
    only to print advice must not be able to become the reason a server fails to
    start; the config read was outside the guard once, and an incomplete
    ``config`` mapping turned a diagnostic into a ``KeyError`` at startup.
    """
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

    # Bail out when a connection pooler sits between us and PostgreSQL: the two
    # sides of the comparison then describe different things.  Our workers
    # contend for the pooler's client slots, while ``max_connections`` bounds
    # the pooler's own (much smaller) server pool, which it multiplexes -- so
    # demand legitimately exceeds it, and the advice below would be actively
    # wrong: cutting ``db_maxconn`` to fit the backend starves the workers
    # against a pooler sized to serve them.  The pooler's client limit is not
    # readable from here (PgBouncer answers ``SHOW max_client_conn`` only on
    # its admin database), so the honest move is to say we cannot check it.
    #
    # Detected without naming a vendor: a proxied connection reports the
    # *backend's* port, so it differs from the port we dialed.
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
