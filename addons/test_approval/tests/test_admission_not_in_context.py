from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestAdmissionNotInContext(ApprovalCommon):
    """What the engine let through is held on the transaction, not in a context.

    Each test sends, in the context, the key the engine once used to carry that
    fact, and checks that the server does what it would have done without it.
    """

    def setUp(self):
        super().setUp()
        self.category = self._make_category(
            name=f"Admission Cat {self.id()}", approvers=[self.approver_1]
        )

    def _gated(self):
        return self.env["approval.test.gated"].create(
            {
                "name": "Admission Gated",
                "partner_id": self.partner.id,
                "amount_total": 100.0,
                "test_category_id": self.category.id,
            }
        )

    def test_a_context_does_not_choose_the_operation_a_request_is_for(self):
        document = self._gated()
        document.with_context(
            approval_gate_operation="action_bill"
        ).action_create_approval_request()
        request = document.approval_request_id
        self.assertEqual(request.operation, "ship")
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(document.bill_count, 0)

    def test_a_context_does_not_tie_a_request_to_a_binding(self):
        action = self.env["ir.actions.server"].create(
            {
                "name": "Admission probe",
                "model_id": self.env["ir.model"]._get("approval.test.gated").id,
                "state": "code",
                "code": "records.write({'bill_count': 99})",
            }
        )
        binding = self.env["approval.binding"].create(
            {
                "model_id": action.model_id.id,
                "action_id": action.id,
                "mode": "advise",
            }
        )
        document = self._gated()
        document.with_context(
            approval_binding_for=(document._name, document.id, binding.id)
        ).action_create_approval_request()
        self.assertFalse(document.approval_request_id.binding_id)

    def test_a_context_does_not_keep_a_state_change_off_the_request(self):
        category = self._make_category(
            name=f"Admission Sync {self.id()}", approvers=[self.approver_1]
        )
        document = (
            self.env["approval.test.synced.document"]
            .with_user(self.owner_user)
            .sudo()
            .create(
                {
                    "name": "Admission Synced",
                    "test_category_id": category.id,
                    "state": "submitted",
                }
            )
        )
        request = document.approval_request_id
        document.with_user(self.approver_1).sudo().with_context(
            approval_state_sync=(request.id,)
        ).write({"state": "approved"})
        self.assertEqual(request.state, "approved")
        self.assertRecordValues(
            request.approver_ids, [{"decided_by_user_id": self.approver_1.id}]
        )
