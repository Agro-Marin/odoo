from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestEmployeeChangeRequest(TransactionCase):
    """A person asks; an HR user decides. Nobody edits their own HR data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.person = new_test_user(
            cls.env, login="asker", groups="base.group_user", name="Asker"
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Asker",
                "user_id": cls.person.id,
                "private_street": "Old Street 1",
                "emergency_contact": "Old Contact",
            }
        )
        cls.officer = new_test_user(
            cls.env, login="officer", groups="hr.group_hr_user", name="Officer"
        )
        cls.other_employee = cls.env["hr.employee"].create({"name": "Somebody Else"})
        cls.Request = cls.env["hr.employee.change.request"]

    def _raise_request(self, **values):
        return self.Request.with_user(self.person).create(
            {"employee_id": self.employee.id, **values}
        )

    def test_a_person_can_ask_to_change_their_own_information(self):
        request = self._raise_request(private_street="New Street 2")
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.requested_by_uid, self.person)
        self.assertEqual(self.employee.private_street, "Old Street 1")

    def test_a_person_cannot_ask_about_somebody_else(self):
        with self.assertRaises(AccessError):
            self.Request.with_user(self.person).create(
                {"employee_id": self.other_employee.id, "private_street": "Nosy"}
            )

    def test_a_person_cannot_approve_their_own_request(self):
        request = self._raise_request(private_street="New Street 2")
        with self.assertRaises(AccessError):
            request.with_user(self.person).action_approve()
        self.assertEqual(self.employee.private_street, "Old Street 1")

    def test_an_hr_user_approving_applies_the_change(self):
        request = self._raise_request(
            private_street="New Street 2", emergency_contact="New Contact"
        )
        request.with_user(self.officer).action_approve()
        self.employee.invalidate_recordset(["private_street", "emergency_contact"])
        self.assertEqual(self.employee.private_street, "New Street 2")
        self.assertEqual(self.employee.emergency_contact, "New Contact")
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.reviewed_by_uid, self.officer)
        self.assertTrue(request.reviewed_on)

    def test_refusing_leaves_the_employee_untouched(self):
        request = self._raise_request(private_street="Never Applied")
        request.with_user(self.officer).action_refuse()
        self.employee.invalidate_recordset(["private_street"])
        self.assertEqual(self.employee.private_street, "Old Street 1")
        self.assertEqual(request.state, "refused")

    def test_a_decided_request_cannot_be_decided_again(self):
        request = self._raise_request(private_street="Once")
        request.with_user(self.officer).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.officer).action_approve()

    def test_only_one_request_may_be_pending_at_a_time(self):
        self._raise_request(private_street="First")
        with self.assertRaises(ValidationError):
            self._raise_request(private_street="Second")

    def test_only_the_fields_that_changed_are_written(self):
        request = self._raise_request(
            private_street="Old Street 1", emergency_contact="Changed"
        )
        self.assertEqual(request._proposed_values(), {"emergency_contact": "Changed"})

    def test_a_person_sees_only_their_own_requests(self):
        mine = self._raise_request(private_street="Mine")
        theirs = self.Request.create(
            {"employee_id": self.other_employee.id, "private_street": "Theirs"}
        )
        visible = self.Request.with_user(self.person).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)
        self.assertIn(theirs, self.Request.with_user(self.officer).search([]))
