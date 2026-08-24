from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"
    _mailing_enabled = True
