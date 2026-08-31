from odoo.db import schema

OLD_REL = "account_payment_method_line_res_company_rel"
NEW_REL = "account_payment_channel_res_company_rel"


def migrate(cr, version):
    if not version:
        return

    if schema.column_exists(
        cr, "hr_expense", "payment_method_line_id"
    ) and not schema.column_exists(cr, "hr_expense", "payment_channel_id"):
        cr.execute(
            'ALTER TABLE "hr_expense" RENAME COLUMN "payment_method_line_id" TO "payment_channel_id"'
        )

    if schema.table_exists(cr, OLD_REL) and not schema.table_exists(cr, NEW_REL):
        cr.execute(f'ALTER TABLE "{OLD_REL}" RENAME TO "{NEW_REL}"')
        cr.execute(
            f'ALTER TABLE "{NEW_REL}" RENAME COLUMN "account_payment_method_line_id" TO "account_payment_channel_id"'
        )
        cr.execute(
            "UPDATE ir_model_relation SET name = %s WHERE name = %s", (NEW_REL, OLD_REL)
        )
