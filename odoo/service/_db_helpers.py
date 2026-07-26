"""Internal helpers for ``odoo.service.db`` (validation, master-password gate,
identifier quoting, connection eviction).

Module-private: ``db.py`` re-exports these names, so external code imports them
from ``odoo.service.db`` and the public surface stays stable.
"""

import functools
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from psycopg import sql as psycopg_sql

import odoo.exceptions
import odoo.tools
from odoo.tools import SQL

if TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.db import BaseCursor

_logger = logging.getLogger("odoo.service.db")


SYSTEM_DBS = frozenset({"postgres", "template0", "template1"})

DBNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z"

DBNAME_MAX_LENGTH = 63

_DBNAME_ERROR_MSG = (
    "Invalid database name {name!r}: must start with a letter or digit and may "
    "contain only alphanumeric characters, underscores, hyphens, and dots."
)
_DBNAME_TOO_LONG_MSG = (
    "Invalid database name {name!r}: PostgreSQL identifiers are limited to "
    f"{DBNAME_MAX_LENGTH} characters (got {{length}})."
)


def validate_db_name(name: str) -> None:
    """Raise ``ValueError`` if ``name`` violates the DB-name shape or length.

    Shared by every ``odoo.service.db`` entry point (create, duplicate, rename,
    restore).  Length is checked before the regex so a degenerate input (a
    huge string) is rejected in O(1) rather than walked O(n) by the regex.
    """
    if len(name) > DBNAME_MAX_LENGTH:
        raise ValueError(_DBNAME_TOO_LONG_MSG.format(name=name, length=len(name)))
    if not re.match(DBNAME_PATTERN, name):
        raise ValueError(_DBNAME_ERROR_MSG.format(name=name))


def rpc_db_exposed(db_name: object) -> bool:
    """Whether an RPC verb may act on ``db_name`` at all.

    The RPC services take the database name as a PARAMETER from a caller that
    has not authenticated yet — ``common.authenticate``/``login`` and
    ``object.execute_kw`` both reach ``Registry(db)``, building a registry and
    a connection pool, BEFORE any credential is verified.  This is the cheapest
    gate that can refuse a name the operator never declared servable, before
    that cost is paid.

    Two rules, both host-independent:

    * the PG system databases and the creation template are never servable
      (the same floor ``http.helpers.db_filter`` and ``db._rpc_db_exist``
      apply);
    * when ``--database`` is set it IS the exposed-database allowlist — the
      meaning ``db_filter`` and ``list_dbs`` already give it — so a name
      outside it is refused.

    ``--db-filter`` is deliberately NOT applied here.  It maps a *hostname* to
    a database, and ``http.dispatch_rpc`` runs inside ``borrow_request()``,
    which POPS the request off the stack — so no host is available at this
    point, and a dbfilter of ``^%h$`` would be evaluated against an empty host
    and refuse every RPC login on a virtual-host deployment.  An RPC caller
    names its database explicitly; host-based routing is not the right axis for
    it.

    With ``--database`` unset (no declared allowlist) every non-system name is
    allowed, i.e. the pre-existing behaviour is unchanged.
    """
    if not isinstance(db_name, str) or not db_name:
        return False
    if db_name in SYSTEM_DBS or db_name == odoo.tools.config["db_template"]:
        return False
    exposed = odoo.tools.config["db_name"]
    return not exposed or db_name in exposed


class DatabaseExists(Warning):
    """Raised by ``_create_empty_database`` when the target name is taken.

    Inherits from ``Warning`` (not ``Exception``) for legacy reasons: callers
    catch it explicitly and the database-manager UI distinguishes it from a
    generic creation error.
    """


def database_identifier(cr: BaseCursor, name: str) -> SQL:
    """Quote a database identifier.

    Use instead of ``SQL.identifier`` to accept all kinds of identifiers.

    The quoted identifier goes into ``SQL``'s ``code``, which is a
    ``%``-format template (``SQL.__init__`` asserts via ``code % ()``), so a
    literal ``%`` in the name — legal in a PostgreSQL identifier, and reachable
    via ``config['db_template']`` — must be doubled or it raises ``TypeError:
    not enough arguments for format string``.
    """
    name = psycopg_sql.Identifier(name).as_string(cr.connection)
    return SQL(name.replace("%", "%%"))


def check_db_management_enabled(func: Callable, /) -> Callable:
    """Decorator: raise ``AccessDenied`` if database management is disabled."""

    @functools.wraps(func)
    def if_db_mgt_enabled(*args: Any, **kwargs: Any) -> Any:
        if not odoo.tools.config["list_db"]:
            _logger.error(
                "Database management functions blocked, admin disabled database listing"
            )
            raise odoo.exceptions.AccessDenied
        return func(*args, **kwargs)

    return if_db_mgt_enabled


def check_super(passwd: str) -> Literal[True]:
    """Verify the master admin password or raise ``AccessDenied``.

    ``verify_admin_password`` checks via passlib's ``crypt_context.verify_and_update``
    (a timing-safe hash comparison that also transparently rehashes a stale hash).
    Returns ``Literal[True]`` because the only non-raising path returns ``True``
    — a ``bool`` annotation would invite an unreachable ``if not check_super()``.
    """
    if passwd and odoo.tools.config.verify_admin_password(passwd):
        return True
    raise odoo.exceptions.AccessDenied


def _drop_conn(cr: BaseCursor, db_name: str) -> None:
    """Try to terminate other connections that might block dropping the DB.

    Best-effort: needs superuser or ``pg_signal_backend`` membership.  Failures
    are logged at debug (callers still see a downstream ``ObjectInUse`` from
    ``DROP DATABASE`` if termination was needed).
    """
    try:
        cr.execute(
            """SELECT pg_terminate_backend(pid)
                      FROM pg_stat_activity
                      WHERE datname = %s AND
                            pid != pg_backend_pid()""",
            (db_name,),
        )
    except Exception:
        _logger.debug("pg_terminate_backend failed for %r", db_name, exc_info=True)
