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
