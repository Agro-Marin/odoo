"""Server facade: re-exports the server classes and their collaborators.

The server flavors were split out of this (formerly ~1,300-line) file into
focused siblings, each independently navigable:

    _base_server.py   CommonServer + the process-global on-stop registry
    _threaded.py      ThreadedServer (dev/threaded) + EventServer (gevent)
    _prefork.py       PreforkServer (multiprocess master/worker supervisor)
    _worker.py        Worker / WorkerHTTP / WorkerCron child classes
    wsgi.py           WSGI request handlers + threaded WSGI server
    lifecycle.py      start / restart / _reexec / preload entry points
    _watcher.py       autoreload filesystem watcher

This module stays the public import surface: ``odoo.addons``, ``cli/``, and
``bus/`` import these names from ``odoo.service.server`` (verified workspace
-wide — e.g. ``CommonServer`` from ``bus`` and ``sass_embedded``, ``restart``
from ``iot_drivers``, ``start`` from ``cli/shell``), so they are re-exported
here rather than relocating every call site.

``server`` and ``server_phoenix`` are NOT exported here — they live in
``odoo.service.lifecycle`` (the single source of truth) and are NOT mirrored
onto this module: there is deliberately no ``__getattr__`` forwarder (a single
``server.server_phoenix = X`` assignment would shadow such a forwarder
permanently and silently desync reads).  Every reader references
``lifecycle.server`` / ``lifecycle.server_phoenix`` directly; ``from
odoo.service.server import server_phoenix`` raises ``ImportError`` on purpose.
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

# ``FSWatcherBase`` is re-exported as a public attribute of this module
# because ``tests/service/test_server.py`` (and any future callers extending
# the watcher) reach it via ``odoo.service.server.FSWatcherBase``.  The
# leading-underscore ``odoo.service._watcher`` is the canonical home but
# signals "private"; this re-export gives external callers a stable,
# non-underscored import path.
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
# NOTE: the ``_helpers`` names (memory_info / empty_pipe / cron_database_list /
# SLEEP_INTERVAL / CRON_NOTIFY_JITTER_MAX_S) are intentionally NOT re-exported.
# They are private dependencies of the server modules; import them from
# ``odoo.service._helpers`` directly.  The former re-export had zero callers.
