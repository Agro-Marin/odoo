"""Base server class and process-global stop-hook registry.

``CommonServer`` is the shared parent of ``ThreadedServer`` / ``EventServer``
(``_threaded.py``) and ``PreforkServer`` (``_prefork.py``).  It lives in this
leaf module so those two siblings and the ``server.py`` facade can all import
it without a cycle (``server.py`` re-exports it for external callers such as
``odoo.addons.bus`` and ``odoo.tools.sass_embedded``).
"""

from __future__ import annotations

import logging
import os
import signal
from typing import TYPE_CHECKING, Any

from odoo.tools import config

if TYPE_CHECKING:
    from collections.abc import Callable

# ``signal.SIGHUP`` is POSIX-only; gate SIGHUP handling on this rather than
# monkey-patching a sentinel into the stdlib ``signal`` module.
_SIGHUP_AVAILABLE = hasattr(signal, "SIGHUP")

# All server classes log under ``odoo.service.server`` so operator log filters
# keep working regardless of which module defines the class.
_logger = logging.getLogger("odoo.service.server")


# Process-global on-stop callbacks: they fire once per process, independent of
# which server class runs, so they live at module scope rather than on the class
# (where a subclass reassignment could silently desync from this list).
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

    @classmethod
    def on_stop(cls, func: Callable) -> None:
        """Register a cleanup function to be executed when the server stops.

        Idempotent: registering the same callable twice is a no-op.  The list is
        process-global and append-only, so without this a module imported twice
        — or a server stopped and restarted in-process (tests, embedded use) —
        would fire the same hook more than once on ``stop()``.
        """
        if func not in _ON_STOP_FUNCS:
            _ON_STOP_FUNCS.append(func)

    def stop(self) -> None:
        for func in _ON_STOP_FUNCS:
            try:
                self.logger.debug("on_close call %s", func)
                func()
            except Exception:
                # A hook may be a ``functools.partial`` (no ``__name__``); fall
                # back to ``repr`` so this handler can't raise and abort the
                # remaining hooks.
                name = getattr(func, "__name__", repr(func))
                self.logger.warning("Exception in %s", name, exc_info=True)
