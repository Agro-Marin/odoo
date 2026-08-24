from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    l10n_latam_check_ids = fields.One2many('l10n_latam.check', 'outstanding_line_id', string='Checks')
