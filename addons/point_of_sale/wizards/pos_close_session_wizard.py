from odoo import fields, models


class PosCloseSessionWizard(models.TransientModel):
    _name = "pos.close.session.wizard"
    _description = "Close Session Wizard"

    amount_to_balance = fields.Float("Amount to balance")
    account_id = fields.Many2one("account.account", "Destination account")
    account_readonly = fields.Boolean("Destination account is readonly")
    message = fields.Text("Information message")

    def action_close_session(self):
        session = self.env["pos.session"].browse(self.env.context["active_ids"])
        return session.action_pos_session_closing_control(
            self.account_id,
            self.amount_to_balance,
            {
                int(payment_method_id): diff
                for payment_method_id, diff in (
                    self.env.context.get("bank_payment_method_diffs") or {}
                ).items()
            },
        )
