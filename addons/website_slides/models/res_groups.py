from odoo import models


class ResGroups(models.Model):
    _inherit = "res.groups"

    def write(self, vals):
        write_res = super().write(vals)
        channels = self.env["slide.channel"]
        if vals.get("user_ids") and channels._channel_ids_by_enroll_group():
            channels._enrolling_channels(self.all_implied_ids)._add_groups_members()
        return write_res
