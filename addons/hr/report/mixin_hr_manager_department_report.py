from odoo import api, fields, models


class MixinHrManagerDepartmentReport(models.AbstractModel):
    _name = "mixin.hr.manager.department.report"
    _description = "Hr Manager Department Report"
    _auto = False

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    has_department_manager_access = fields.Boolean(
        search="_search_has_department_manager_access",
        compute="_compute_has_department_manager_access",
    )

    def _get_managed_department_ids(self):
        return self.env["hr.department"]._search(
            [("manager_id", "in", self.env.user.employee_ids.ids)]
        )

    def _search_has_department_manager_access(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [
            "|",
            ("employee_id.user_id", "=", self.env.user.id),
            (
                "employee_id.department_id",
                "child_of",
                tuple(self._get_managed_department_ids()),
            ),
        ]

    @api.depends_context("uid")
    @api.depends("employee_id")
    def _compute_has_department_manager_access(self):
        employees = self.env["hr.employee"].search(
            [
                "|",
                ("user_id", "=", self.env.user.id),
                (
                    "department_id",
                    "child_of",
                    tuple(self._get_managed_department_ids()),
                ),
            ]
        )
        for report in self:
            report.has_department_manager_access = report.employee_id in employees
