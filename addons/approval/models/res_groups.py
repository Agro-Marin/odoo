from odoo import models


class ResGroups(models.Model):
    _inherit = "res.groups"

    def write(self, vals):
        res = super().write(vals)
        if {"user_ids", "implied_ids", "all_user_ids"} & vals.keys():
            self.env["approval.request"]._invalidate_escalation_manager_cache()
        return res
