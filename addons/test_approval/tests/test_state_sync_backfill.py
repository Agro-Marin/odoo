from odoo import SUPERUSER_ID
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalStateSyncBackfill(ApprovalCommon):
    """A document already in flight when its module adopts the engine gets the
    request it would have raised, and keeps the decisions it recorded before.

    The upgrade runs as the superuser, who raises no request on its own.
    """

    def _category(self, approvers=None):
        return self._make_category(
            name=f"Backfill {self.id()}",
            approvers=[self.approver_1] if approvers is None else approvers,
        )

    def _two_step_category(self, first_users, second_users):
        category = self._category(approvers=[])
        steps = self.env["approval.category.step"]
        for sequence, users in ((10, first_users), (20, second_users)):
            steps |= steps.create(
                {
                    "category_id": category.id,
                    "name": f"Step {sequence}",
                    "sequence": sequence,
                    "minimum": 1,
                    "user_ids": [(6, 0, [user.id for user in users])],
                }
            )
        return category, steps

    def _legacy(self, category=None, **vals):
        return (
            self.env["approval.test.synced.document"]
            .with_user(SUPERUSER_ID)
            .create(
                {
                    "name": f"Legacy {self.id()}",
                    "test_category_id": category.id if category else False,
                    **vals,
                }
            )
        )

    def test_a_pending_document_gets_its_request(self):
        document = self._legacy(self._category(), state="submitted")
        self.assertFalse(document.approval_request_id)

        backfilled = document._backfill_approval_requests()

        self.assertEqual(backfilled, document)
        self.assertEqual(document.approval_request_id.state, "pending")
        self.assertIn(
            self.approver_1, document.approval_request_id.approver_ids.user_id
        )
        self.assertEqual(document.state, "submitted")
        self.assertEqual(document.applied_outcomes, "")

    def test_a_document_in_progress_keeps_its_first_decision(self):
        category, steps = self._two_step_category([self.approver_1], [self.approver_2])
        document = self._legacy(
            category, state="first", first_decider_id=self.approver_1.id
        )

        document._backfill_approval_requests()

        request = document.approval_request_id
        self.assertEqual(request.state, "pending")
        row = request.approver_ids.filtered(lambda row: row.user_id == self.approver_1)
        self.assertEqual(row.decided_step_ids, steps[0])
        self.assertEqual(row.decided_by_user_id, self.approver_1)
        self.assertEqual(request._get_open_steps(), steps[1])
        self.assertEqual(document.state, "first")
        self.assertEqual(document.applied_outcomes, "")

    def test_a_first_decider_without_a_row_leaves_that_step_open(self):
        category, steps = self._two_step_category([self.approver_1], [self.approver_2])
        document = self._legacy(
            category, state="first", first_decider_id=self.manager_user.id
        )

        document._backfill_approval_requests()

        request = document.approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertFalse(request.approver_ids.filtered("decision_date"))
        self.assertEqual(request._get_open_steps(), steps[0])
        self.assertTrue(
            any(
                self.manager_user.name in str(message.body)
                for message in document.message_ids
            )
        )

    def test_an_adopter_exclusion_holds_the_backfill_too(self):
        document = self._legacy(
            self._category(), state="submitted", never_requests=True
        )

        backfilled = document._backfill_approval_requests()

        self.assertFalse(backfilled)
        self.assertFalse(document.approval_request_id)

    def test_documents_not_in_flight_or_already_requested_are_left_alone(self):
        category = self._category()
        draft = self._legacy(category, state="draft")
        approved = self._legacy(category, state="approved")
        uncategorised = self._legacy(state="submitted")
        requested = (
            self.env["approval.test.synced.document"]
            .with_user(self.owner_user)
            .sudo()
            .create(
                {
                    "name": f"Requested {self.id()}",
                    "test_category_id": category.id,
                    "state": "submitted",
                }
            )
        )
        request = requested.approval_request_id
        self.assertTrue(request)

        backfilled = (
            draft | approved | uncategorised | requested
        )._backfill_approval_requests()

        self.assertFalse(backfilled)
        self.assertFalse((draft | approved | uncategorised).approval_request_id)
        self.assertEqual(requested.approval_request_id, request)
