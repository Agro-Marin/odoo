from odoo import api, fields, models
from odoo.tools.translate import _


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchase_order_count = fields.Integer(
        string="Purchase Order Count",
        compute="_compute_purchase_order_count",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("line_ids")
    def _compute_purchase_order_count(self):
        # Drives a single form smart button (analytic_account_views.xml), so it
        # is computed one record at a time — the per-account search_count is
        # fine here. If this field is ever exposed in a list/kanban, batch it by
        # plan_id first (a raw-SQL join would be needed, which bypasses ir.rule).
        for account in self:
            account.purchase_order_count = (
                self.env["purchase.order"].search_count(
                    [
                        (
                            "line_ids.invoice_line_ids.analytic_line_ids."
                            + account.plan_id._column_name(),
                            "in",
                            account.ids,
                        ),
                    ],
                )
                if account.plan_id
                else 0
            )

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_view_purchase_orders(self):
        self.ensure_one()
        purchase_orders = self.env["purchase.order"].search(
            [
                (
                    "line_ids.invoice_line_ids.analytic_line_ids."
                    + self.plan_id._column_name(),
                    "=",
                    self.id,
                ),
            ]
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
