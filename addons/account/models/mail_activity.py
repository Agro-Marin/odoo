from odoo import models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    def action_view_document(self):
        # OVERRIDE
        # when opening the "View all activities", and opening a return, we actually want the kanban view of return checks
        if self.res_model != "account.return":
            return super().action_view_document()

        return (
            self.env["account.return"].browse(self.res_id).action_view_account_return()
        )
