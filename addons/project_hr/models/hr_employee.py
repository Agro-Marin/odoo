from odoo import models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def write(self, vals):
        """Re-sync reservations of any task assigned to these employees
        when the link to the resource changes.

        Reservations carry a ``resource_id`` snapshot, not a related
        field, so an admin swapping ``employee.resource_id`` would leave
        existing reservations pointing at the stale resource until the
        next task-side write.  Forcing a sync here keeps both sides
        consistent.
        """
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
