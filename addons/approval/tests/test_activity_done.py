from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalActivityDone(ApprovalCommon):
    """Marking an approval activity done, which is how Studio's approvals are granted."""

    def _activity_for(self, request, user):
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        return request.activity_ids.filtered(
            lambda a: a.activity_type_id == activity_type and a.user_id == user
        )

    def _row_for(self, request, user):
        return request.approver_ids.filtered(lambda a: a.user_id == user)

    def test_the_approver_marking_their_activity_done_approves(self):
        request = self._prepare_request(
            self._make_category(approvers=[self.approver_1])
        )
        activity = self._activity_for(request, self.approver_1)
        self.assertEqual(len(activity), 1)
        activity.with_user(self.approver_1).action_done()
        self.assertEqual(self._row_for(request, self.approver_1).state, "approved")
        self.assertEqual(request.state, "approved")
        self.assertFalse(activity.active)

    def test_the_feedback_given_while_approving_is_posted(self):
        request = self._prepare_request(
            self._make_category(approvers=[self.approver_1])
        )
        activity = self._activity_for(request, self.approver_1)
        activity.with_user(self.approver_1).action_feedback("Checked the figures")
        self.assertEqual(request.state, "approved")
        self.assertEqual(
            len(
                request.message_ids.filtered(
                    lambda message: "Checked the figures" in (message.body or "")
                )
            ),
            1,
        )

    def test_someone_else_marking_it_done_decides_nothing(self):
        """Studio's test_12_approval_activity_spoof."""
        request = self._prepare_request(
            self._make_category(approvers=[self.approver_1])
        )
        activity = self._activity_for(request, self.approver_1)
        activity.with_user(self.manager_user).action_done()
        self.assertEqual(self._row_for(request, self.approver_1).state, "pending")
        self.assertEqual(request.state, "pending")
        self.assertFalse(activity.active)

    def test_the_system_marking_it_done_decides_nothing(self):
        request = self._prepare_request(
            self._make_category(approvers=[self.approver_1])
        )
        activity = self._activity_for(request, self.approver_1)
        activity.action_done()
        self.assertEqual(self._row_for(request, self.approver_1).state, "pending")
        self.assertFalse(activity.active)

    def test_an_approval_that_cannot_be_recorded_leaves_the_activity_open(self):
        request = self._prepare_request(
            self._make_category(approvers=[self.approver_1])
        )
        activity = self._activity_for(request, self.approver_1)
        self.env["approval.decision.wizard"].with_user(self.approver_1).create(
            {
                "approver_id": self._row_for(request, self.approver_1).id,
                "decision_type": "change",
                "change_field": "reason",
                "note": "Say why this is needed.",
            }
        ).action_confirm_change()
        self.assertEqual(request.pending_change_field, "reason")
        self.assertTrue(activity.active)
        # Not assertRaises: it rolls back to its own savepoint, which would hide
        # whether marking the activity done is undone with the failed decision.
        raised = False
        try:
            activity.with_user(self.approver_1).action_done()
        except UserError:
            raised = True
        self.assertTrue(raised)
        self.assertTrue(activity.active, "nothing was decided, so it stays open")
        self.assertEqual(self._row_for(request, self.approver_1).state, "pending")
