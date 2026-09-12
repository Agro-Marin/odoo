from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestCoverageIntegrity(ApprovalCommon):
    """What a document says about its approval can come only from a decision on a
    request about that document. Every gate downstream -- posting an invoice,
    confirming an order, applying an adjustment -- reads the document."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls._make_category(
            "Coverage", approvers=[(cls.approver_1, True, 10)]
        )
        cls.partner = cls.env["res.partner"].create({"name": "Coverage Partner"})

    def _document(self, name="Doc"):
        return self.env["approval.test.document"].create(
            {
                "name": name,
                "partner_id": self.partner.id,
                "test_category_id": self.category.id,
            }
        )

    def _approved_document(self, name="Approved"):
        document = self._document(name)
        document.action_create_approval_request()
        document.approval_request_id.with_user(self.approver_1).action_approve()
        self.assertEqual(document.approval_state, "approved")
        return document

    def test_the_approval_state_cannot_be_written(self):
        document = self._document()
        document.action_create_approval_request()
        for caller in (document, document.sudo()):
            with self.assertRaises(ValidationError):
                caller.write({"approval_state": "approved"})
        document.invalidate_recordset()
        self.assertEqual(document.approval_state, "pending")

    def test_the_approval_dates_cannot_be_written(self):
        document = self._document()
        for field in ("date_approval_granted", "date_approval_requested"):
            with self.assertRaises(ValidationError):
                document.sudo().write({field: "2026-01-01 00:00:00"})

    def test_a_document_cannot_be_created_already_approved(self):
        with self.assertRaises(ValidationError):
            self.env["approval.test.document"].create(
                {
                    "name": "Born approved",
                    "partner_id": self.partner.id,
                    "approval_state": "approved",
                }
            )

    def test_another_documents_approved_request_cannot_be_borrowed(self):
        approved = self._approved_document()
        borrower = self._document("Borrower")
        with self.assertRaises(ValidationError):
            borrower.sudo().write(
                {"approval_request_id": approved.approval_request_id.id}
            )
        self.assertFalse(borrower.approval_request_id)
        self.assertNotEqual(borrower.approval_state, "approved")

    def test_a_decided_request_without_a_subject_cannot_be_adopted(self):
        request = self._prepare_request(self.category)
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "approved")
        document = self._document()
        with self.assertRaises(ValidationError):
            document.write({"approval_request_id": request.id})

    def test_an_undecided_request_without_a_subject_is_bound_on_adoption(self):
        request = self._prepare_request(self.category, confirm=False)
        document = self._document()
        document.write({"approval_request_id": request.id})
        self.assertEqual(
            (request.res_model, request.res_id), (document._name, document.id)
        )
        with self.assertRaises(ValidationError):
            self._document("Second").write({"approval_request_id": request.id})

    def test_one_request_cannot_be_linked_to_several_documents(self):
        request = self._prepare_request(self.category, confirm=False)
        documents = self._document("A") | self._document("B")
        with self.assertRaises(ValidationError):
            documents.write({"approval_request_id": request.id})

    def test_the_engine_still_links_its_own_request(self):
        document = self._document()
        document.action_create_approval_request()
        self.assertEqual(document.approval_request_id.res_id, document.id)
        self.assertEqual(document.approval_state, "pending")

    def test_a_document_may_still_let_go_of_its_request(self):
        document = self._approved_document()
        document.write({"approval_request_id": False})
        self.assertFalse(document.approval_state)
