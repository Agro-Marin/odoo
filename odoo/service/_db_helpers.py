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
    if len(name) > DBNAME_MAX_LENGTH:
        raise ValueError(_DBNAME_TOO_LONG_MSG.format(name=name, length=len(name)))
    if not re.match(DBNAME_PATTERN, name):
        raise ValueError(_DBNAME_ERROR_MSG.format(name=name))


def rpc_db_exposed(db_name: object) -> bool:
    if not isinstance(db_name, str) or not db_name:
        return False
    if db_name in SYSTEM_DBS or db_name == odoo.tools.config["db_template"]:
        return False
    exposed = odoo.tools.config["db_name"]
    return not exposed or db_name in exposed


class DatabaseExists(Warning):
    pass


def database_identifier(cr: BaseCursor, name: str) -> SQL:
    name = psycopg_sql.Identifier(name).as_string(cr.connection)
    return SQL(name.replace("%", "%%"))


def check_db_management_enabled(func: Callable, /) -> Callable:

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
    if passwd and odoo.tools.config.verify_admin_password(passwd):
        return True
    raise odoo.exceptions.AccessDenied


def _drop_conn(cr: BaseCursor, db_name: str) -> None:
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
