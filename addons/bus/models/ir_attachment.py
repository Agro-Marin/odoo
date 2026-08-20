from odoo import models


class IrAttachment(models.Model):
    _name = "ir.attachment"
    _inherit = ["ir.attachment", "mixin.bus.listener"]

    def _bus_channel(self):
        return self.env.user
