r"""Pre-migration: ``res.partner.category_id`` becomes ``res.partner.tag_ids``.

Step 2 of the tag rename. 1.30 renamed the MODEL; this renames the FIELD, which
was left alone there because ``category_id`` is declared by some thirty unrelated
models and needed its own pass.

The name was wrong twice over: it said "category" for a model that is now
``res.partner.tag``, and it was SINGULAR for a Many2many -- `category_id` holding
a set of tags, presented in the UI as "Tags" and read by consumers as a
recordset. ``tag_ids`` fixes both.

WHY PRE. The Many2many has no column on ``res_partner``; its data lives in
``res_partner_res_partner_tag_rel``, whose second column is named after the
field. Renaming the field in code makes the reloaded registry derive
``tag_id`` and ADD it empty beside the populated ``category_id`` -- every tag on
every partner stranded in a column nothing reads, with no error. The column has
to move before the ORM looks.

``ir_model_fields`` is renamed rather than left to be rebuilt for the same
reason: the ORM would otherwise treat the ``category_id`` row as an orphan of a
field the code no longer declares.

Idempotent: each guard stops matching once the rename has happened.
"""

import logging
import typing

from odoo.db import schema
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

REL = "res_partner_res_partner_tag_rel"


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    if schema.table_exists(cr, REL) and schema.column_exists(cr, REL, "category_id"):
        if schema.column_exists(cr, REL, "tag_id"):
            raise ValueError(
                f"{REL} carries both category_id and tag_id. Refusing to guess "
                f"which one holds the links; resolve by hand."
            )
        cr.execute(
            SQL(
                "ALTER TABLE %s RENAME COLUMN %s TO %s",
                SQL.identifier(REL),
                SQL.identifier("category_id"),
                SQL.identifier("tag_id"),
            )
        )
        _logger.info("%s.category_id renamed to tag_id.", REL)

    cr.execute(
        """
        UPDATE ir_model_fields SET name = 'tag_ids'
         WHERE model = 'res.partner' AND name = 'category_id'
           AND NOT EXISTS (SELECT 1 FROM ir_model_fields
                            WHERE model = 'res.partner' AND name = 'tag_ids')
        """
    )
    cr.execute(
        "UPDATE ir_model_fields SET column2 = 'tag_id' "
        "WHERE relation_table = %s AND column2 = 'category_id'",
        (REL,),
    )
    cr.execute(
        "UPDATE ir_model_fields SET column1 = 'tag_id' "
        "WHERE relation_table = %s AND column1 = 'category_id'",
        (REL,),
    )
    cr.execute(
        """
        UPDATE ir_model_data SET name = 'field_res_partner__tag_ids'
         WHERE module = 'base' AND model = 'ir.model.fields'
           AND name = 'field_res_partner__category_id'
           AND NOT EXISTS (SELECT 1 FROM ir_model_data
                            WHERE module = 'base' AND model = 'ir.model.fields'
                              AND name = 'field_res_partner__tag_ids')
        """
    )
