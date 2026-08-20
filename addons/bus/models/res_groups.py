from odoo import models


class ResGroups(models.Model):
    _name = "res.groups"
    _inherit = ["res.groups", "mixin.bus.listener"]
