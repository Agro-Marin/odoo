from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartyConvergence(TransactionCase):
    """Party convergence reports before it writes.

    An employee can carry two partner rows for one person -- the work contact,
    and the partner behind their login user. Converging them is a
    deduplication, so the report has to separate what a migration could merge
    from what needs a human, and it must never write.
    """

    @classmethod
    def _diverge(cls, employee, contact):
        """Legacy data: two partner rows for one person. The constraint forbids
        writing it, so it is planted the way an old database holds it."""
        cls.env.flush_all()
        cls.env.cr.execute(
            "UPDATE hr_employee SET partner_id = %s WHERE id = %s",
            (contact.id, employee.id),
        )
        employee.invalidate_recordset(["partner_id"])

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Emp = cls.env["hr.employee"]
        Partner = cls.env["res.partner"]
        User = cls.env["res.users"]

        user = User.create({"name": "Converged", "login": "conv_a"})
        cls.converged = cls.Emp.create({"name": "Converged", "user_id": user.id})

        user_b = User.create({"name": "Mergeable", "login": "conv_b"})
        cls.mergeable = cls.Emp.create({"name": "Mergeable", "user_id": user_b.id})
        cls._diverge(cls.mergeable, Partner.create({"name": "Mergeable Work"}))

        user_c = User.create(
            {"name": "Conflicted", "login": "conv_c", "email": "home@example.com"}
        )
        cls.conflicted = cls.Emp.create({"name": "Conflicted", "user_id": user_c.id})
        cls._diverge(
            cls.conflicted,
            Partner.create({"name": "Conflicted Work", "email": "work@example.com"}),
        )

        cls.userless = cls.Emp.create({"name": "No User"})
        cls.env.flush_all()

    def test_an_employee_whose_contact_is_already_the_user_partner_is_converged(self):
        report = self.Emp.report_party_convergence()
        ids = [
            e["employee_id"] for e in report["safe_to_merge"] + report["conflicting"]
        ]
        self.assertNotIn(self.converged.id, ids)

    def test_two_rows_with_no_clashing_value_are_reported_as_mergeable(self):
        report = self.Emp.report_party_convergence()
        ids = [e["employee_id"] for e in report["safe_to_merge"]]
        self.assertIn(self.mergeable.id, ids)

    def test_a_field_held_differently_on_both_rows_needs_a_human(self):
        report = self.Emp.report_party_convergence()
        entry = next(
            e for e in report["conflicting"] if e["employee_id"] == self.conflicted.id
        )
        self.assertEqual(
            entry["clashes"]["email"], ("work@example.com", "home@example.com")
        )

    def test_an_employee_with_no_login_user_is_not_a_convergence_case(self):
        report = self.Emp.report_party_convergence()
        ids = [
            e["employee_id"] for e in report["safe_to_merge"] + report["conflicting"]
        ]
        self.assertNotIn(self.userless.id, ids)
        self.assertGreaterEqual(report["no_user"], 1)

    def test_the_report_writes_nothing(self):
        """It is a dry run: reading it must not change the data it describes."""
        before = {
            e.id: (e.partner_id.id, e.user_id.partner_id.id)
            for e in self.Emp.search([])
        }
        self.Emp.report_party_convergence()
        self.Emp.print_party_convergence()
        self.env.flush_all()
        after = {
            e.id: (e.partner_id.id, e.user_id.partner_id.id)
            for e in self.Emp.search([])
        }
        self.assertEqual(before, after)

    def test_converging_merges_the_unambiguous_pair(self):
        work_contact = self.mergeable.partner_id
        user_partner = self.mergeable.user_id.partner_id
        self.assertNotEqual(work_contact, user_partner)

        result = self.Emp.converge_party_rows()

        self.assertIn(self.mergeable.id, result["merged"])
        self.mergeable.invalidate_recordset()
        self.assertEqual(
            self.mergeable.partner_id,
            user_partner,
            "the user's partner is the row that survives",
        )
        self.assertFalse(work_contact.exists(), "the duplicate row is gone")

    def test_converging_refuses_the_conflicting_pair(self):
        work_contact = self.conflicted.partner_id
        user_partner = self.conflicted.user_id.partner_id

        result = self.Emp.converge_party_rows()

        self.assertNotIn(self.conflicted.id, result["merged"])
        self.assertIn(self.conflicted.id, result["left_for_a_human"])
        self.conflicted.invalidate_recordset()
        self.assertEqual(self.conflicted.partner_id, work_contact)
        self.assertTrue(work_contact.exists())
        self.assertNotEqual(work_contact, user_partner)

    def test_converging_twice_is_a_no_op_the_second_time(self):
        first = self.Emp.converge_party_rows()
        second = self.Emp.converge_party_rows()
        self.assertIn(self.mergeable.id, first["merged"])
        self.assertNotIn(self.mergeable.id, second["merged"])


@tagged("post_install", "-at_install")
class TestPrivateAddressFollowsTheContact(TransactionCase):
    def _link_user_to_an_employee_with_a_home(self):
        employee = self.env["hr.employee"].create(
            {"name": "Homed", "private_street": "Home Street 1"}
        )
        old_contact = employee.partner_id
        user = self.env["res.users"].create({"name": "Homed", "login": "homed"})
        employee.write({"user_id": user.id})
        return employee, old_contact, user

    def test_linking_a_user_moves_the_home_under_the_user_partner(self):
        employee, old_contact, user = self._link_user_to_an_employee_with_a_home()
        self.assertEqual(employee.partner_id, user.partner_id)
        self.assertEqual(employee.private_address_id.parent_id, user.partner_id)
        self.assertEqual(employee.private_street, "Home Street 1")
        self.assertFalse(old_contact.child_ids)

    def test_the_user_partner_then_serves_the_home_as_the_employee_address(self):
        _employee, _old_contact, user = self._link_user_to_an_employee_with_a_home()
        addresses = user.partner_id._get_all_addr()
        self.assertEqual(addresses[0]["contact_type"], "employee")
        self.assertEqual(addresses[0]["street"], "Home Street 1")

    def test_the_report_names_a_home_left_under_another_contact(self):
        employee = self.env["hr.employee"].create(
            {"name": "Stranded", "private_street": "Elsewhere 2"}
        )
        other = self.env["res.partner"].create({"name": "Stranded Other"})
        employee.private_address_id.sudo().parent_id = other
        report = self.env["hr.employee"].report_party_convergence()
        self.assertIn(employee.id, report["misparented_home"])
        self.env["hr.employee"].converge_party_rows()
        self.assertEqual(
            employee.private_address_id.parent_id, employee.partner_id
        )


@tagged("post_install", "-at_install")
class TestWorkContactFollowsTheUser(TransactionCase):
    def test_an_employee_with_a_user_cannot_point_at_another_contact(self):
        user = self.env["res.users"].create({"name": "Bound", "login": "bound"})
        employee = self.env["hr.employee"].create({"name": "Bound", "user_id": user.id})
        other = self.env["res.partner"].create({"name": "Someone Else"})
        with self.assertRaises(ValidationError):
            employee.partner_id = other

    def test_linking_a_user_moves_the_work_contact_to_the_user_partner(self):
        employee = self.env["hr.employee"].create({"name": "Later User"})
        own_contact = employee.partner_id
        user = self.env["res.users"].create({"name": "Later User", "login": "later"})
        employee.user_id = user
        self.assertEqual(employee.partner_id, user.partner_id)
        self.assertNotEqual(employee.partner_id, own_contact)
