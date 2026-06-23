"""Base server class and process-global stop-hook registry.

``CommonServer`` is the shared parent of ``ThreadedServer`` / ``EventServer``
(``_threaded.py``) and ``PreforkServer`` (``_prefork.py``).  It lives in this
leaf module so those two siblings and the ``server.py`` facade can all import
it without a cycle (``server.py`` re-exports it for external callers such as
``odoo.addons.bus`` and ``odoo.tools.sass_embedded``).
"""

from __future__ import annotations

import errno
import logging
import os
import platform
import signal
import socket
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
                # A hook may be a ``functools.partial`` (no ``__name__``); fall
                # back to ``repr`` so this handler can't raise and abort the
                # remaining hooks.
                name = getattr(func, "__name__", repr(func))
                self.logger.warning("Exception in %s", name, exc_info=True)


