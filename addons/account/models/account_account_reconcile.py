from odoo import models


class AccountAccount(models.Model):
    _inherit = "account.account"

    def action_view_reconcile(self):
        self.check_singleton()
        return self.env["account.move.line"]._action_view_unreconciled(
            extra_domain=[("account_id", "=", self.id)],
        )
