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

# Log under the public module name so operators filtering on ``odoo.service.db``
# still see these records after the extraction from ``db.py``.
_logger = logging.getLogger("odoo.service.db")


# Enforced by the HTTP controller and service layer alike.  First char
# alphanumeric; the rest may add _ . - (``*`` so a single-char name is valid).
DBNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z"

# PostgreSQL silently truncates identifiers past NAMEDATALEN-1 = 63 bytes, so a
# 64+ char name would land under a different name in ``pg_database``.  Reject at
# validation time instead.  The pattern is ASCII-only, so char count == byte
# count.
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
        raise ValueError(
            _DBNAME_TOO_LONG_MSG.format(name=name, length=len(name))
        )
    if not re.match(DBNAME_PATTERN, name):
        raise ValueError(_DBNAME_ERROR_MSG.format(name=name))


class DatabaseExists(Warning):
    """Raised by ``_create_empty_database`` when the target name is taken.

    Inherits from ``Warning`` (not ``Exception``) for legacy reasons: callers
    catch it explicitly and the database-manager UI distinguishes it from a
    generic creation error.
    """


def database_identifier(cr: BaseCursor, name: str) -> SQL:
    """Quote a database identifier.

    Use instead of ``SQL.identifier`` to accept all kinds of identifiers.
    """
    name = psycopg_sql.Identifier(name).as_string(cr.connection)
    return SQL(name)


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

    ``verify_admin_password`` compares in constant time (``hmac.compare_digest``).
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
