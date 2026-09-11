from odoo import models
from odoo.exceptions import UserError

TIME_OFF_MODELS = ("hr.leave", "hr.leave.allocation")


class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    def _check_moved_from_time_off(self):
        if any(request.res_model in TIME_OFF_MODELS for request in self):
            raise UserError(
                self.env._(
                    "This approval belongs to a time off: approve or refuse it here, "
                    "and cancel it or send it back to approval from the time off itself."
                )
            )

    def _check_withdraw_allowed(self):
        self._check_moved_from_time_off()
        return super()._check_withdraw_allowed()

    def _check_reset_allowed(self):
        self._check_moved_from_time_off()
        return super()._check_reset_allowed()

    def _check_change_request_allowed(self):
        self._check_moved_from_time_off()
        return super()._check_change_request_allowed()

    def action_cancel(self):
        self._check_moved_from_time_off()
        return super().action_cancel()
