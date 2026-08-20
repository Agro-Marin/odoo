from odoo import models


class ResUsers(models.Model):
    _name = "res.users"
    _inherit = ["res.users", "mixin.bus.listener"]

    def _bus_channel(self):
        return self.partner_id
