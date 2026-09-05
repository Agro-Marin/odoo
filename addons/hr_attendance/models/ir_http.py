from odoo import api, models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @api.model
    def lazy_session_info(self):
        res = super().lazy_session_info()
        employee = self.env.user.employee_id
        if employee:
            res["attendance_user_data"] = employee._get_attendance_systray_data()
        return res
