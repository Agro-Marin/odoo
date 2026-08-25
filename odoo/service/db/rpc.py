import logging
from collections.abc import Callable
from typing import Any, Literal

import odoo.tools

from .._db_helpers import check_db_management_enabled, check_super
from .._dispatch import dispatch_table
from .._env import env_int
from .dump import exp_dump
from .lifecycle import exp_create_database, exp_drop, exp_duplicate_database, exp_rename
from .listing import (
    _rpc_db_exist,
    check_db_exposed,
    exp_list,
    exp_list_countries,
    exp_list_lang,
    exp_server_version,
)
from .restore import exp_restore

_logger = logging.getLogger("odoo.service.db")


@check_db_management_enabled
def exp_change_admin_password(new_password: str) -> Literal[True]:
    """Set the master admin password.

    Enforces a minimum length — the master password authorises every destructive
    DB operation, so it is the highest-value credential.  Default 8 chars;
    ``ODOO_ADMIN_PASSWORD_MIN_LENGTH`` can raise (never lower) the floor for
    stricter regimes.  Further complexity checks belong in the HTTP controller.
    """
    if not isinstance(new_password, str):
        raise TypeError(
            f"new_password must be a str, got {type(new_password).__name__!r}"
        )
    min_length = env_int("ODOO_ADMIN_PASSWORD_MIN_LENGTH", 8, minimum=8)
    if len(new_password) < min_length:
        raise ValueError(
            f"Master admin password must be at least {min_length} characters long."
        )
    old_hash = odoo.tools.config.options.get("admin_passwd")
    odoo.tools.config.set_admin_password(new_password)
    try:
        odoo.tools.config.save(["admin_passwd"])
    except Exception:
        if old_hash is None:
            odoo.tools.config.options.pop("admin_passwd", None)
        else:
            odoo.tools.config.options["admin_passwd"] = old_hash
        _logger.exception(
            "Failed to persist admin password change; reverted in-memory hash"
        )
        raise
    _logger.info("Master admin password updated")
    return True


@check_db_management_enabled
def exp_migrate_databases(databases: list[str]) -> Literal[True]:
    """Run ``base`` module upgrade against each listed database.

    Used by the HTTP database-manager "Migrate" action to bring several
    databases forward one Odoo version at a time.
    """
    for db in databases:
        check_db_exposed(db)
    for db in databases:
        _logger.info("migrate database %s", db)
        odoo.modules.registry.Registry.new(
            db, update_module=True, upgrade_modules={"base"}, run_tests=False
        )
    return True


def dispatch(method: str, params: list[Any]) -> Any:
    return dispatch_table(
        method,
        params,
        _DISPATCH,
        credentialed=_REQUIRES_MASTER_PASSWORD,
        check_credential=check_super,
    )


_DISPATCH: dict[str, Callable] = {
    "db_exist": _rpc_db_exist,
    "list": exp_list,
    "list_lang": exp_list_lang,
    "server_version": exp_server_version,
    "create_database": exp_create_database,
    "duplicate_database": exp_duplicate_database,
    "drop": exp_drop,
    "dump": exp_dump,
    "restore": exp_restore,
    "rename": exp_rename,
    "change_admin_password": exp_change_admin_password,
    "migrate_databases": exp_migrate_databases,
    "list_countries": exp_list_countries,
}


_REQUIRES_MASTER_PASSWORD: frozenset[str] = frozenset(
    {
        "create_database",
        "duplicate_database",
        "drop",
        "dump",
        "restore",
        "rename",
        "change_admin_password",
        "migrate_databases",
    }
)
