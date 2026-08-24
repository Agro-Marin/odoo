from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    invoice_reference_model = fields.Selection(selection_add=[
        ('si', 'Slovenian 01 (SI01 25-1235-8403)')
        ], ondelete={'si': lambda recs: recs.write({'invoice_reference_model': 'odoo'})})
