"""Classes of this module implement the network protocols that the
Odoo server uses to communicate with remote clients.

Some classes are mostly utilities, whose API need not be visible to
the average user/developer. Study them only if you are about to
implement an extension to the network protocols, or need to debug some
low-level behavior of the wire.

Module layout:

    common.py       RPC service: login / authenticate / version
    db/             RPC service package: database lifecycle / dump / restore
        rpc.py          The dispatch table and the master-password gate
        lifecycle.py    create / drop / duplicate / rename
        dump.py         dump_db + the backup manifest
        restore.py      restore_db + neutralization
        listing.py      list_dbs + the dbfilter exposure checks
    model.py        RPC service: object dispatch (execute / execute_kw)
    transaction.py  Cross-cutting retrying() primitive
    security.py     Session-token validation

    wsgi.py         WSGI request handlers + threaded WSGI server
    server.py       Public facade re-exporting the server/worker classes
    _base_server.py CommonServer base + process-global on-stop registry
    _threaded.py    ThreadedServer (threaded) + EventServer (evented/websocket)
    _prefork.py     PreforkServer (multiprocess master/worker supervisor)
    lifecycle.py    Process-lifecycle entry points (start / restart / preload)
    _watcher.py     Filesystem watcher backends (autoreload)
    _worker.py      Prefork worker classes
    _cron.py        Shared cron LISTEN/NOTIFY plumbing (server + worker)
    _dispatch.py    Shared argument validation for the RPC dispatch tables
    _metrics.py     Prometheus exposition served behind /web/metrics
    _helpers.py     Shared process-control helpers
    _db_helpers.py  Shared helpers for the db package
    _dump_scanner.py  psql meta-command safety scanner for restore input
    _env.py         Guarded ODOO_* env-var parsing (env_float / env_int)

Submodules are imported eagerly so callers can use ``odoo.service.X`` after a
single ``import odoo.service``.  (A lazy ``__getattr__`` was tried and reverted:
it saved little and broke the DB-free test suite, which relies on the eager
``wsgi`` import to load stdlib ``http.server`` before odoo stubs top-level
``http``.)  Import order is not load-bearing.
"""

from . import common
from . import db
from . import lifecycle
from . import model
from . import server
from . import wsgi
