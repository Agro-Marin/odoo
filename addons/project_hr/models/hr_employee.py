from odoo import models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def write(self, vals):
        result = super().write(vals)
        if "resource_id" in vals and self.ids:
            tasks = (
                self.env["project.task"]
                .sudo()
                .search([("employee_ids", "in", self.ids)])
            )
            if tasks:
                tasks._sync_reservations()
        return result
