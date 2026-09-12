from odoo import models

from ..tools import debug_log as dbg


class MailActivity(models.Model):
    _inherit = "mail.activity"

    @dbg.timed
    def action_view_document(self):
        # OVERRIDE
        # when opening the "View all activities", and opening a return, we actually want the kanban view of return checks
        dbg.lifecycle.debug("action_view_document on %s", dbg.rec(self))
        if self.res_model != "account.return":
            return super().action_view_document()

        return (
            self.env["account.return"].browse(self.res_id).action_view_account_return()
        )
