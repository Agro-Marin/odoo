from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = "hr.department"

    display_name = fields.Char(compute_sudo=True)
