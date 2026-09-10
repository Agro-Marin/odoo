from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _get_blacklisted_menu_ids(self):
        res = super()._get_blacklisted_menu_ids()
        if not (
            self.env.user.has_group("hr_attendance.group_hr_attendance_manager")
            and self.env.user.has_group("hr_holidays.group_hr_holidays_user")
        ):
            res.append(
                self.env.ref("hr_holidays_attendance.hr_leave_attendance_report").id
            )
        return res
