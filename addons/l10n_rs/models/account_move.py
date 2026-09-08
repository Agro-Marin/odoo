from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_rs_turnover_date = fields.Date(string="Turnover Date")
