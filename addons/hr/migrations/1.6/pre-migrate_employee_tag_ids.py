r"""Pre-migration: ``hr.employee.category_ids`` becomes ``hr.employee.tag_ids``.

The employee side of the field rename that base 1.27 makes on ``res.partner``.
ADR-0086 step 6 merged ``hr.employee.category`` into ``res.partner.category``,
and 1.26 renamed that model to ``res.partner.tag`` -- so this field pointed at a
tag model under a category name, and ``res.users.category_ids`` related onto it.

The join table is named after the field on BOTH sides, so ``employee_category_rel``
and its ``category_id`` column move together with it. This runs from ``hr`` rather
than from ``base`` because the table is hr's: ``hr``'s own pre-migration runs
before ``hr``'s models are set up, which is early enough, and keeping each
module's schema in its own migration is what makes the ordering readable.

Without it the reloaded registry derives ``employee_tag_rel``, creates it EMPTY,
and every employee's tags are gone with no error -- the old table simply stops
being read. ``_drop_m2m_tables`` skips code-declared fields, so it would linger
full of the only copy of the data.

Idempotent: each guard stops matching once the rename has happened.
"""

import logging
import typing

from odoo.db import schema
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

OLD_REL = "employee_category_rel"
NEW_REL = "employee_tag_rel"


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    if schema.table_exists(cr, OLD_REL):
        if schema.table_exists(cr, NEW_REL):
            raise ValueError(
                f"Both {OLD_REL} and {NEW_REL} exist. Refusing to guess which "
                f"one holds the employee tags; resolve by hand."
            )
        cr.execute(
            SQL(
                "ALTER TABLE %s RENAME TO %s",
                SQL.identifier(OLD_REL),
                SQL.identifier(NEW_REL),
            )
        )
        # Postgres keeps constraint and index names across a table rename.
        cr.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = %s::regclass AND conname LIKE %s",
            (NEW_REL, OLD_REL + "\\_%"),
        )
        for (conname,) in cr.fetchall():
            cr.execute(
                SQL(
                    "ALTER TABLE %s RENAME CONSTRAINT %s TO %s",
                    SQL.identifier(NEW_REL),
                    SQL.identifier(conname),
                    SQL.identifier(NEW_REL + conname[len(OLD_REL) :]),
                )
            )
        cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexname LIKE %s",
            (NEW_REL, OLD_REL + "\\_%"),
        )
        for (indexname,) in cr.fetchall():
            cr.execute(
                SQL(
                    "ALTER INDEX %s RENAME TO %s",
                    SQL.identifier(indexname),
                    SQL.identifier(NEW_REL + indexname[len(OLD_REL) :]),
                )
            )
        _logger.info("%s renamed to %s.", OLD_REL, NEW_REL)

    if schema.table_exists(cr, NEW_REL) and schema.column_exists(
        cr, NEW_REL, "category_id"
    ):
        cr.execute(
            SQL(
                "ALTER TABLE %s RENAME COLUMN %s TO %s",
                SQL.identifier(NEW_REL),
                SQL.identifier("category_id"),
                SQL.identifier("tag_id"),
            )
        )

    for model in ("hr.employee", "res.users"):
        cr.execute(
            """
            UPDATE ir_model_fields SET name = 'tag_ids'
             WHERE model = %s AND name = 'category_ids'
               AND NOT EXISTS (SELECT 1 FROM ir_model_fields
                                WHERE model = %s AND name = 'tag_ids')
            """,
            (model, model),
        )
        cr.execute(
            """
            UPDATE ir_model_data SET name = %s
             WHERE model = 'ir.model.fields' AND name = %s
               AND NOT EXISTS (SELECT 1 FROM ir_model_data
                                WHERE model = 'ir.model.fields' AND name = %s)
            """,
            (
                f"field_{model.replace('.', '_')}__tag_ids",
                f"field_{model.replace('.', '_')}__category_ids",
                f"field_{model.replace('.', '_')}__tag_ids",
            ),
        )
    cr.execute(
        "UPDATE ir_model_fields SET relation_table = %s WHERE relation_table = %s",
        (NEW_REL, OLD_REL),
    )
    cr.execute(
        "UPDATE ir_model_relation SET name = %s WHERE name = %s", (NEW_REL, OLD_REL)
    )
    for col in ("column1", "column2"):
        cr.execute(
            SQL(
                "UPDATE ir_model_fields SET %s = 'tag_id' "
                "WHERE relation_table = %s AND %s = 'category_id'",
                SQL.identifier(col),
                NEW_REL,
                SQL.identifier(col),
            )
        )
