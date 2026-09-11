from odoo import models


class ResGroups(models.Model):
    _inherit = "res.groups"

    def write(self, vals):
        write_res = super().write(vals)
        if vals.get("user_ids"):
            self.env["slide.channel"].sudo().search(
                [("enroll_group_ids", "in", self._ids)]
            )._add_groups_members()
        return write_res
