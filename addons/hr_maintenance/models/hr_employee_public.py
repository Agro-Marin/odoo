from odoo import fields, models


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    equipment_count = fields.Integer(related="employee_id.equipment_count")
