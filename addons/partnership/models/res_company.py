from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    partnership_label = fields.Char(
        default=lambda s: s.env._('Members'), translate=True,
        help="Name used to refer to affiliates: partners, members, alumnis, etc...",
    )
