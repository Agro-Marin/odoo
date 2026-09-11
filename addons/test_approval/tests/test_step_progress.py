from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestStepProgress(ApprovalCommon):
    """A document hears a step being met while its request is still pending.

    A double-validation leave moves to its intermediate state when the manager step
    is met; nothing told a document about a step until the request ended.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver_3 = cls.env["res.users"].create(
            {
                "name": "Progress Three",
                "login": "progress_u3",
                "email": "progress_u3@test.com",
                "group_ids": [(4, cls.env.ref("approval.group_approval_approver").id)],
            },
        )

    def _document(self, first_users, first_minimum=1):
        category = self._make_category(name=f"Progress {self.id()}")
        Step = self.env["approval.category.step"]
        Step.create(
            {
                "category_id": category.id,
                "name": "First",
                "sequence": 10,
                "minimum": first_minimum,
                "member_ids": [Command.create({"user_id": u.id}) for u in first_users],
            },
        )
        Step.create(
            {
                "category_id": category.id,
                "name": "Second",
                "sequence": 20,
                "member_ids": [Command.create({"user_id": self.approver_2.id})],
            },
        )
        doc = self.env["approval.test.document"].create(
            {
                "name": f"Progress doc {self.id()}",
                "partner_id": self.partner.id,
                "test_category_id": category.id,
            },
        )
        doc.action_create_approval_request()
        return doc

    def test_a_decision_that_meets_a_step_tells_the_document(self):
        doc = self._document(self.approver_1)

        doc.approval_request_id.with_user(self.approver_1).action_approve()

        self.assertEqual(doc.approval_request_id.state, "pending")
        self.assertEqual(doc.progress_call_count, 1)
        self.assertEqual(doc.hook_call_count, 0)

    def test_the_final_decision_reports_the_outcome_not_progress(self):
        doc = self._document(self.approver_1)
        doc.approval_request_id.with_user(self.approver_1).action_approve()

        doc.approval_request_id.with_user(self.approver_2).action_approve()

        self.assertEqual(doc.approval_request_id.state, "approved")
        self.assertEqual(doc.progress_call_count, 1)
        self.assertEqual(doc.last_approval_state, "approved")

    def test_a_decision_that_meets_no_step_reports_nothing(self):
        doc = self._document(self.approver_1 | self.approver_3, first_minimum=2)

        doc.approval_request_id.with_user(self.approver_1).action_approve()

        self.assertEqual(doc.approval_request_id.state, "pending")
        self.assertEqual(doc.progress_call_count, 0)
