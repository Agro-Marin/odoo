from odoo import models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _convert_visitor_to_lead(self, partner, key):
        lead = super()._convert_visitor_to_lead(partner, key)
        visitor_sudo = self.livechat_visitor_id.sudo()
        if visitor_sudo:
            visitor_sudo.write({"lead_ids": [(4, lead.id)]})
            lead.country_id = lead.country_id or visitor_sudo.country_id
        return lead
