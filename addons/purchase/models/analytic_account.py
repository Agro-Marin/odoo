from odoo import _, api, fields, models


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    purchase_order_count = fields.Integer(
        string="Purchase Order Count",
        compute="_compute_purchase_order_count",
    )

    @api.depends("line_ids")
    def _compute_purchase_order_count(self):
        for account in self:
            account.purchase_order_count = self.env["purchase.order"].search_count(
                [
                    (
                        "line_ids.invoice_line_ids.analytic_line_ids.account_id",
                        "in",
                        account.ids,
                    ),
                ],
            )

    def action_view_purchase_orders(self):
        self.ensure_one()
        purchase_orders = self.env["purchase.order"].search(
            [("line_ids.invoice_line_ids.analytic_line_ids.account_id", "=", self.id)]
        )
        result = {
            "name": _("Purchase Orders"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "domain": [["id", "in", purchase_orders.ids]],
            "view_mode": "list,form",
        }
        if len(purchase_orders) == 1:
            result["view_mode"] = "form"
            result["res_id"] = purchase_orders.id
        return result
