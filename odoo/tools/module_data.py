from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from odoo.db.schema import get_tables_existing
from odoo.libs.sql import SQL

if TYPE_CHECKING:
    from typing import Any, Protocol

    from odoo.db import BaseCursor

    class _SqlCursor(Protocol):
        """The four members these helpers touch.

        Narrower than `BaseCursor` on purpose: a migration script or a test can hand
        them anything that answers SQL, which is how `tests/test_module_data.py`
        exercises the statements without a database.
        """

        rowcount: int

        def execute(self, query: Any, params: Any = None) -> Any: ...
        def fetchall(self) -> list[tuple[Any, ...]]: ...
        def fetchone(self) -> tuple[Any, ...] | None: ...


_logger = logging.getLogger(__name__)


def adopt_xmlids(
    cr: _SqlCursor,
    from_module: str,
    to_module: str,
    names: Iterable[str],
    renamed: Mapping[str, str] | None = None,
) -> int:
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


def retire_empty_module(cr: _SqlCursor, module: str) -> None:
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


READONLY_FORERUNNERS: Mapping[str, str] = {
    "stock_group_readonly": "stock",
    "sale_group_readonly": "sale",
    "purchase_group_readonly": "purchase",
    "mrp_group_readonly": "mrp",
}
READONLY_MERGED_MODULE = "group_readonly"
_ACCESS_PREFIX = "access_"
_READONLY_SUFFIX = "_readonly"


def _readonly_merged_name(name: str, domain: str) -> str:
    if name.startswith(_ACCESS_PREFIX) and name.endswith(_READONLY_SUFFIX):
        return f"{name[: -len(_READONLY_SUFFIX)]}_{domain}{_READONLY_SUFFIX}"
    return name


def absorb_readonly_forerunners(cr: _SqlCursor) -> int:
    moved = 0
    for module, domain in READONLY_FORERUNNERS.items():
        cr.execute(SQL("SELECT id, name FROM ir_model_data WHERE module = %s", module))
        rows = cr.fetchall()
        for row_id, name in rows:
            cr.execute(
                SQL(
                    "UPDATE ir_model_data SET module = %s, name = %s WHERE id = %s",
                    READONLY_MERGED_MODULE,
                    _readonly_merged_name(name, domain),
                    row_id,
                )
            )
        moved += len(rows)
        if rows:
            _logger.info(
                "%s absorbed %d record(s) from %s",
                READONLY_MERGED_MODULE,
                len(rows),
                module,
            )
            retire_empty_module(cr, module)
    return moved


_EXPRESSION_SOURCES = (
    ("ir_ui_view", ("arch_db",), (), "model", False),
    (
        "mail_template",
        ("body_html", "subject"),
        (
            "email_from",
            "email_to",
            "email_cc",
            "partner_to",
            "reply_to",
            "scheduled_date",
        ),
        "model_id",
        True,
    ),
    ("ir_act_server", (), ("code",), "model_id", True),
    ("ir_filters", (), ("domain", "context", "sort"), "model_id", False),
    ("ir_act_window", (), ("domain", "context"), "res_model", False),
)

_RENAMEABLE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.]*\Z")
_REPLACEMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.()]*\Z")


def rename_in_stored_expressions(
    cr: BaseCursor,
    old: str,
    new: str,
    *,
    model: str | None = None,
) -> int:
    if not _RENAMEABLE.match(old) or not _REPLACEMENT.match(new):
        raise ValueError(f"cannot rewrite {old!r} to {new!r}: unsupported characters")
    if model is None and "." not in old:
        raise ValueError(f"{old!r} is a bare field name and needs model= to scope it")

    pattern = r"\y%s\y" % old.replace(".", r"\.")
    tables = set(get_tables_existing(cr, [name for name, *_ in _EXPRESSION_SOURCES]))
    rewritten = 0
    for (
        table,
        jsonb_columns,
        text_columns,
        scope_column,
        scope_is_id,
    ) in _EXPRESSION_SOURCES:
        if table not in tables:
            continue
        scope = SQL("")
        if model is not None:
            scope = SQL(
                " AND %s = (SELECT id FROM ir_model WHERE model = %s)"
                if scope_is_id
                else " AND %s = %s",
                SQL.identifier(scope_column),
                model,
            )
        assignments = SQL(", ").join(
            SQL(
                "%s = regexp_replace(%s::text, %s, %s, 'g')%s",
                SQL.identifier(column),
                SQL.identifier(column),
                pattern,
                new,
                SQL("::jsonb") if is_jsonb else SQL(""),
            )
            for column, is_jsonb in (
                *((name, True) for name in jsonb_columns),
                *((name, False) for name in text_columns),
            )
        )
        guard = SQL(" OR ").join(
            SQL("%s::text ~ %s", SQL.identifier(column), pattern)
            for column in (*jsonb_columns, *text_columns)
        )
        cr.execute(
            SQL(
                "UPDATE %s SET %s WHERE (%s)%s",
                SQL.identifier(table),
                assignments,
                guard,
                scope,
            )
        )
        rewritten += cr.rowcount
    if rewritten:
        _logger.info(
            "renamed %s to %s in %d stored expression(s)%s",
            old,
            new,
            rewritten,
            f" of {model}" if model else "",
        )
    return rewritten


