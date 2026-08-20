from odoo import models


class ResUsersSettings(models.Model):
    _name = "res.users.settings"
    _inherit = ["res.users.settings", "mixin.bus.listener"]

    def _bus_channel(self):
        return self.user_id
