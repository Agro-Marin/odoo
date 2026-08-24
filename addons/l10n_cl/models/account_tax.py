# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    l10n_cl_sii_code = fields.Integer('SII Code', aggregator=False)
