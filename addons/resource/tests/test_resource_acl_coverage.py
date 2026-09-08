from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSystemOnlyModelsStayReadOnlyForPlainUsers(TransactionCase):
    MODELS = ("resource.assignment", "resource.role", "resource.reservation")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = cls.env["res.users"].create(
            {
                "name": "Resource ACL reader",
                "login": "resource_acl_reader",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def test_plain_user_can_read_but_not_write(self):
        for model in self.MODELS:
            Model = self.env[model].with_user(self.reader)
            with self.subTest(model=model):
                Model.check_access("read")
                for operation in ("write", "create", "unlink"):
                    with (
                        self.subTest(operation=operation),
                        self.assertRaises(AccessError),
                    ):
                        Model.check_access(operation)


@tagged("post_install", "-at_install")
class TestMultiCompanyRuleVisibility(TransactionCase):
    def setUp(self):
        super().setUp()
        self.other_company = self.env["res.company"].create({"name": "Other Co ACL"})

    def test_assignment_from_another_company_is_not_visible(self):
        resource = (
            self.env["resource.resource"]
            .with_company(self.other_company)
            .create(
                {
                    "name": "Foreign asset",
                    "resource_type": "material",
                    "tz": "UTC",
                    "company_id": self.other_company.id,
                }
            )
        )
        assignee = (
            self.env["resource.resource"]
            .with_company(self.other_company)
            .create(
                {
                    "name": "Foreign holder",
                    "resource_type": "user",
                    "tz": "UTC",
                    "company_id": self.other_company.id,
                }
            )
        )
        assignment = (
            self.env["resource.assignment"]
            .sudo()
            .create({"resource_id": resource.id, "assignee_id": assignee.id})
        )
        admin = self.env.ref("base.user_admin")
        self.assertNotIn(
            assignment,
            self.env["resource.assignment"].with_user(admin).search([]),
        )

    def test_reservation_from_another_company_is_not_visible(self):
        from datetime import datetime

        resource = (
            self.env["resource.resource"]
            .with_company(self.other_company)
            .create(
                {
                    "name": "Foreign asset",
                    "resource_type": "material",
                    "tz": "UTC",
                    "company_id": self.other_company.id,
                }
            )
        )
        reservation = (
            self.env["resource.reservation"]
            .sudo()
            .create(
                {
                    "name": "Foreign booking",
                    "resource_id": resource.id,
                    "date_start": datetime(2026, 6, 1, 8, 0),
                    "date_end": datetime(2026, 6, 1, 17, 0),
                    "res_model": "res.partner",
                    "res_id": 1,
                    "company_id": self.other_company.id,
                }
            )
        )
        admin = self.env.ref("base.user_admin")
        self.assertNotIn(
            reservation,
            self.env["resource.reservation"].with_user(admin).search([]),
        )
