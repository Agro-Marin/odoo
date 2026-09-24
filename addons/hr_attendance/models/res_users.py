from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _clean_attendance_officers(self):
        attendance_officers = (
            self.env["hr.employee"]
            .search([("attendance_manager_id", "in", self.ids)])
            .attendance_manager_id
        )
        officers_to_remove_ids = self - attendance_officers
        if officers_to_remove_ids:
            self.env["res.users.grant"].with_privilege(
                "hr_attendance.privilege_grant_attendance_officer",
                reason="no longer an attendance manager",
            )._revoke(
                officers_to_remove_ids,
                self.env.ref("hr_attendance.group_hr_attendance_officer"),
            )
