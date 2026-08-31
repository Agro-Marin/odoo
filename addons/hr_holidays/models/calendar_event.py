from odoo import models


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    def _need_video_call(self):
        self.check_singleton()
        if self.res_model == "hr.leave":
            return False
        return super()._need_video_call()
