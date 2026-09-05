from odoo.tests.common import tagged

from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install", "mail_flow")
class TestHrEmployeeMail(TestHrCommon, MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_template_employee = (
            cls.env["mail.template"]
            .with_user(cls.user_admin)
            .create(
                {
                    "auto_delete": True,
                    "body_html": '<p>Hello <t t-out="object.name"/></p>',
                    "email_from": '{{ object.user_id.email_formatted or user.email_formatted or "" }}',
                    "model_id": cls.env["ir.model"]._get_id("hr.employee"),
                    "name": "Test Hr Template",
                    "subject": "Test {{ object.name }}",
                    "use_default_to": True,
                }
            )
        )
        cls.test_employee = cls.env["hr.employee"].create(
            [
                {
                    "company_id": cls.company_admin.id,
                    "country_id": cls.env.ref("base.be").id,
                    "name": "QuickEmployee",
                    "work_email": "quick.employee@test.example.com",
                    "work_phone": "+32455001122",
                },
            ]
        )

    def test_employees_alias_compares_whole_addresses(self):
        """`work_email ilike <address>` read `%` and `_` as wildcards, and both
        are legal in a local part: `%@test.example.com` matched every employee."""
        alias = self.env["mail.alias"].create(
            {
                "alias_contact": "employees",
                "alias_domain_id": self.mail_alias_domain.id,
                "alias_model_id": self.env["ir.model"]._get_id("hr.employee"),
                "alias_name": "employees.only",
            }
        )
        self.employee.user_id = self.res_users_hr_officer
        Employee = self.env["hr.employee"]

        def verdict(email_from):
            return Employee._alias_get_error(None, {"email_from": email_from}, alias)

        for refused in (
            "%@test.example.com",
            "_uick.employee@test.example.com",
            "quick.employee@test.example.co_",
            "employee@test.example.com",
            "",
            False,
            "not an address",
        ):
            with self.subTest(email_from=refused):
                error = verdict(refused)
                self.assertTrue(error)
                self.assertEqual(error.code, "error_hr_employee_restricted")
        for accepted in (
            "quick.employee@test.example.com",
            '"Quick" <QUICK.Employee@Test.Example.COM>',
            self.res_users_hr_officer.email,
        ):
            with self.subTest(email_from=accepted):
                self.assertFalse(verdict(accepted))

    def test_assert_initial_values(self):
        self.assertTrue(self.test_employee.partner_id)
        self.assertFalse(self.test_employee.message_partner_ids)
        # The party's channels are the employee's work channels now.
        self.assertEqual(self.test_employee.email, self.test_employee.work_email)
        self.assertEqual(self.test_employee.phone, self.test_employee.work_phone)
        self.assertFalse(self.test_employee.user_id)

    def test_employee_get_default_recipients(self):
        employee = self.test_employee.with_user(self.res_users_hr_officer)
        defaults = employee._message_get_default_recipients()
        self.assertDictEqual(
            defaults[employee.id],
            {
                "email_cc": "",
                "email_to": "",
                "partner_ids": self.test_employee.partner_id.ids,
            },
        )

    def test_employee_get_suggested_recipients(self):
        employee = self.test_employee.with_user(self.res_users_hr_officer)
        suggested = employee._message_get_suggested_recipients()
        self.assertListEqual(
            suggested,
            [
                {
                    "create_values": {},
                    "email": self.test_employee.partner_id.email_normalized,
                    "name": self.test_employee.partner_id.name,
                    "partner_id": self.test_employee.partner_id.id,
                },
            ],
        )

    def test_employee_template(self):
        employee, template = (
            self.test_employee.with_user(self.res_users_hr_officer),
            self.test_template_employee.with_user(self.res_users_hr_officer),
        )
        message = employee.message_post_with_source(
            template,
            message_type="comment",
            subtype_id=self.env.ref("mail.mt_comment").id,
        )
        self.assertEqual(
            message.notified_partner_ids,
            self.test_employee.partner_id,
            "Matches suggested recipients",
        )
