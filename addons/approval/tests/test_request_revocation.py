from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestRequestRevocation(ApprovalCommon):
    """An approved request revoked by an authority outside its decisions.

    Time off lets an officer refuse a leave that was already validated. The engine's
    decisions only reach a pending request, and forcing a terminal state skips one that
    is already approved, so a revocation is its own fact on the request: the decisions
    it overturns stay as they were given.
    """

    def _approved_request(self):
        category = self._make_category(
            name=f"Revocation {self.id()}", approvers=[self.approver_1]
        )
        request = self._prepare_request(category)
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "approved")
        return request

    def test_an_approved_request_revoked_into_refused_keeps_its_decisions(self):
        request = self._approved_request()
        granted = request.date_approval_granted

        request.with_user(self.manager_user)._revoke(
            "refused", "Refused after validation"
        )

        self.assertEqual(request.state, "refused")
        self.assertEqual(request.revoked_state, "refused")
        self.assertEqual(request.revoked_by_user_id, self.manager_user)
        self.assertTrue(request.date_revoked)
        self.assertTrue(request.date_refused)
        self.assertEqual(request.date_approval_granted, granted)
        self.assertRecordValues(
            request.approver_ids,
            [{"state": "approved", "decided_by_user_id": self.approver_1.id}],
        )

    def test_an_approved_request_revoked_into_cancelled(self):
        request = self._approved_request()

        request._revoke("cancelled", "Cancelled after validation")

        self.assertEqual(request.state, "cancelled")
        self.assertTrue(request.date_cancelled)

    def test_only_an_approved_request_is_revoked(self):
        category = self._make_category(
            name=f"Revocation pending {self.id()}", approvers=[self.approver_1]
        )
        request = self._prepare_request(category)

        with self.assertRaises(UserError):
            request._revoke("refused", "Not approved yet")
        with self.assertRaises(ValueError):
            self._approved_request()._revoke("approved", "Not a revocation")

    def test_a_revocation_records_its_reason(self):
        request = self._approved_request()
        reason = self.env.ref("approval.refusal_reason_budget_exceeded")

        request._revoke(
            "refused", "Over budget", refusal_reason=reason, refusal_note="No money"
        )

        self.assertEqual(request.refusal_reason_id, reason)
        self.assertEqual(request.refusal_note, "No money")

    def test_a_revoked_request_reset_to_draft_is_a_clean_draft(self):
        request = self._approved_request()
        request._revoke("refused", "Refused after validation")

        request.action_reset_to_draft()

        self.assertEqual(request.state, "new")
        self.assertFalse(request.revoked_state)
        self.assertFalse(request.revoked_by_user_id)
        self.assertFalse(request.date_revoked)
        self.assertEqual(request.approver_ids.mapped("state"), ["new"])

    def test_a_revoked_request_cannot_be_withdrawn_from(self):
        request = self._approved_request()
        request._revoke("refused", "Refused after validation")

        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_withdraw()
        self.assertEqual(request.state, "refused")
