from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestBindingOnAnAdopter(ApprovalCommon):
    """A Request-mode binding on a document that implements mixin.approval.

    The document asks through its own `action_create_approval_request`, so its
    category matching and hooks still run; the binding only records which
    operation to run once the document is approved.
    """

    def setUp(self):
        super().setUp()
        self.category = self._make_category(
            name=f"Binding Adopter Cat {self.id()}",
            approvers=[self.approver_1],
        )
        self.doc = self.env["approval.test.document"].create(
            {
                "name": "Gated document",
                "partner_id": self.partner.id,
                "test_category_id": self.category.id,
            },
        )
        self.binding = self.env["approval.binding"].create(
            {
                "model_id": self.env["ir.model"]._get("approval.test.document").id,
                "method": "action_record_operation",
                "mode": "request",
                "category_id": self.category.id,
                "sudo_policy": "enforce",
            },
        )

    def tearDown(self):
        self.env["approval.binding"]._unregister_hook()
        super().tearDown()

    def test_the_call_asks_through_the_document_instead_of_running(self):
        self.doc.action_record_operation()
        self.assertEqual(self.doc.operation_count, 0)
        request = self.doc.approval_request_id
        self.assertTrue(request, "the document's own request was not raised")
        self.assertEqual(request.binding_id, self.binding)
        self.assertEqual(request.state, "pending")

    def test_calling_again_while_pending_reuses_the_documents_request(self):
        self.doc.action_record_operation()
        first = self.doc.approval_request_id
        self.doc.action_record_operation()
        self.assertEqual(self.doc.approval_request_id, first)
        self.assertEqual(self.doc.operation_count, 0)

    def test_approval_tells_the_document_then_runs_the_operation_once(self):
        self.doc.action_record_operation()
        request = self.doc.approval_request_id
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(self.doc.last_approval_state, "approved")
        self.assertEqual(self.doc.operation_count, 1)
        self.assertTrue(request.date_binding_replayed)
        self.assertFalse(request.binding_replay_error)

    def test_an_approved_document_runs_the_operation_directly(self):
        self.doc.action_record_operation()
        self.doc.approval_request_id.with_user(self.approver_1).action_approve()
        self.doc.action_record_operation()
        self.assertEqual(self.doc.operation_count, 2)
