# -*- coding: utf-8 -*-
from odoo import models


class CrmLead(models.Model):
    _inherit = 'crm.lead'
    _mailing_enabled = True
