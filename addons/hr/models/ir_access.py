from odoo import models


class IrAccess(models.Model):
    _inherit = "ir.access"

    def _access_bind_employees(self) -> list[int]:
        # every employee record of the principal, archived and other companies'
        # included, as the paths `employee_id.user_id = user.id` read them
        self.env["hr.employee"].flush_model(["user_id"])
        self.env.cr.execute(
            "SELECT id FROM hr_employee WHERE user_id = %s ORDER BY id",
            [self.env.uid],
        )
        return [employee_id for (employee_id,) in self.env.cr.fetchall()]

    def _access_bind_units(self) -> list[int]:
        # the departments the principal's active employees work in now
        self.env["hr.employee"].flush_model(["user_id", "active", "current_version_id"])
        self.env["hr.version"].flush_model(["department_id"])
        self.env.cr.execute(
            """
            SELECT DISTINCT version.department_id
              FROM hr_employee employee
              JOIN hr_version version ON version.id = employee.current_version_id
             WHERE employee.user_id = %s
               AND employee.active
               AND version.department_id IS NOT NULL
             ORDER BY 1
            """,
            [self.env.uid],
        )
        return [department_id for (department_id,) in self.env.cr.fetchall()]
