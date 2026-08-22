# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrEmployeeCategory(models.Model):
    _name = "hr.employee.category"
    _description = "Employee Category"
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, whose index replaces the `unique (name)`
    # constraint this model declared -- that one compared whole jsonb documents
    # once `name` became translatable. Flat: employee tags do not nest.
    _inherit = ["mixin.tag"]

    employee_ids = fields.Many2many(
        "hr.employee",
        "employee_category_rel",
        "category_id",
        "employee_id",
        string="Employees",
    )
