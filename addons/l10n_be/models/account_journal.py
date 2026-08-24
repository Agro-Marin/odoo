# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    invoice_reference_model = fields.Selection(selection_add=[
        ('be', 'Belgium (+++000/2024/00182+++)')
        ], ondelete={'be': lambda recs: recs.write({'invoice_reference_model': 'odoo'})})
