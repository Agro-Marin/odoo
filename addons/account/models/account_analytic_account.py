from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    invoice_count = fields.Integer(compute="_compute_invoice_count")
    vendor_bill_count = fields.Integer(compute="_compute_vendor_bill_count")

    def _get_move_line_domain(self, move_types):
        return [
            ("move_id.move_type", "in", move_types),
            ("analytic_distribution", "in", self.ids),
        ]

    def _get_move_count_by_account(self, move_types):
        data = self.env["account.move.line"]._read_group(
            [("parent_state", "=", "posted"), *self._get_move_line_domain(move_types)],
            ["analytic_distribution"],
            ["__count"],
        )
        _debug.perf.count("analytic_move_counts", rows=len(data))
        return {int(account_id): move_count for account_id, move_count in data}

    @api.depends("line_ids")
    def _compute_invoice_count(self):
        counts = self._get_move_count_by_account(
            self.env["account.move"].get_sale_types(include_receipts=True)
        )
        for account in self:
            account.invoice_count = counts.get(account.id, 0)

    @api.depends("line_ids")
    @_debug.perf.timed
    def _compute_vendor_bill_count(self):
        counts = self._get_move_count_by_account(
            self.env["account.move"].get_purchase_types(include_receipts=True)
        )
        for account in self:
            account.vendor_bill_count = counts.get(account.id, 0)

    def _get_moves_action(self, move_types, default_move_type, name):
        self.check_singleton()
        account_move_lines = self.env["account.move.line"].search_fetch(
            self._get_move_line_domain(move_types),
            ["move_id"],
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "domain": [("id", "in", account_move_lines.move_id.ids)],
            "context": {"create": False, "default_move_type": default_move_type},
            "name": name,
            "view_mode": "list,form",
        }

    @_debug.perf.timed
    def action_view_invoice(self):
        _debug.lifecycle("action_view_invoice", records=self)
        return self._get_moves_action(
            self.env["account.move"].get_sale_types(include_receipts=True),
            "out_invoice",
            self.env._("Customer Invoices"),
        )

    @_debug.perf.timed
    def action_view_vendor_bill(self):
        _debug.lifecycle("action_view_vendor_bill", records=self)
        return self._get_moves_action(
            self.env["account.move"].get_purchase_types(include_receipts=True),
            "in_invoice",
            self.env._("Vendor Bills"),
        )
