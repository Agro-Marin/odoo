from __future__ import annotations

import logging
import re
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


# The four per-app read-only modules were first merged into `group_readonly`
# (its pre_init_hook re-homed their xmlids, suffixing every ACL name with the
# domain that grants it), then `group_readonly` itself was split back into
# stock, sales_team, purchase and mrp. A database that never installed the
# intermediate module still holds the original xmlids, so the split's
# adoptions found nothing to adopt and the loader created a second group
# under the same name -- `res_groups_name_src_uniq` rejected it.
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


def absorb_readonly_forerunners(cr: BaseCursor) -> int:
    """Replay the merge into `group_readonly` for databases that skipped it.

    Idempotent: a database that installed the intermediate module, or one
    whose split migrations already ran, holds no row under the forerunner
    names and nothing moves.
    """
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


# Every column that stores an expression naming a model or a field: QWeb arch,
# a template body or recipient, server-action Python, a domain, a context, an
# order. Each entry is (table, jsonb columns, text columns, scope column, scope
# holds an ir_model id). A rename migration that hand-picks a subset of these is
# how a renamed name survives an upgrade in the one artifact its author forgot.
_EXPRESSION_SOURCES = (
    ("ir_ui_view", ("arch_db",), (), "model", False),
    (
        "mail_template",
        ("body_html", "subject"),
        # The recipient and scheduling fields are inline templates too, and a
        # rename breaks `partner_to` exactly as readily as a body -- more
        # quietly, because the mail then addresses nobody rather than raising.
        ("email_from", "email_to", "email_cc", "partner_to", "reply_to", "scheduled_date"),
        "model_id",
        True,
    ),
    ("ir_act_server", (), ("code",), "model_id", True),
    ("ir_filters", (), ("domain", "context", "sort"), "model_id", False),
    ("ir_act_window", (), ("domain", "context"), "res_model", False),
)

# `old` becomes a POSIX regex and `new` a regexp_replace replacement, and both
# are spliced into a jsonb column through its ::text form. Restricting them to
# characters that are literal in all three -- and that JSON never escapes -- is
# what makes that safe. `&` and `\` carry meaning in a replacement, a quote
# would be escaped inside the ::text form, and neither belongs in a name.
_RENAMEABLE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.]*\Z")
_REPLACEMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.()]*\Z")


def rename_in_stored_expressions(
    cr: BaseCursor,
    old: str,
    new: str,
    *,
    model: str | None = None,
) -> int:
    """Repoint every stored expression that still names ``old`` at ``new``.

    Module-owned XML is reloaded from source by the upgrade itself. This is for
    what the upgrade will never rewrite: records users authored, and records a
    module ships inside ``<data noupdate="1">`` -- which is every
    ``mail.template``, so a rename that skips this leaves a template that raises
    only when something finally tries to send it, months later.

    ``model`` scopes the rewrite to artifacts bound to that model and is
    **required for a bare field name**, which is only unique within its own
    model: an unscoped ``stage_id`` would rewrite ``crm.lead``'s too. A dotted
    ``old`` -- a model name, or a qualified expression like ``company_id.phone``
    -- already says which record it reads, so it is rewritten everywhere and
    ``model`` may be omitted.

    Matching is whole-word, so ``phone`` does not touch ``phone_ids`` and the
    statement stops matching once it has run: calling this twice is a no-op, and
    so is calling it on a database somebody already repaired by hand.

    Scoping by model cannot reach a QWeb view, whose ``model`` is null; pass a
    dotted ``old``, or repair such a view by hand.

    :param cr: database cursor
    :param str old: name as it was written
    :param str new: name to write instead
    :param model: model owning ``old``, or None when ``old`` is dotted
    :return: number of rows rewritten
    :rtype: int
    """
    if not _RENAMEABLE.match(old) or not _REPLACEMENT.match(new):
        raise ValueError(f"cannot rewrite {old!r} to {new!r}: unsupported characters")
    if model is None and "." not in old:
        raise ValueError(f"{old!r} is a bare field name and needs model= to scope it")

    pattern = r"\y%s\y" % old.replace(".", r"\.")
    tables = set(get_tables_existing(cr, [name for name, *_ in _EXPRESSION_SOURCES]))
    rewritten = 0
    for table, jsonb_columns, text_columns, scope_column, scope_is_id in (
        _EXPRESSION_SOURCES
    ):
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
