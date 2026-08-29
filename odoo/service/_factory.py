"""Choose a server for this process, run it, and re-exec if it asked to.

The factory, and only the factory.  `lifecycle` is everything the servers
themselves need -- preload, the re-exec, the resident-registry sizing -- and
`_process_state` holds the two globals they reach for.  This module sits ABOVE
the server classes and imports them at the top; while it lived inside
`lifecycle`, which they import, the graph was two-way and `lifecycle`,
`_watcher`, `_metrics`, `_threaded` and `_prefork` each carried a deferred
import to work around it.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

from odoo.tools import config

from . import _process_state
from ._base_server import CommonServer
from ._env import _IS_POSIX
from ._prefork import PreforkServer
from ._process_state import set_server
from ._threaded import EventServer, ThreadedServer
from ._watcher import (
    FSWatcherInotify,
    FSWatcherWatchdog,
    inotify,
    watchdog,
)
from .lifecycle import (
    _limit_malloc_arenas,
    _reexec,
    _warn_on_connection_budget,
    load_server_wide_modules,
    preload_registries,
    restart,
)

_logger = logging.getLogger("odoo.service.server")

__all__ = (
    "load_server_wide_modules",
    "preload_registries",
    "restart",
    "start",
)


def _with_werkzeug_debugger(app: Any) -> Any:
    if "werkzeug" not in config["dev_mode"]:
        return app

    from werkzeug.debug import DebuggedApplication

    import odoo.http.application

    if config["workers"]:
        _logger.warning(
            "--dev=werkzeug with workers > 0: each worker prints its own "
            "debugger PIN and only the worker that served the request accepts "
            "it. Use --workers 0."
        )
    _logger.warning(
        "--dev=werkzeug is on: unhandled errors render an interactive "
        "traceback with a code console. Never expose this port."
    )
    odoo.http.application.debugger_attached = True
    return DebuggedApplication(app, evalex=True)


def _build_server(app: Any) -> CommonServer:
    import odoo

    if odoo.evented:
        return EventServer(app)
    if config["workers"]:
        if config["test_enable"]:
            _logger.warning("Unit testing in workers mode could fail; use --workers 0.")
        return PreforkServer(app)
    _limit_malloc_arenas()
    return ThreadedServer(app)


def start(preload: list[str] | None = None, stop: bool = False) -> int:
    load_server_wide_modules()
    import odoo
    import odoo.http

    app = _with_werkzeug_debugger(odoo.http.root)
    server = _build_server(app)
    set_server(server)

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
            if _IS_POSIX and platform.system() != "Darwin":
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
    if _process_state.server_phoenix:
        _reexec()

    return rc or 0
