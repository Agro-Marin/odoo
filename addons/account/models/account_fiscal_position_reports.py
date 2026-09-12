from odoo import models

from ..tools import debug_log as dbg


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    @dbg.timed
    def action_create_foreign_taxes(self):
        # EXTENDS account
        dbg.lifecycle.debug("action_create_foreign_taxes on %s", dbg.rec(self))
        super().action_create_foreign_taxes()
        self.env["account.return.type"]._sync_all_returns(self.company_id.root_id)
