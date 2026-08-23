from odoo import models


class AccountTax(models.Model):
    _inherit = "account.tax"


    def _get_used_tax_ids(self, tax_ids):
        used_taxes = super()._get_used_tax_ids(tax_ids)
        remaining_ids = tax_ids - used_taxes

        if remaining_ids:
            self.env["purchase.order.line"].flush_model(["tax_ids"])
            self.env.cr.execute(
                """
                SELECT id
                FROM
                    account_tax
                WHERE EXISTS(
                    SELECT 1
                    FROM account_tax_purchase_order_line_rel AS pur
                    WHERE account_tax.id = pur.account_tax_id
                )
                AND id = ANY(%s)
                """,
                [list(remaining_ids)],
            )

            used_taxes.update([tax[0] for tax in self.env.cr.fetchall()])

        return used_taxes
