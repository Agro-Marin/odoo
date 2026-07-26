"""Base server class and process-global stop-hook registry.

``CommonServer`` is the shared parent of ``ThreadedServer`` / ``EventServer``
(``_threaded.py``) and ``PreforkServer`` (``_prefork.py``).  It lives in this
leaf module so both siblings and the ``server.py`` facade can import it without
a cycle.
"""

from __future__ import annotations

import logging
import os
import signal
from typing import TYPE_CHECKING, Any

from odoo.tools import config

if TYPE_CHECKING:
    from collections.abc import Callable

_SIGHUP_AVAILABLE = hasattr(signal, "SIGHUP")

_logger = logging.getLogger("odoo.service.server")


_ON_STOP_FUNCS: list[Callable] = []


class CommonServer:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.interface: str = config["http_interface"] or "0.0.0.0"
        self.port: int = config["http_port"]
        self.pid: int = os.getpid()
        self.logger = _logger.getChild(self.__class__.__name__)

    @classmethod
    def on_stop(cls, func: Callable) -> None:
        """Register a cleanup function to run when the server stops.

        Idempotent: the process-global list is append-only, so deduping here
        keeps a twice-imported module (or an in-process restart) from firing
        the same hook more than once.
        """
        if func not in _ON_STOP_FUNCS:
            _ON_STOP_FUNCS.append(func)

    def stop(self) -> None:
        for func in _ON_STOP_FUNCS:
            try:
                self.logger.debug("on_close call %s", func)
                func()
            except Exception:
                name = getattr(func, "__name__", repr(func))
                self.logger.warning("Exception in %s", name, exc_info=True)
