from odoo.exceptions import AccessError

from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import mail_new_test_user


class TestEmployeeProfileAccess(TestHrCommon):
    """Every internal user reads hr.employee; what they read is decided by
    field groups on that one model, not by a second one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain = mail_new_test_user(
            cls.env,
            email="nhr@example.com",
            login="nhr",
            groups="base.group_user,base.group_partner_manager",
            name="No HR Right",
        )
        cls.subject = cls.env["hr.employee"].create(
            {
                "name": "Profile Subject",
                "work_email": "subject@example.com",
                "marital": "single",
            }
        )

    def test_a_plain_user_searches_the_public_fields(self):
        Employee = self.env["hr.employee"].with_user(self.plain)
        self.assertIn(self.subject, Employee.search([("email", "!=", False)]))
        self.assertIn(
            self.subject, Employee.search([("work_email", "=", "subject@example.com")])
        )

    def test_a_plain_user_reads_exactly_the_ungrouped_fields(self):
        Employee = self.env["hr.employee"].with_user(self.plain)
        readable = set(Employee.fields_get())
        self.assertIn("job_title", readable)
        self.assertIn("avatar_128", readable)
        self.assertNotIn("marital", readable)
        self.assertNotIn("ssnid", readable)
        values = Employee.browse(self.subject.id).read(
            ["name", "job_title", "work_email"]
        )[0]
        self.assertEqual(values["work_email"], "subject@example.com")

    def test_a_grouped_field_is_refused_to_a_plain_user(self):
        Employee = self.env["hr.employee"].with_user(self.plain)
        with self.assertRaises(AccessError):
            Employee.browse(self.subject.id).read(["marital"])
        with self.assertRaises(AccessError):
            Employee.search([("marital", "=", "single")])

    def test_access_search_on_users_department(self):
        User = self.env["res.users"].with_user(self.plain)
        User.search([("employee_id.department_id", "=", 1)])
