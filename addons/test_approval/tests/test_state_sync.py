from odoo import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalStateSync(ApprovalCommon):
    """A document whose own state drives its approval request.

    The document keeps its lifecycle and the request records who decided which step:
    a state change on the document brings the request in line, and a decision taken
    on the request reaches the document through the document's own policy.
    """

    def _category(self, approvers=None, **vals):
        return self._make_category(
            name=f"Sync {self.id()} {vals.pop('suffix', '')}",
            approvers=[self.approver_1] if approvers is None else approvers,
            **vals,
        )

    def _document(self, category=None, user=None, **vals):
        model = self.env["approval.test.synced.document"]
        if user != SUPERUSER_ID:
            model = model.with_user(user or self.owner_user).sudo()
        return model.create(
            {
                "name": f"Doc {self.id()}",
                "test_category_id": (category or self._category()).id,
                **vals,
            }
        )

    def _as(self, document, user):
        return document.with_user(user).sudo()

    def _two_step_category(self, first_users, second_users):
        category = self._category(approvers=[], suffix="steps")
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

    # -- raising the request -----------------------------------------------

    def test_a_document_created_pending_raises_its_request(self):
        document = self._document(state="submitted")

        request = document.sudo().approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, self.owner_user)

    def test_a_document_moved_to_pending_raises_its_request(self):
        document = self._document()
        self.assertFalse(document.approval_request_id)

        self._as(document, self.owner_user).write({"state": "submitted"})

        self.assertEqual(document.approval_request_id.state, "pending")

    def test_the_superuser_raises_no_request(self):
        document = self._document(user=SUPERUSER_ID, state="submitted")
        self.assertFalse(document.approval_request_id)

        document.write({"state": "draft"})
        document.write({"state": "submitted"})

        self.assertFalse(document.approval_request_id)

    # -- the document moves, the request follows -----------------------------

    def test_an_approver_approving_the_document_records_a_decision(self):
        document = self._document(state="submitted")

        self._as(document, self.approver_1).write({"state": "approved"})

        request = document.approval_request_id
        self.assertEqual(request.state, "approved")
        self.assertRecordValues(
            request.approver_ids, [{"decided_by_user_id": self.approver_1.id}]
        )
        self.assertFalse(request.granted_by_user_id)

    def test_a_user_without_a_row_approves_without_a_decision(self):
        document = self._document(state="submitted")

        self._as(document, self.manager_user).write({"state": "approved"})

        request = document.approval_request_id
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.granted_by_user_id, self.manager_user)
        self.assertFalse(request.approver_ids.filtered("decision_date"))

    def test_refusing_an_approved_document_revokes_its_request(self):
        document = self._document(state="submitted")
        self._as(document, self.approver_1).write({"state": "approved"})

        self._as(document, self.manager_user).write({"state": "refused"})

        request = document.approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertEqual(request.revoked_state, "refused")
        self.assertEqual(request.approver_ids.state, "approved")

    def test_an_approver_refusing_a_pending_document_decides(self):
        document = self._document(state="submitted")

        self._as(document, self.approver_1).write({"state": "refused"})

        request = document.approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertRecordValues(
            request.approver_ids,
            [{"state": "refused", "decided_by_user_id": self.approver_1.id}],
        )

    def test_cancelling_a_pending_document_cancels_its_request(self):
        document = self._document(state="submitted")

        self._as(document, self.owner_user).write({"state": "cancelled"})

        self.assertEqual(document.approval_request_id.state, "cancelled")

    def test_a_document_back_to_draft_resets_and_resubmitting_restarts(self):
        document = self._document(state="submitted")
        self._as(document, self.approver_1).write({"state": "approved"})

        self._as(document, self.owner_user).write({"state": "draft"})
        self.assertEqual(document.approval_request_id.state, "new")

        self._as(document, self.owner_user).write({"state": "submitted"})
        request = document.approval_request_id
        self.assertEqual(request.state, "pending")
        self.assertFalse(request.approver_ids.filtered("decision_date"))

    def test_moving_the_document_to_progress_decides_only_the_open_step(self):
        category, steps = self._two_step_category(
            [self.approver_1], [self.approver_1, self.approver_2]
        )
        document = self._document(category=category, state="submitted")

        self._as(document, self.approver_1).write({"state": "first"})

        request = document.approval_request_id
        self.assertEqual(request.state, "pending")
        row = request.approver_ids.filtered(lambda a: a.user_id == self.approver_1)
        self.assertEqual(row.decided_step_ids, steps[0])

    def test_a_sync_driven_reset_does_not_notify_the_document(self):
        document = self._document(state="submitted")
        self._as(document, self.approver_1).write({"state": "approved"})

        self._as(document, self.owner_user).write({"state": "draft"})

        self.assertFalse(
            any(
                "prior approval is no longer valid" in body
                for body in document.sudo().message_ids.mapped("body")
            )
        )

    # -- a decision on the request moves the document ------------------------

    def test_a_decision_on_the_request_moves_the_document_once(self):
        document = self._document(state="submitted")

        document.approval_request_id.with_user(self.approver_1).action_approve()

        self.assertEqual(document.state, "approved")
        self.assertEqual(document.applied_outcomes, "approved;")

    def test_a_refusal_on_the_request_refuses_the_document(self):
        document = self._document(state="submitted")

        document.approval_request_id.with_user(self.approver_1).with_context(
            skip_wizard=True
        ).action_refuse()

        self.assertEqual(document.state, "refused")

    def test_a_first_step_on_the_request_moves_the_document_to_progress(self):
        category, _steps = self._two_step_category([self.approver_1], [self.approver_2])
        document = self._document(category=category, state="submitted")

        document.approval_request_id.with_user(self.approver_1).action_approve()
        self.assertEqual(document.state, "first")

        self._as(document, self.approver_2).write({"state": "approved"})
        self.assertEqual(document.approval_request_id.state, "approved")

    def test_a_first_step_decided_on_the_request_does_not_decide_the_next(self):
        category, steps = self._two_step_category(
            [self.approver_1], [self.approver_1, self.approver_2]
        )
        document = self._document(category=category, state="submitted")

        document.approval_request_id.with_user(self.approver_1).action_approve(
            steps=steps[0]
        )

        self.assertEqual(document.state, "first")
        request = document.approval_request_id
        self.assertEqual(request.state, "pending")
        row = request.approver_ids.filtered(lambda a: a.user_id == self.approver_1)
        self.assertEqual(row.decided_step_ids, steps[0])

    def test_the_document_policy_vetoes_a_request_decision(self):
        document = self._document(state="submitted", policy_refusal="Not yours")

        # assertRaises rolls the failed decision back to a savepoint, as the transaction
        # would; assertRaisesRegex does not, and would leave the approval written.
        with self.assertRaises(UserError) as caught:
            document.approval_request_id.with_user(self.approver_1).action_approve()
        self.assertIn("Not yours", str(caught.exception))

        self.assertEqual(document.state, "submitted")
        self.assertEqual(document.approval_request_id.state, "pending")

    def test_an_engine_cancellation_reaches_the_document_past_its_policy(self):
        document = self._document(state="submitted", policy_refusal="Not yours")

        document.approval_request_id._force_terminal("cancelled", "Expired")

        self.assertEqual(document.state, "cancelled")

    # -- a refusal note travels with the document's refusal ------------------

    def test_a_refusal_note_reaches_a_decided_refusal(self):
        document = self._document(state="submitted")

        self._as(document, self.approver_1).with_context(
            approval_refusal_note="Not in budget"
        ).write({"state": "refused"})

        request = document.approval_request_id
        self.assertEqual(request.refusal_note, "Not in budget")
        self.assertEqual(request.approver_ids.decided_by_user_id, self.approver_1)

    def test_a_refusal_note_reaches_a_revoked_approval(self):
        document = self._document(state="submitted")
        self._as(document, self.approver_1).write({"state": "approved"})

        self._as(document, self.manager_user).with_context(
            approval_refusal_note="Duplicate claim"
        ).write({"state": "refused"})

        request = document.approval_request_id
        self.assertEqual(request.revoked_state, "refused")
        self.assertEqual(request.refusal_note, "Duplicate claim")

    def test_a_refusal_note_reaches_a_forced_refusal(self):
        document = self._document(state="submitted")

        self._as(document, self.manager_user).with_context(
            approval_refusal_note="Out of policy"
        ).write({"state": "refused"})

        request = document.approval_request_id
        self.assertEqual(request.state, "refused")
        self.assertFalse(request.approver_ids.filtered("decision_date"))
        self.assertEqual(request.refusal_note, "Out of policy")

    def test_a_cancellation_carries_no_refusal_note(self):
        document = self._document(state="submitted")

        self._as(document, self.owner_user).with_context(
            approval_refusal_note="Changed my mind"
        ).write({"state": "cancelled"})

        request = document.approval_request_id
        self.assertEqual(request.state, "cancelled")
        self.assertFalse(request.refusal_note)

    # -- the request is not moved from elsewhere ------------------------------

    def test_the_request_is_not_moved_from_the_approvals_app(self):
        document = self._document(state="submitted")
        request = document.approval_request_id
        with self.assertRaises(UserError):
            request.with_user(self.owner_user).action_cancel()

        self._as(document, self.approver_1).write({"state": "approved"})

        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_withdraw()
        with self.assertRaises(UserError):
            request.with_user(self.manager_user).action_reset_to_draft()
        self.assertEqual(request.state, "approved")

    def test_a_refused_request_is_not_reset_from_the_approvals_app(self):
        document = self._document(state="submitted")
        self._as(document, self.approver_1).write({"state": "refused"})
        request = document.approval_request_id
        self.assertEqual(request.state, "refused")

        with self.assertRaises(UserError):
            request.with_user(self.manager_user).action_reset_to_draft()

        self.assertEqual(request.state, "refused")

    def test_no_change_is_requested_from_the_approvals_app(self):
        document = self._document(state="submitted")

        with self.assertRaises(UserError):
            document.approval_request_id.with_user(
                self.approver_1
            ).action_request_change()

    def test_deleting_a_pending_document_cancels_its_request(self):
        document = self._document(state="submitted")
        request = document.approval_request_id

        self._as(document, self.owner_user).unlink()

        self.assertEqual(request.state, "cancelled")
