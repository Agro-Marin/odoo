from odoo import models


class MixinApprovalSource(models.AbstractModel):
    _name = "mixin.approval.source"
    _description = "Record an Approval Request Is Raised For"

    def _filter_approval_step_user_ids(self, step, user_ids: set[int]) -> set[int]:
        """Of the users `step` would let decide this document, the ones its own
        policy lets decide it. Routing, the quorum check and the approval button
        all read the narrowed pool."""
        return user_ids

    def _get_approval_activity_type(self, approver, step_type):
        """The activity type `approver` is asked with on this document; the step's by
        default. A document whose asking depends on its own progress chooses here."""
        return step_type
