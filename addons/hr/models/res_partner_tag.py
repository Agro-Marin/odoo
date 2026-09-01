from odoo import fields, models


class ResPartnerTag(models.Model):
    _inherit = "res.partner.tag"

    employee_ids = fields.Many2many(
        "hr.employee",
        "employee_tag_rel",
        "tag_id",
        "employee_id",
        string="Employees",
    )
