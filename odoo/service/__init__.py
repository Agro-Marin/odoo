"""Classes of this module implement the network protocols that the
Odoo server uses to communicate with remote clients.

Some classes are mostly utilities, whose API need not be visible to
the average user/developer. Study them only if you are about to
implement an extension to the network protocols, or need to debug some
low-level behavior of the wire.

Module layout (post round-5+6 extractions):

    common.py       RPC service: login / authenticate / version
    db.py           RPC service: database lifecycle / dump / restore
    model.py        RPC service: object dispatch (execute / execute_kw)
    transaction.py  Cross-cutting retrying() primitive
    security.py     Session-token validation

    wsgi.py         WSGI request handlers + threaded WSGI server
    server.py       Server classes (Threaded / Event / Prefork)
    lifecycle.py    Process-lifecycle entry points (start / restart / preload)
    _watcher.py     Filesystem watcher backends (autoreload)
    _worker.py      Prefork worker classes
    _helpers.py     Shared process-control helpers (memory_info, empty_pipe,
                    cron_database_list, set_limit_memory_hard, SLEEP_INTERVAL,
                    CRON_NOTIFY_JITTER_MAX_S)
    _db_helpers.py  Shared db.py helpers (validate_db_name, check_super, ...)

Dependency graph is strictly downward:

    server -> _worker, lifecycle, wsgi, _watcher, _helpers, db
    _worker -> _helpers, wsgi
    _helpers -> db
    _watcher -> (nothing in service/)
    lifecycle -> _watcher, db
    db -> _db_helpers
    transaction -> (lazy odoo.http only)
    model -> transaction

No cycles.  The previous server <-> _worker cycle was broken in round 6
by extracting the shared helpers into ``_helpers.py``.
"""

# .apidoc title: RPC Services

# The submodules below are imported explicitly so external callers can do
# ``odoo.service.X`` after a single ``import odoo.service`` (Python only
# adds submodules to the parent package's namespace once they have been
# imported by someone).  The order is no longer load-bearing — every
# module's own imports drive the actual load order.
from . import common
from . import db
from . import lifecycle
from . import model
from . import server
from . import wsgi
