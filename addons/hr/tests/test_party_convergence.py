from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartyConvergence(TransactionCase):
    """ADR-0086 step 5 reports before it writes.

    An employee can carry two partner rows for one person -- the work contact,
    and the partner behind their login user. Converging them is a
    deduplication, so the report has to separate what a migration could merge
    from what needs a human, and it must never write.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Emp = cls.env["hr.employee"]
        Partner = cls.env["res.partner"]
        User = cls.env["res.users"]

        user = User.create({"name": "Converged", "login": "conv_a"})
        cls.converged = cls.Emp.create({"name": "Converged", "user_id": user.id})
        cls.converged.work_contact_id = user.partner_id

        user_b = User.create({"name": "Mergeable", "login": "conv_b"})
        cls.mergeable = cls.Emp.create({"name": "Mergeable", "user_id": user_b.id})
        cls.mergeable.work_contact_id = Partner.create({"name": "Mergeable Work"})

        user_c = User.create(
            {"name": "Conflicted", "login": "conv_c", "email": "home@example.com"}
        )
        cls.conflicted = cls.Emp.create({"name": "Conflicted", "user_id": user_c.id})
        cls.conflicted.work_contact_id = Partner.create(
            {"name": "Conflicted Work", "email": "work@example.com"}
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
            e.id: (e.work_contact_id.id, e.user_id.partner_id.id)
            for e in self.Emp.search([])
        }
        self.Emp.report_party_convergence()
        self.Emp.print_party_convergence()
        self.env.flush_all()
        after = {
            e.id: (e.work_contact_id.id, e.user_id.partner_id.id)
            for e in self.Emp.search([])
        }
        self.assertEqual(before, after)

    def test_converging_merges_the_unambiguous_pair(self):
        work_contact = self.mergeable.work_contact_id
        user_partner = self.mergeable.user_id.partner_id
        self.assertNotEqual(work_contact, user_partner)

        result = self.Emp.converge_party_rows()

        self.assertIn(self.mergeable.id, result["merged"])
        self.mergeable.invalidate_recordset()
        self.assertEqual(
            self.mergeable.work_contact_id,
            user_partner,
            "the user's partner is the row that survives",
        )
        self.assertFalse(work_contact.exists(), "the duplicate row is gone")

    def test_converging_refuses_the_conflicting_pair(self):
        work_contact = self.conflicted.work_contact_id
        user_partner = self.conflicted.user_id.partner_id

        result = self.Emp.converge_party_rows()

        self.assertNotIn(self.conflicted.id, result["merged"])
        self.assertIn(self.conflicted.id, result["left_for_a_human"])
        self.conflicted.invalidate_recordset()
        self.assertEqual(self.conflicted.work_contact_id, work_contact)
        self.assertTrue(work_contact.exists())
        self.assertNotEqual(work_contact, user_partner)

    def test_converging_twice_is_a_no_op_the_second_time(self):
        first = self.Emp.converge_party_rows()
        second = self.Emp.converge_party_rows()
        self.assertIn(self.mergeable.id, first["merged"])
        self.assertNotIn(self.mergeable.id, second["merged"])
