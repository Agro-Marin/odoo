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

# Server classes (CommonServer is the shared base; the three flavors live in
# the two sibling modules below).
from ._base_server import (
    _ON_STOP_FUNCS,  # noqa: F401 — re-export (tests reach srv._ON_STOP_FUNCS)
    _SIGHUP_AVAILABLE,  # noqa: F401 — re-export (tests reach srv._SIGHUP_AVAILABLE)
    CommonServer,
)
from ._prefork import PreforkServer
from ._threaded import EventServer, ThreadedServer

# ``FSWatcherBase`` lives in the private ``_watcher`` module; re-export it here
# so tests and external callers have a stable, non-underscored import path.
from ._watcher import (
    FSWatcherBase,  # noqa: F401 — public re-export (tests reach srv.FSWatcherBase)
)

# Worker classes — re-exported from ``_worker``.
from ._worker import (
    CpuTimeLimitExceeded,
    Worker,
    WorkerCron,
    WorkerHTTP,
)

# Lifecycle entry points — re-exported so ``cli/shell.py`` (``server.start``),
# ``http/application.py`` (``load_server_wide_modules``) and the iot_drivers
# ``/restart`` helper (``server.restart``) keep working.
from .lifecycle import (
    load_server_wide_modules,
    preload_registries,
    restart,
    start,
)

# WSGI handlers — re-exported for backwards compat (addons/, cli/, bus/ all
# import these from ``odoo.service.server``).
from .wsgi import (
    BaseWSGIServerNoBind,
    CommonRequestHandler,
    LoggingBaseWSGIServerMixIn,
    RequestHandler,
    ThreadedWSGIServerReloadable,
)

_logger = logging.getLogger(__name__)


__all__ = (  # noqa: RUF022 — grouped by origin (server/worker/wsgi/lifecycle); flat alphabetical loses that semantic
    # Server classes (CommonServer from ._base_server; flavors from ._threaded/._prefork)
    "CommonServer",
    "EventServer",
    "PreforkServer",
    "ThreadedServer",
    # Worker classes (re-exported from ._worker)
    "CpuTimeLimitExceeded",
    "Worker",
    "WorkerCron",
    "WorkerHTTP",
    # WSGI handlers (re-exported from .wsgi)
    "BaseWSGIServerNoBind",
    "CommonRequestHandler",
    "LoggingBaseWSGIServerMixIn",
    "RequestHandler",
    "ThreadedWSGIServerReloadable",
    # Lifecycle entry points (re-exported from .lifecycle)
    "load_server_wide_modules",
    "preload_registries",
    "restart",
    "start",
)
# The ``_helpers`` names (memory_info / empty_pipe / cron_database_list /
# SLEEP_INTERVAL / CRON_NOTIFY_JITTER_MAX_S) are private dependencies of the
# server modules and are intentionally NOT re-exported; import them from
# ``odoo.service._helpers`` directly.
