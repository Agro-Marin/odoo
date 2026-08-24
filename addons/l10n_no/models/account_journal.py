# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    invoice_reference_model = fields.Selection(selection_add=[
        ('no', 'Norway (000001024000083)')
    ], ondelete={'no': lambda recs: recs.write({'invoice_reference_model': 'odoo'})})
