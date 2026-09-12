import functools
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

import odoo.exceptions
import odoo.tools
from odoo.libs.debug_log import DebugLog

if TYPE_CHECKING:
    from collections.abc import Callable

_logger = logging.getLogger("odoo.service.db")
_debug = DebugLog(__name__)


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


def check_db_name(name: str) -> None:
    if len(name) > DBNAME_MAX_LENGTH:
        _debug.logic("database.name_rejected", reason="too_long", length=len(name))
        raise ValueError(_DBNAME_TOO_LONG_MSG.format(name=name, length=len(name)))
    if not re.match(DBNAME_PATTERN, name):
        _debug.logic("database.name_rejected", reason="pattern", db=name)
        raise ValueError(_DBNAME_ERROR_MSG.format(name=name))


def check_db_management_enabled(func: Callable, /) -> Callable:

    @functools.wraps(func)
    def if_db_mgt_enabled(*args: Any, **kwargs: Any) -> Any:
        if not odoo.tools.config["list_db"]:
            _logger.error(
                "Database management functions blocked, admin disabled database listing"
            )
            _debug.logic("database.management_blocked", op=func.__name__)
            raise odoo.exceptions.AccessDenied
        _debug.pipeline("database.management_call", op=func.__name__)
        return func(*args, **kwargs)

    return if_db_mgt_enabled


def check_super(passwd: str) -> Literal[True]:
    if passwd and odoo.tools.config.is_valid_admin_password(passwd):
        _debug.pipeline("database.master_password_accepted")
        return True
    _debug.logic("database.master_password_rejected", empty=not passwd)
    raise odoo.exceptions.AccessDenied
