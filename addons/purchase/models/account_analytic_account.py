from odoo import api, fields, models
from odoo.tools.translate import _


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    purchase_order_count = fields.Integer(
        string="Purchase Order Count",
        compute="_compute_purchase_order_count",
    )

    def _get_purchase_order_domain(self):
        return [
            (
                "line_ids.invoice_line_ids.analytic_line_ids."
                + self.plan_id._column_name(),
                "in",
                self.ids,
            ),
        ]

    @api.depends("line_ids")
    def _compute_purchase_order_count(self):
        # `for account in self:` is load-bearing, not habit. This is one
        # `search_count` per record and `py_x2many_count` counts it as such --
        # but only for a loop whose iterable is literally `self`, so spelling it
        # `self.filtered("plan_id")` takes the debt off the gate's books without
        # removing it. `fields.Count` cannot express this one: the orders are
        # reached through a domain traversal, not an x2many on this record.
        for account in self:
            account.purchase_order_count = (
                self.env["purchase.order"].search_count(
                    account._get_purchase_order_domain(),
                )
                if account.plan_id
                else 0
            )

    def action_view_purchase_orders(self):
        self.check_singleton()
        result = {
            "name": _("Purchase Orders"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "domain": self._get_purchase_order_domain(),
            "view_mode": "list,form",
        }
        if self.purchase_order_count == 1:
            purchase_order = self.env["purchase.order"].search(
                self._get_purchase_order_domain(),
                limit=1,
            )
            result["view_mode"] = "form"
            result["res_id"] = purchase_order.id
        return result
