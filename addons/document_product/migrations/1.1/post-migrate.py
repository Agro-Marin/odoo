"""Backfill ``documents.document`` from ``product.document`` (1.1).

Expand step of the product-document dissolution: every ``product.document``
gains a ``documents.document`` over the same attachment, and the discriminator
columns the extending modules just added are copied across. Nothing reads the
new rows yet, and ``product.document`` is left untouched.

Both shapes occur in the same cluster, and both must be handled. Whether an
attachment on a product already carries a ``documents.document`` depends on
``res_company.documents_product_settings``, which defaults off: a company that
never enabled Product Documents has only the ``product.document`` sidecar, one
that did has both. So this matches on the attachment and updates, else creates
-- a create-only pass would double every document in the second case, and an
update-only pass would silently skip every document in the first.

The row creation deliberately does NOT go through ``mixin.documents``: that
path is gated on ``documents_product_settings`` too, and the data being
migrated exists regardless of the setting.

Idempotent: re-running matches the rows it created last time and only updates.
"""

import logging

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.db.schema import column_exists, table_exists

_logger = logging.getLogger(__name__)

# Column name on both tables; each is owned by the module that added it, so any
# subset of them may be absent depending on what is installed.
DISCRIMINATORS = (
    "attached_on_sale",
    "attached_on_mrp",
    "shown_on_product_page",
    "is_gelato",
    "origin_attachment_id",
)


def migrate(cr, version):
    if not table_exists(cr, "product_document"):
        return
    created = _create_missing_documents(cr)
    copied = _copy_discriminators(cr)
    _logger.info(
        "product.document backfill: %s documents.document created, "
        "columns copied: %s",
        created,
        ", ".join(copied) or "none",
    )


def _create_missing_documents(cr):
    cr.execute(
        """
        SELECT pd.ir_attachment_id, a.company_id
          FROM product_document pd
          JOIN ir_attachment a ON a.id = pd.ir_attachment_id
         WHERE NOT EXISTS (
                   SELECT 1 FROM documents_document d
                    WHERE d.attachment_id = pd.ir_attachment_id
               )
        """
    )
    rows = cr.fetchall()
    if not rows:
        return 0

    env = Environment(cr, SUPERUSER_ID, {})
    folder_by_company = {
        company.id: company.product_folder_id
        for company in env["res.company"].search([])
    }
    # `name`, `res_model` and `res_id` all compute from `attachment_id`, so the
    # attachment is the only value that has to be supplied.
    env["documents.document"].create(
        [
            {
                "attachment_id": attachment_id,
                "company_id": company_id,
                "folder_id": folder_by_company.get(company_id, env["documents.document"]).id,
            }
            for attachment_id, company_id in rows
        ]
    )
    return len(rows)


def _copy_discriminators(cr):
    copied = []
    for column in DISCRIMINATORS:
        if not column_exists(cr, "product_document", column):
            continue
        if not column_exists(cr, "documents_document", column):
            continue
        cr.execute(
            f"""
            UPDATE documents_document d
               SET {column} = pd.{column}
              FROM product_document pd
             WHERE pd.ir_attachment_id = d.attachment_id
               AND pd.{column} IS NOT NULL
               AND d.{column} IS DISTINCT FROM pd.{column}
            """
        )
        copied.append(column)
    return copied