CRON_ACTION_SUFFIX = "_ir_actions_server"


def rehome_cron_xmlids(
    cr: _SqlCursor,
    from_module: str,
    to_module: str,
    renamed: Mapping[str, str],
) -> int:
    """Move `ir.cron` xmlids together with their server-action companions.

    Loading a cron from XML registers two xmlids, not one: the cron itself and
    the `ir.actions.server` it delegates to, named `<cron xmlid>_ir_actions_server`.
    A migration that renames or rehomes only the first leaves the second owned by
    a module that no longer declares it, and nothing goes wrong until that module
    is next in `updated_modules`. Then `ir.model.data._process_end()` reads the
    companion as stale and deletes it, which
    `ir_cron_ir_actions_server_id_fkey` refuses because it is `RESTRICT`.

    That failure lands in the stale-data sweep, which runs *after* every module
    has upgraded and committed, so an otherwise complete `-u all` exits non-zero
    with the whole database already migrated. Renaming the pair together is what
    keeps the sweep from ever seeing a half-moved cron.
    """
    pairs = {}
    for old, new in renamed.items():
        pairs[old] = new
        pairs[old + CRON_ACTION_SUFFIX] = new + CRON_ACTION_SUFFIX
    return adopt_xmlids(cr, from_module, to_module, (), pairs)


def repair_orphaned_cron_actions(cr: _SqlCursor) -> int:
    """Re-point companions left behind by a cron rename that moved only the cron.

    Only the companions that still drive a live `ir.cron` are repaired, because
    those are the ones whose deletion the foreign key refuses. The companion is
    re-pointed at the module and name its cron now answers to, never deleted: the
    server action carries the cron's `state`, `code` and `model_id`, so dropping
    it would take the schedule with it.

    A companion that drives no cron is ordinary dead data and is left alone --
    the owning module's own sweep removes it correctly, and a module whose sweep
    can never run is a different defect that has to name its rows deliberately.

    Idempotent, and safe on a database that has nothing to repair.
    """
    cr.execute(
        SQL(
            """
            SELECT stale.id, stale.module, stale.name, cron_data.module, cron_data.name
              FROM ir_model_data stale
              JOIN ir_cron cron ON cron.ir_actions_server_id = stale.res_id
              JOIN ir_model_data cron_data
                ON cron_data.model = 'ir.cron' AND cron_data.res_id = cron.id
             WHERE stale.model = 'ir.actions.server'
               AND stale.name LIKE %s
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data owner
                    WHERE owner.model = 'ir.cron'
                      AND owner.module = stale.module
                      AND owner.name = left(stale.name, -%s)
               )
            """,
            f"%{CRON_ACTION_SUFFIX}",
            len(CRON_ACTION_SUFFIX),
        )
    )
    repaired = 0
    for data_id, old_module, old_name, module, cron_name in cr.fetchall():
        name = cron_name + CRON_ACTION_SUFFIX
        cr.execute(
            SQL(
                "UPDATE ir_model_data SET module = %s, name = %s "
                "WHERE id = %s AND NOT EXISTS ("
                "    SELECT 1 FROM ir_model_data taken"
                "     WHERE taken.module = %s AND taken.name = %s AND taken.id != %s"
                ")",
                module,
                name,
                data_id,
                module,
                name,
                data_id,
            )
        )
        if cr.rowcount:
            repaired += 1
            _logger.info(
                "re-pointed %s.%s to %s.%s, the cron it actually drives",
                old_module,
                old_name,
                module,
                name,
            )
    return repaired
