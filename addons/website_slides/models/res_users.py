from collections import defaultdict

from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._enroll_in_group_channels()
        return users

    def write(self, vals):
        res = super().write(vals)
        if "group_ids" in vals:
            self._enroll_in_group_channels()
        return res

    def _enroll_in_group_channels(self):
        channels = self.env["slide.channel"]
        if not channels._channel_ids_by_enroll_group():
            return
        partners_by_channels = defaultdict(lambda: self.env["res.partner"])
        for user in self:
            if enrolling := channels._enrolling_channels(user.all_group_ids):
                partners_by_channels[enrolling] |= user.partner_id
        for enrolling, partners in partners_by_channels.items():
            enrolling._action_add_members(partners)

    def prepare_rank_email_links(self):
        res = super().prepare_rank_email_links()
        res.append({"url": "/slides", "label": self.env._("See our eLearning")})
        return res
