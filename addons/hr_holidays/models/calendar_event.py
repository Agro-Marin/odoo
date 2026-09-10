from odoo import models


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    def _is_video_call_required(self):
        self.check_singleton()
        if self.res_model == "hr.leave":
            return False
        return super()._is_video_call_required()
