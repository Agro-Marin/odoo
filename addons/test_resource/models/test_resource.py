# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResourceTest(models.Model):
    _name = 'resource.test'
    _description = 'Test Resource Model'
    _inherit = ['mixin.resource']

    name = fields.Char()
