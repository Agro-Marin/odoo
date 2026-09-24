from odoo import models


class MixinApprovalLifecycle(models.AbstractModel):
    _name = "mixin.approval.lifecycle"
    _inherit = ["mixin.approval.gate", "mixin.lifecycle"]
    _description = "Lifecycle Confirmed Through Approval"

    def _check_before_approval(self, verb):
        super()._check_before_approval(verb)
        if verb == "confirm":
            self._check_confirm_allowed()

    def _get_confirmed_state(self):
        return self.browse()._prepare_confirmation_values()["state"]

    def _is_operation_run_on_approval(self, operation):
        self.check_singleton()
        return self.state == "draft"

    def action_cancel(self):
        result = super().action_cancel()
        self._refuse_pending_approval()
        return result

    def action_draft(self):
        result = super().action_draft()
        self._clear_refused_approval_link()
        return result
