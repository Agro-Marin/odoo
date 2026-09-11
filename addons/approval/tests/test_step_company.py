from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestStepCompany(ApprovalCommon):
    """A step's approvers are the users who work in the request's company.

    Members, a group and a user field on the document name a step's approvers
    without knowing which company the request is raised in, while an approver row
    belongs to its request's company. Time off raised in a second company must not
    route to the officers of the first.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env["res.company"].create({"name": "Step Company B"})
        cls.group = cls.env.ref("approval.group_approval_approver")
        cls.approver_b = cls._company_b_user("step_company_approver_b", cls.group)
        cls.owner_b = cls._company_b_user("step_company_owner_b")
        cls.partner_model = cls.env["ir.model"]._get("res.partner")

    @classmethod
    def _company_b_user(cls, login, group=None):
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "email": f"{login}@test.com",
                "company_id": cls.company_b.id,
                "company_ids": [(6, 0, cls.company_b.ids)],
                "group_ids": [(4, group.id)] if group else [],
            }
        )

    def _category(self, **step_vals):
        category = self._make_category(
            name=f"Step company {self.id()}", company_id=False
        )
        step = self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Approvers",
                "sequence": 10,
                "minimum": 1,
                **step_vals,
            }
        )
        return category, step

    def _request_in_company_b(self, category, confirm=True, **vals):
        return self._prepare_request(
            category,
            confirm=confirm,
            owner=self.owner_b,
            company_id=self.company_b.id,
            **vals,
        )

    def _assert_rows_in_company_b(self, request):
        self.assertTrue(
            all(
                self.company_b in user.company_ids
                for user in request.approver_ids.user_id
            )
        )

    def test_a_group_step_holds_only_the_users_of_the_request_company(self):
        category, _step = self._category(group_id=self.group.id)

        request_a = self._prepare_request(category)
        request_b = self._request_in_company_b(category)

        self.assertIn(self.approver_1, request_a.approver_ids.user_id)
        self.assertNotIn(self.approver_b, request_a.approver_ids.user_id)
        self.assertIn(self.approver_b, request_b.approver_ids.user_id)
        self.assertNotIn(self.approver_1, request_b.approver_ids.user_id)
        self._assert_rows_in_company_b(request_b)
        members = request_b.category_snapshot["steps"][0]["members"]
        self.assertIn(self.approver_b.id, members)
        self.assertNotIn(self.approver_1.id, members)

    def test_a_document_user_outside_the_request_company_is_not_its_approver(self):
        category, _step = self._category(
            subject_model_id=self.partner_model.id, subject_user_path="user_id"
        )
        partner = self.env["res.partner"].create(
            {"name": "Managed from company A", "user_id": self.approver_1.id}
        )

        request = self._request_in_company_b(
            category, confirm=False, res_model="res.partner", res_id=partner.id
        )

        self.assertFalse(request.approver_ids)
        with self.assertRaisesRegex(UserError, "only 0 user"):
            request.action_confirm()

    def test_a_member_outside_the_request_company_is_not_an_approver(self):
        category, _step = self._category(
            user_ids=[(6, 0, (self.approver_2 | self.approver_b).ids)]
        )

        request = self._request_in_company_b(category)

        self.assertEqual(request.approver_ids.user_id, self.approver_b)

    def test_a_later_step_member_is_one_of_the_request_company(self):
        first_b = self._company_b_user("step_company_first_b")
        category, _step = self._category(user_ids=[(6, 0, first_b.ids)])
        self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Later",
                "sequence": 20,
                "minimum": 1,
                "group_id": self.group.id,
            }
        )
        request = self._request_in_company_b(category)
        first = request.approver_ids.filtered(lambda row: row.user_id == first_b)
        self.assertEqual(first.step_ids.mapped("name"), ["Approvers"])

        self.assertTrue(request._is_later_step_member(first, self.approver_b))
        self.assertFalse(request._is_later_step_member(first, self.approver_1))
