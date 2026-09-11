from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestStepSourceApprovers(ApprovalCommon):
    """A step may name its approvers through a user field on the source document.

    "The employee's time off manager" is neither a listed member nor a group: it is a
    user read off the record being approved, and a different one on every record.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.approver_3 = cls.env["res.users"].create(
            {
                "name": "Source Three",
                "login": "source_u3",
                "email": "source_u3@test.com",
                "group_ids": [(4, cls.env.ref("approval.group_approval_approver").id)],
            },
        )

    def _source_step(self, category, path="user_id", **vals):
        return self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": "Account manager",
                "sequence": 10,
                "subject_model_id": self.partner_model.id,
                "subject_user_path": path,
                **vals,
            },
        )

    def _partner_request(self, category, partner, confirm=True):
        return self._prepare_request(
            category,
            confirm=confirm,
            res_model="res.partner",
            res_id=partner.id,
        )

    def _partner(self, user):
        return self.env["res.partner"].create(
            {
                "name": f"Managed by {user.name if user else 'nobody'}",
                "user_id": user.id,
            }
        )

    def test_the_step_asks_the_user_the_document_names(self):
        category = self._make_category(name=f"Source {self.id()}")
        step = self._source_step(category)

        request = self._partner_request(category, self._partner(self.approver_3))

        self.assertEqual(request.approver_ids.user_id, self.approver_3)
        self.assertEqual(request.approver_ids.step_ids, step)

    def test_each_document_names_its_own_approver(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category)

        first = self._partner_request(category, self._partner(self.approver_1))
        second = self._partner_request(category, self._partner(self.approver_2))

        self.assertEqual(first.approver_ids.user_id, self.approver_1)
        self.assertEqual(second.approver_ids.user_id, self.approver_2)

    def test_only_the_named_user_decides(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category)
        request = self._partner_request(category, self._partner(self.approver_3))

        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_approve()
        request.with_user(self.approver_3).action_approve()

        self.assertEqual(request.state, "approved")

    def test_listed_members_and_the_named_user_share_the_pool(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category, minimum=2, user_ids=[(6, 0, self.approver_1.ids)])
        request = self._partner_request(category, self._partner(self.approver_3))

        self.assertEqual(
            request.approver_ids.user_id, self.approver_1 | self.approver_3
        )
        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "pending")
        request.with_user(self.approver_3).action_approve()
        self.assertEqual(request.state, "approved")

    def test_confirm_refuses_a_document_that_names_nobody(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category)
        request = self._partner_request(
            category, self._partner(self.env["res.users"]), confirm=False
        )

        with self.assertRaises(UserError):
            request.action_confirm()

    def test_the_named_user_is_asked_with_an_activity(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category)
        request = self._partner_request(category, self._partner(self.approver_3))
        activity_type = self.env.ref("approval.mail_activity_data_approval")

        self.assertEqual(
            request.activity_ids.filtered(
                lambda activity: activity.activity_type_id == activity_type
            ).user_id,
            self.approver_3,
        )

    def test_the_snapshot_records_where_the_approvers_come_from(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category)
        request = self._partner_request(category, self._partner(self.approver_3))

        (step,) = request.category_snapshot["steps"]
        self.assertEqual(step["source_user_path"], "user_id")
        self.assertEqual(step["members"], [self.approver_3.id])

    # -- configuration that could never work ------------------------------

    def test_a_source_step_needs_no_members_or_group(self):
        category = self._make_category(name=f"Source {self.id()}")
        self.assertTrue(self._source_step(category))

    def test_a_path_needs_the_model_it_reads(self):
        category = self._make_category(name=f"Source {self.id()}")
        with self.assertRaises(ValidationError):
            self._source_step(category, subject_model_id=False)

    def test_a_path_naming_a_missing_field_is_refused(self):
        category = self._make_category(name=f"Source {self.id()}")
        with self.assertRaises(ValidationError):
            self._source_step(category, path="no_such_field")

    def test_a_path_must_end_in_users(self):
        category = self._make_category(name=f"Source {self.id()}")
        with self.assertRaises(ValidationError):
            self._source_step(category, path="parent_id")
        with self.assertRaises(ValidationError):
            self._source_step(category, path="name")

    def test_a_path_may_cross_relations(self):
        category = self._make_category(name=f"Source {self.id()}")
        self._source_step(category, path="parent_id.user_id")
        company = self._partner(self.approver_2)
        contact = self.env["res.partner"].create(
            {"name": "Contact of a managed company", "parent_id": company.id}
        )

        request = self._partner_request(category, contact)

        self.assertEqual(request.approver_ids.user_id, self.approver_2)
