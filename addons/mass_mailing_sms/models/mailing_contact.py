# -*- coding: utf-8 -*-
from odoo import fields, models


class MailingContact(models.Model):
    _name = 'mailing.contact'
    _inherit = ['mailing.contact', 'mixin.mail.thread.phone']

    mobile = fields.Char(string='Mobile')
