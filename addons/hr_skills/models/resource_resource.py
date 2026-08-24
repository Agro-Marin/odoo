from odoo import fields, models


class ResourceResource(models.Model):
    _inherit = "resource.resource"

    employee_skill_ids = fields.One2many(related="employee_id.employee_skill_ids")
