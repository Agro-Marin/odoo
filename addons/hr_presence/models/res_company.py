from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    hr_presence_last_compute_date = fields.Datetime()
