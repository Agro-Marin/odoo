from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from odoo.db.schema import get_tables_existing
from odoo.libs.sql import SQL

if TYPE_CHECKING:
    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)


def adopt_xmlids(
    cr: BaseCursor,
    from_module: str,
    to_module: str,
    names: Iterable[str],
    renamed: Mapping[str, str] | None = None,
) -> int:
    # Re-homing an xmlid before the adopting module's data loads makes the
    # loader update the existing row in place instead of creating a second
    # record nobody references -- for a group, one nobody is a member of.
    moved = 0
    for old, new in {**dict.fromkeys(names), **(renamed or {})}.items():
        cr.execute(
            SQL(
                "UPDATE ir_model_data SET module = %s, name = %s "
                "WHERE module = %s AND name = %s",
                to_module,
                new or old,
                from_module,
                old,
            )
        )
        moved += cr.rowcount
    if moved:
        _logger.info("%s adopted %d record(s) from %s", to_module, moved, from_module)
    return moved


def remove_xmlid_records(cr: BaseCursor, module: str, names: Iterable[str]) -> int:
    cr.execute(
        SQL(
            "SELECT model, res_id FROM ir_model_data "
            "WHERE module = %s AND name = ANY(%s)",
            module,
            list(names),
        )
    )
    by_model: dict[str, list[int]] = defaultdict(list)
    for model, res_id in cr.fetchall():
        by_model[model].append(res_id)
    tables = {model: model.replace(".", "_") for model in by_model}
    existing = set(get_tables_existing(cr, tables.values()))
    deleted = 0
    for model, ids in by_model.items():
        if tables[model] not in existing:
            continue
        cr.execute(
            SQL("DELETE FROM %s WHERE id = ANY(%s)", SQL.identifier(tables[model]), ids)
        )
        deleted += cr.rowcount
    cr.execute(
        SQL(
            "DELETE FROM ir_model_data WHERE module = %s AND name = ANY(%s)",
            module,
            list(names),
        )
    )
    return deleted


def retire_empty_module(cr: BaseCursor, module: str) -> None:
    # A module whose every record has been adopted elsewhere must not stay
    # `installed`: its manifest is gone or uninstallable, and every registry
    # load would warn that it could not be loaded.
    cr.execute(SQL("SELECT 1 FROM ir_model_data WHERE module = %s LIMIT 1", module))
    if cr.fetchone():
        return
    cr.execute(
        SQL(
            "UPDATE ir_module_module SET state = 'uninstalled', db_version = NULL "
            "WHERE name = %s AND state != 'uninstalled'",
            module,
        )
    )
    retired = cr.rowcount > 0
    cr.execute(
        SQL(
            "DELETE FROM ir_module_module_dependency "
            "WHERE module_id = (SELECT id FROM ir_module_module WHERE name = %s)",
            module,
        )
    )
    if retired:
        _logger.info("%s retired: every record it shipped now lives elsewhere", module)
