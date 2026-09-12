from odoo import models

from . import approval_trace as trace


class MixinApprovalSource(models.AbstractModel):
    _name = "mixin.approval.source"
    _description = "Record an Approval Request Is Raised For"

    def _filter_approval_step_user_ids(self, step, user_ids: set[int]) -> set[int]:
        """Of the users `step` would let decide this document, the ones its own
        policy lets decide it. Routing, the quorum check and the approval button
        all read the narrowed pool."""
        trace.STEPS.event(
            "document_policy_default",
            model=self._name,
            step=step.id,
            users=len(user_ids),
            narrowed=False,
        )
        return user_ids

    def _get_approval_activity_values(self, approver) -> dict:
        """Values of this record's own to put on the activity asking `approver`, when
        the engine asks on the record rather than on the request."""
        return {}

    def _get_approval_activity_type(self, approver, step_type):
        """The activity type `approver` is asked with on this document; the step's by
        default. A document whose asking depends on its own progress chooses here."""
        trace.ACTIVITY.event(
            "activity_type_default",
            model=self._name,
            approver=approver.id,
            step_type=step_type.id if step_type else None,
        )
        return step_type
