from odoo.tests import tagged

from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestHrResponsibleNotify(TestHrCommon):
    """Changing who validates an employee's contracts must reach the employee.

    `hr_responsible_id` is `groups="hr.group_hr_user"`, and mail filters every
    tracking row by field access, so the change never shows up in a chatter the
    employee can read. A direct notification is the only channel they have.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worker = mail_new_test_user(
            cls.env,
            email="worker@example.com",
            login="worker",
            groups="base.group_user",
            name="Worker",
        )
        cls.hired = cls.env["hr.employee"].create(
            {
                "name": "Hired",
                "user_id": cls.worker.id,
                "date_version": "2020-01-01",
                "hr_responsible_id": cls.res_users_hr_officer.id,
            }
        )

    def _notifications_to(self, partner):
        return self.env["mail.message"].search(
            [
                ("partner_ids", "in", partner.ids),
                ("subject", "=", "HR Responsible Update"),
            ]
        )

    def test_the_employee_is_told_when_their_responsible_changes(self):
        self.hired.version_id.write({"hr_responsible_id": self.res_users_hr_manager.id})
        messages = self._notifications_to(self.worker.partner_id)
        self.assertEqual(len(messages), 1)
        self.assertIn("HR Admin", messages.body)

    def test_rewriting_the_same_responsible_says_nothing(self):
        self.hired.version_id.write({"hr_responsible_id": self.res_users_hr_officer.id})
        self.assertFalse(self._notifications_to(self.worker.partner_id))

    def test_a_contract_date_in_the_same_write_does_not_double_the_message(self):
        """Our write() re-enters itself to sync the contract dates."""
        self.hired.version_id.write(
            {
                "hr_responsible_id": self.res_users_hr_manager.id,
                "contract_date_start": "2020-01-01",
            }
        )
        self.assertEqual(len(self._notifications_to(self.worker.partner_id)), 1)

    def test_an_employee_with_no_user_is_reached_at_their_work_contact(self):
        contact = self.env["res.partner"].create({"name": "Contact"})
        employee = self.env["hr.employee"].create(
            {
                "name": "No User",
                "work_contact_id": contact.id,
                "date_version": "2020-01-01",
                "hr_responsible_id": self.res_users_hr_officer.id,
            }
        )
        employee.version_id.write({"hr_responsible_id": self.res_users_hr_manager.id})
        self.assertEqual(len(self._notifications_to(contact)), 1)
