from odoo.db import schema


def migrate(cr, version):
    if not version:
        return

    if schema.column_exists(
        cr, "sale_order", "preferred_payment_method_line_id"
    ) and not schema.column_exists(cr, "sale_order", "preferred_payment_channel_id"):
        cr.execute(
            'ALTER TABLE "sale_order" RENAME COLUMN "preferred_payment_method_line_id" TO "preferred_payment_channel_id"'
        )
