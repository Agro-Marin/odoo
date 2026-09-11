from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestStepDocumentPolicy(ApprovalCommon):
    """A document narrows its steps to the users its own policy lets decide it.

    A step names its approvers by members, a group and a user field, none of which
    knows the document's policy: an expense is never approved by its own employee,
    and a team approver outside the employee's hierarchy is refused. Such a user
    holding a row is asked, listed and offered a decision the document then vetoes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env.ref("approval.group_approval_approver")
        cls.group_user = new_test_user(
            cls.env,
            login="step_policy_group_user",
            groups="base.group_user,approval.group_approval_approver",
        )

    def _category(self, **step_vals):
        category = self._make_category(
            name=f"Step policy {self.id()}", approvers=[], company_id=False
        )
        self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Approvers",
                "sequence": 10,
                "minimum": 1,
                **step_vals,
            }
        )
        return category

    def _document(self, category, blocked=(), **vals):
        return (
            self.env["approval.test.synced.document"]
            .with_user(self.owner_user)
            .sudo()
            .create(
                {
                    "name": f"Doc {self.id()}",
                    "test_category_id": category.id,
                    "blocked_user_ids": [(6, 0, [user.id for user in blocked])],
                    "state": "submitted",
                    **vals,
                }
            )
        )

    def test_a_group_step_holds_no_row_for_a_user_the_document_refuses(self):
        category = self._category(group_id=self.group.id)

        document = self._document(category, blocked=self.approver_2)

        request = document.approval_request_id
        self.assertIn(self.approver_1, request.approver_ids.user_id)
        self.assertIn(self.group_user, request.approver_ids.user_id)
        self.assertNotIn(self.approver_2, request.approver_ids.user_id)
        members = request.category_snapshot["steps"][0]["members"]
        self.assertIn(self.approver_1.id, members)
        self.assertNotIn(self.approver_2.id, members)

    def test_a_member_the_document_refuses_is_not_an_approver(self):
        category = self._category(
            user_ids=[(6, 0, (self.approver_1 | self.approver_2).ids)]
        )

        document = self._document(category, blocked=self.approver_2)

        self.assertEqual(
            document.approval_request_id.approver_ids.user_id, self.approver_1
        )

    def test_a_step_the_document_refuses_entirely_cannot_be_confirmed(self):
        category = self._category(user_ids=[(6, 0, self.approver_1.ids)])

        with self.assertRaises(UserError) as caught:
            self._document(category, blocked=self.approver_1)

        self.assertIn("only 0 user", str(caught.exception))

    def test_a_user_the_document_refuses_is_no_later_step_member(self):
        first_user = new_test_user(
            self.env, login="step_policy_first_user", groups="base.group_user"
        )
        category = self._category(user_ids=[(6, 0, first_user.ids)])
        self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Later",
                "sequence": 20,
                "minimum": 1,
                "group_id": self.group.id,
            }
        )

        document = self._document(category, blocked=self.approver_2)

        request = document.approval_request_id
        first = request.approver_ids.filtered(lambda row: row.user_id == first_user)
        self.assertEqual(first.step_ids.mapped("name"), ["Approvers"])
        self.assertTrue(request._is_later_step_member(first, self.group_user))
        self.assertFalse(request._is_later_step_member(first, self.approver_2))

    def test_a_document_that_narrows_nothing_keeps_every_step_user(self):
        category = self._category(group_id=self.group.id)
        partner = self.env["res.partner"].create({"name": f"Plain {self.id()}"})
        document = self.env["approval.test.document"].create(
            {
                "name": f"Plain {self.id()}",
                "partner_id": partner.id,
                "test_category_id": category.id,
            }
        )

        document.action_create_approval_request()

        users = document.approval_request_id.approver_ids.user_id
        self.assertIn(self.approver_1, users)
        self.assertIn(self.approver_2, users)
        self.assertIn(self.group_user, users)

    def test_a_record_outside_the_mixin_keeps_its_pool(self):
        partner_model = self.env["ir.model"]._get("res.partner")
        category = self._category(
            subject_model_id=partner_model.id, subject_user_path="user_id"
        )
        partner = self.env["res.partner"].create(
            {"name": f"Partner {self.id()}", "user_id": self.approver_1.id}
        )

        request = self._prepare_request(
            category, res_model="res.partner", res_id=partner.id
        )

        self.assertEqual(request.approver_ids.user_id, self.approver_1)

    def test_rerouting_drops_the_row_of_a_user_the_document_since_refused(self):
        category = self._category(
            user_ids=[(6, 0, (self.approver_1 | self.approver_2).ids)]
        )
        document = self._document(category)
        request = document.approval_request_id
        self.assertEqual(
            request.approver_ids.user_id, self.approver_1 | self.approver_2
        )

        document.write(
            {"state": "draft", "blocked_user_ids": [(4, self.approver_2.id)]}
        )
        document.state = "submitted"

        self.assertEqual(request.state, "pending")
        self.assertEqual(request.approver_ids.user_id, self.approver_1)

    def test_a_legacy_row_of_a_user_the_document_since_refused_is_removed(self):
        category = self._category(
            user_ids=[(6, 0, (self.approver_1 | self.approver_2).ids)]
        )
        document = self._document(category)
        request = document.approval_request_id
        legacy = request.approver_ids.filtered(
            lambda row: row.user_id == self.approver_2
        )
        legacy.sudo().source_synced = False

        document.write(
            {"state": "draft", "blocked_user_ids": [(4, self.approver_2.id)]}
        )
        document.state = "submitted"

        self.assertFalse(legacy.exists())
        self.assertEqual(request.approver_ids.user_id, self.approver_1)
