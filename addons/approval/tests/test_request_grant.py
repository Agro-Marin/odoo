from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestRequestGrant(ApprovalCommon):
    """A pending request approved by an authority outside its decisions.

    Time off lets the system validate a leave whose request is still pending. A
    decision needs an approver row, and recording one for a row nobody decided would
    name a decider who never acted, so the approval is its own fact on the request.
    """

    def _pending_request(self, minimum=2):
        category = self._make_category(
            name=f"Grant {self.id()}",
            approvers=[self.approver_1, self.approver_2][:minimum],
            approval_minimum=minimum,
        )
        request = self._prepare_request(category)
        self.assertEqual(request.state, "pending")
        return request

    def test_a_pending_request_approved_without_a_decision_names_no_decider(self):
        request = self._pending_request()
        self.assertTrue(request._get_approval_activities())

        request.with_user(self.manager_user)._approve_without_decision(
            "Validated by the system"
        )

        self.assertEqual(request.state, "approved")
        self.assertEqual(request.granted_by_user_id, self.manager_user)
        self.assertTrue(request.date_approval_granted)
        self.assertRecordValues(
            request.approver_ids,
            [
                {
                    "state": "waiting",
                    "decided_by_user_id": False,
                    "decision_date": False,
                },
                {
                    "state": "waiting",
                    "decided_by_user_id": False,
                    "decision_date": False,
                },
            ],
        )
        self.assertFalse(request.pending_approver_ids)
        self.assertFalse(request._get_approval_activities())

    def test_a_decision_already_given_stays_as_given(self):
        request = self._pending_request()
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "pending")

        request._approve_without_decision("Validated by the system")

        first = request.approver_ids.filtered(
            lambda row: row.user_id == self.approver_1
        )
        second = request.approver_ids - first
        self.assertRecordValues(
            first, [{"state": "approved", "decided_by_user_id": self.approver_1.id}]
        )
        self.assertRecordValues(
            second, [{"state": "waiting", "decided_by_user_id": False}]
        )

    def test_only_a_pending_request_is_approved_without_a_decision(self):
        category = self._make_category(
            name=f"Grant draft {self.id()}", approvers=[self.approver_1]
        )
        draft = self._prepare_request(category, confirm=False)
        with self.assertRaises(UserError):
            draft._approve_without_decision("Not submitted")

        approved = self._pending_request(minimum=1)
        approved.with_user(self.approver_1).action_approve()
        with self.assertRaises(UserError):
            approved._approve_without_decision("Already approved")

    def test_withdrawing_from_a_granted_request_is_refused(self):
        request = self._pending_request()
        request.with_user(self.approver_1).action_approve()
        request._approve_without_decision("Validated by the system")

        self.assertFalse(request.with_user(self.approver_1).can_withdraw)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_withdraw()
        self.assertEqual(request.state, "approved")

    def test_a_granted_request_can_be_revoked_and_reset(self):
        request = self._pending_request()
        request._approve_without_decision("Validated by the system")

        request._revoke("refused", "Refused after validation")
        self.assertEqual(request.state, "refused")

        request._force_draft()
        self.assertFalse(request.granted_by_user_id)
        self.assertFalse(request.revoked_state)
        self.assertEqual(request.state, "new")

    def test_the_source_document_is_told_once(self):
        category = self._make_category(
            name=f"Grant Notify Cat {self.id()}", approvers=[self.approver_1]
        )
        doc = self.env["approval.test.document"].create(
            {
                "name": "Doc approved without a decision",
                "partner_id": self.partner.id,
                "test_category_id": category.id,
            },
        )
        doc.action_create_approval_request()

        doc.approval_request_id._approve_without_decision("Validated by the system")

        self.assertEqual(doc.last_approval_state, "approved")
        self.assertEqual(doc.hook_call_count, 1)
