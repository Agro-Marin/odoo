from __future__ import annotations

import logging
import os
import signal
from typing import TYPE_CHECKING, Any

import psutil

from odoo.tools.config import config

from ._helpers import over_memory_soft_limit

if TYPE_CHECKING:
    from collections.abc import Callable

_SIGHUP_AVAILABLE = hasattr(signal, "SIGHUP")

_logger = logging.getLogger("odoo.service.server")


_ON_STOP_FUNCS: list[Callable] = []


class CommonServer:
    flavor = "unknown"
    """How this server names itself to an operator, a metric, an alert.

    A class attribute rather than a lookup keyed on the class name: a new
    server flavour that forgets to set it is answering "unknown", which is
    visible, where a name-keyed dict outside the class answers with the class
    name and is not.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.interface: str = config["http_interface"] or "0.0.0.0"
        self.port: int = config["http_port"]
        self.pid: int = os.getpid()
        self.logger = _logger.getChild(self.__class__.__name__)
        self._process_handle = psutil.Process(self.pid)

    def metrics(self) -> dict[str, Any]:
        """What this server can say about itself, for /web/metrics.

        Each flavour answers for its own concurrency: a prefork master counts
        processes, a threaded server counts threads, and neither has to be
        recognised from outside by the shape of its attributes.
        """
        return {}

    def check_memory_limit(self) -> int | None:
        """RSS over the soft limit, or None.  Shared by every flavour."""
        memory = over_memory_soft_limit(self._process_handle, self.memory_soft_limit())
        if memory is not None:
            self.logger.warning("RSS memory soft-limit reached: %s bytes.", memory)
        return memory

    def memory_soft_limit(self) -> int:
        return config["limit_memory_soft"]

    @classmethod
    def on_stop(cls, func: Callable) -> None:
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
