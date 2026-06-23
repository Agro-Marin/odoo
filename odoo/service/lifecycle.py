"""Process-lifecycle entry points: ``start``, ``restart``, ``_reexec``,
``preload_registries``, ``load_server_wide_modules``.

Module-level functions (no class wrapper) because external callers —
``cli/shell.py``, ``http/application.py``, ``_watcher.py`` — invoke them as
plain functions.

Also defines the ``server`` and ``server_phoenix`` module globals.  Other
parts of ``service/`` mutate them as ``lifecycle.server_phoenix = True`` (not a
``global`` in their own namespace) so every reader sees the same binding.

* ``server`` — current server instance, set by ``start``.
* ``server_phoenix`` — "should we re-exec after stop?" flag, set on SIGHUP
  (``ThreadedServer.signal_handler``, ``PreforkServer.process_signals``) and in
  ``PreforkServer.stop``, read by ``start()`` after ``server.run()`` returns.
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
    if osutil.is_running_as_nt_service():
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


def preload_registries(dbnames: list[str] | None) -> int:
    """Preload a registries, possibly run a test file."""
    # TODO: move all config checks to args dont check tools.config here
    dbnames = dbnames or []
    rc = 0

    preload_profiler = contextlib.nullcontext()

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
                    result = loader.run_suite(
                        post_install_suite,
                        global_report=registry._assertion_report,
                    )
                    registry._assertion_report.update(result)
                    _logger.info(
                        "%d post-tests in %.2fs, %s queries",
                        registry._assertion_report.testsRun - tests_before,
                        time.time() - t0,
                        db.sql_counter - t0_sql,
                    )

                    registry._assertion_report.log_stats()
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
        if (
            platform.system() == "Linux"
            and sys.maxsize > 2**32
            and "MALLOC_ARENA_MAX" not in os.environ
        ):
            # glibc's malloc() uses arenas [1] in order to efficiently handle memory allocation of multi-threaded
            # applications. This allows better memory allocation handling in case of multiple threads that
            # would be using malloc() concurrently [2].
            # Due to the python's GIL, this optimization have no effect on multithreaded python programs.
            # Unfortunately, a downside of creating one arena per cpu core is the increase of virtual memory
            # which Odoo is based upon in order to limit the memory usage for threaded workers.
            # On 32bit systems the default size of an arena is 512K while on 64bit systems it's 64M [3],
            # hence a threaded worker will quickly reach it's default memory soft limit upon concurrent requests.
            # We therefore set the maximum arenas allowed to 2 unless the MALLOC_ARENA_MAX env variable is set.
            # Note: Setting MALLOC_ARENA_MAX=0 allow to explicitly set the default glibs's malloc() behaviour.
            #
            # [1] https://sourceware.org/glibc/wiki/MallocInternals#Arenas_and_Heaps
            # [2] https://www.gnu.org/software/libc/manual/html_node/The-GNU-Allocator.html
            # [3] https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c;h=00ce48c;hb=0a8262a#l862
            try:
                import ctypes

                libc = ctypes.CDLL("libc.so.6")
                M_ARENA_MAX = -8
                assert libc.mallopt(ctypes.c_int(M_ARENA_MAX), ctypes.c_int(2))
            except Exception:
                _logger.warning("Could not set ARENA_MAX through mallopt()")
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

    rc = server.run(preload, stop)

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
