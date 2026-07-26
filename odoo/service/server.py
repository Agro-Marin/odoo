"""Server facade: the public import surface for the server classes.

The flavors live in focused sibling modules; ``odoo.addons``, ``cli/`` and
``bus/`` import these names from ``odoo.service.server``, so they are
re-exported here:

    _base_server.py   CommonServer + the process-global on-stop registry
    _threaded.py      ThreadedServer (dev/threaded) + EventServer (evented/websocket)
    _prefork.py       PreforkServer (multiprocess master/worker supervisor)
    _worker.py        Worker / WorkerHTTP / WorkerCron child classes
    wsgi.py           WSGI request handlers + threaded WSGI server
    lifecycle.py      start / restart / _reexec / preload entry points
    _watcher.py       autoreload filesystem watcher

``server`` and ``server_phoenix`` are deliberately NOT re-exported: they live in
``lifecycle`` (single source of truth) and are read as ``lifecycle.server`` /
``lifecycle.server_phoenix``.  A forwarder here would be silently shadowed by a
``server.server_phoenix = X`` assignment, so importing them from here raises
``ImportError`` on purpose.
"""

import logging

from ._base_server import (
    _ON_STOP_FUNCS,
    _SIGHUP_AVAILABLE,
    CommonServer,
)
from ._prefork import PreforkServer
from ._threaded import EventServer, ThreadedServer

from ._watcher import (
    FSWatcherBase,
)

from ._worker import (
    CpuTimeLimitExceeded,
    Worker,
    WorkerCron,
    WorkerHTTP,
    WorkerJob,
)

from .lifecycle import (
    load_server_wide_modules,
    preload_registries,
    restart,
    start,
)

from .wsgi import (
    BaseWSGIServerNoBind,
    CommonRequestHandler,
    LoggingBaseWSGIServerMixIn,
    RequestHandler,
    ThreadedWSGIServerReloadable,
)

_logger = logging.getLogger(__name__)


__all__ = (
    "CommonServer",
    "EventServer",
    "PreforkServer",
    "ThreadedServer",
    "CpuTimeLimitExceeded",
    "Worker",
    "WorkerCron",
    "WorkerHTTP",
    "WorkerJob",
    "BaseWSGIServerNoBind",
    "CommonRequestHandler",
    "LoggingBaseWSGIServerMixIn",
    "RequestHandler",
    "ThreadedWSGIServerReloadable",
    "load_server_wide_modules",
    "preload_registries",
    "restart",
    "start",
)
