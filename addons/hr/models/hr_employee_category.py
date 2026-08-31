from odoo import fields, models


class HrEmployeeCategory(models.Model):
    _name = "hr.employee.category"
    _description = "Employee Category"
    _inherit = ["mixin.tag"]

    employee_ids = fields.Many2many(
        "hr.employee",
        "employee_category_rel",
        "category_id",
        "employee_id",
        string="Employees",
    )
