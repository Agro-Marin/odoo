r"""Pre-migration: ``partner_category_id`` becomes ``partner_tag_id``.

``account.analytic.distribution.model`` selects a distribution by partner tag.
Its Many2one already pointed at ``res.partner.category`` before 1.26 renamed that
model to ``res.partner.tag``, so after the rename the field read
``partner_category_id -> res.partner.tag``, labelled "Partner Category", with
help text offering to match "a partner category" that no longer exists under
that name anywhere.

This is a plain stored column on ``account_analytic_distribution_model``, so
renaming the field in code without renaming the column makes the ORM add
``partner_tag_id`` empty and drop ``partner_category_id`` as a field the code no
longer declares -- taking every configured distribution rule with it.

Idempotent: the guard stops matching once the column has moved.
"""

import logging
import typing

from odoo.db import schema
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

TABLE = "account_analytic_distribution_model"


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    if not schema.table_exists(cr, TABLE):
        return
    if not schema.column_exists(cr, TABLE, "partner_category_id"):
        return
    if schema.column_exists(cr, TABLE, "partner_tag_id"):
        raise ValueError(
            f"{TABLE} carries both partner_category_id and partner_tag_id. "
            f"Refusing to guess which one the rules use; resolve by hand."
        )

    cr.execute(
        SQL(
            "ALTER TABLE %s RENAME COLUMN %s TO %s",
            SQL.identifier(TABLE),
            SQL.identifier("partner_category_id"),
            SQL.identifier("partner_tag_id"),
        )
    )
    cr.execute(
        """
        UPDATE ir_model_fields SET name = 'partner_tag_id'
         WHERE model = 'account.analytic.distribution.model'
           AND name = 'partner_category_id'
        """
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = 'field_account_analytic_distribution_model__partner_tag_id'
         WHERE model = 'ir.model.fields'
           AND name = 'field_account_analytic_distribution_model__partner_category_id'
        """
    )
    _logger.info("%s.partner_category_id renamed to partner_tag_id.", TABLE)
