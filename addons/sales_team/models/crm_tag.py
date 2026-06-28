# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class CrmTag(models.Model):
    _name = 'crm.tag'
    _inherit = ['tag.mixin']
    _description = "CRM Tag"

    parent_id = fields.Many2one(
        'crm.tag',
        string="Parent Tag",
        index=True,
        ondelete='cascade',
    )
    child_ids = fields.One2many('crm.tag', 'parent_id', string="Child Tags")
