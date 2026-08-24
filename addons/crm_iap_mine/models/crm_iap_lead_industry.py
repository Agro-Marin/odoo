# -*- coding: utf-8 -*-
from odoo import fields, models

from odoo.addons.base.models.mixin_catalog import name_uniq_index


class CrmIapLeadIndustry(models.Model):
    """ Industry Tags of Acquisition Rules """
    _name = 'crm.iap.lead.industry'
    _description = 'CRM IAP Lead Industry'
    _order = 'sequence,id'

    name = fields.Char(string='Industry', required=True, translate=True)
    reveal_ids = fields.Char(required=True) # The list of reveal_ids for this industry, separated with ','
    color = fields.Integer(string='Color Index')
    sequence = fields.Integer('Sequence')

    _name_src_uniq = name_uniq_index(
        message='Industry name already exists!',
    )
