"""Internal helpers for ``odoo.service.db``.

Module-private (underscore prefix).  External code should keep importing
these names from ``odoo.service.db`` — that module re-exports everything
defined here for backward compatibility.

Splitting these out of ``db.py`` reduces that module from ~970 lines to
~860 and groups the small utility surface (validation pattern, master-
password gate, identifier quoting, connection eviction) in one place.
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

# Use the public module's logger name so operators who filter on
# ``odoo.service.db`` continue to see these messages after the extraction.
# A ``__name__``-derived logger would silently move log records under
# ``odoo.service._db_helpers``, breaking existing log-config patterns.
_logger = logging.getLogger("odoo.service.db")


# Pattern enforced by the HTTP controller and service layer alike.
# First char must be alphanumeric; any additional chars may include _ . -
# (``*`` not ``+`` — a single-character alphanumeric name is valid in PG
# and was wrongly rejected by the previous ``+`` quantifier).
DBNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z"

# PostgreSQL caps identifiers at NAMEDATALEN-1 = 63 bytes. Names beyond
# that limit are silently truncated rather than rejected, so a request to
# create ``my_very_long_name_that_exceeds_the_limit_blah_blah_blah_more`` would
# end up as a different name in ``pg_database`` — a footgun that is easier to
# explain at validation time than after the fact.  The pattern only allows
# ASCII characters (alnum / _ / . / -) so ``len(name)`` and ``len(bytes)``
# coincide; no encoding step needed.
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

    Centralizes the two checks (length + regex shape) so every entry point
    in ``odoo.service.db`` (create, duplicate, rename, restore) gets the
    same diagnostics — the previous code duplicated the regex check at
    each call site and never enforced the length, letting PG silently
    truncate to 63 bytes.

    Length is checked **before** the regex so a degenerate input (e.g.,
    a megabyte-sized string slipping past an upstream bound) is rejected
    in O(1) rather than walked O(n) by the regex engine.
    """
    if len(name) > DBNAME_MAX_LENGTH:
        raise ValueError(
            _DBNAME_TOO_LONG_MSG.format(name=name, length=len(name))
        )
    if not re.match(DBNAME_PATTERN, name):
        raise ValueError(_DBNAME_ERROR_MSG.format(name=name))


class DatabaseExists(Warning):
    """Raised by ``_create_empty_database`` when the target name is taken.

    Inherits from ``Warning`` (not ``Exception``) for legacy reasons:
    historic callers caught it explicitly via ``except DatabaseExists`` and
    the database-manager UI distinguishes it from a generic creation error.
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

    Uses ``verify_admin_password`` which performs constant-time comparison
    (``hmac.compare_digest``) via the fork's ``CryptContext``.  The return
    type is ``Literal[True]`` because the only non-raising path returns
    ``True`` — annotating ``bool`` invites a callsite to test ``if not
    check_super(...)`` which is unreachable.
    """
    if passwd and odoo.tools.config.verify_admin_password(passwd):
        return True
    raise odoo.exceptions.AccessDenied




def _drop_conn(cr: BaseCursor, db_name: str) -> None:
    """Try to terminate all other connections that might prevent dropping the DB.

    Best-effort: requires the calling PG role to have superuser or
    ``pg_signal_backend`` membership.  Failures are caught (callers will see
    a downstream ``ObjectInUse`` from ``DROP DATABASE`` if termination was
    needed) but logged at debug level so operators with --log-level=debug
    can spot a missing-permission misconfiguration; the previous bare
    ``suppress(Exception)`` made permission errors invisible.
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
