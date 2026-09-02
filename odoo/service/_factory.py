from __future__ import annotations

import logging
import platform
from typing import Any

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
    _reexec_server,
    _warn_on_connection_budget,
    load_server_wide_modules,
    preload_registries,
    restart,
)
from .settings import ServerSettings, current

_logger = logging.getLogger("odoo.service.server")

__all__ = (
    "load_server_wide_modules",
    "preload_registries",
    "restart",
    "start",
)


def _wrap_app_in_debugger(app: Any, settings: ServerSettings) -> Any:
    if "werkzeug" not in settings.dev_mode:
        return app

    from werkzeug.debug import DebuggedApplication

    import odoo.http.application

    if settings.workers:
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


def _prepare_server(app: Any, settings: ServerSettings) -> CommonServer:
    import odoo

    if odoo.evented:
        return EventServer(app)
    if settings.workers:
        if settings.test_enable:
            _logger.warning("Unit testing in workers mode could fail; use --workers 0.")
        return PreforkServer(app)
    _limit_malloc_arenas()
    return ThreadedServer(app)


def start(preload: list[str] | None = None, stop: bool = False) -> int:
    return _run_configured_server(current(), preload, stop)


def _run_configured_server(
    settings: ServerSettings, preload: list[str] | None, stop: bool
) -> int:
    load_server_wide_modules()
    import odoo
    import odoo.http

    app = _wrap_app_in_debugger(odoo.http.root, settings)
    server = _prepare_server(app, settings)
    set_server(server)

    _warn_on_connection_budget()

    watcher = None
    if {"reload", "assets"} & set(settings.dev_mode) and not odoo.evented:
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
                module = "run_watchdog"
            _logger.warning(
                "'%s' module not installed. Code autoreload is disabled%s",
                module,
                (
                    " — with --dev=assets and no watcher, edited asset sources "
                    "are NOT picked up; use --dev=xml instead"
                    if "assets" in settings.dev_mode
                    else ""
                ),
            )

    try:
        rc = server.run(preload, stop)
    finally:
        if watcher:
            watcher.stop()
    if _process_state.server_phoenix:
        _reexec_server()

    return rc or 0
