from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmployeeCopy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "Scope A"})
        cls.company_b = cls.env["res.company"].create({"name": "Scope B"})

        cls.calendar_a = cls.env["resource.calendar"].create(
            {"name": "Calendar A", "company_id": cls.company_a.id}
        )
        cls.calendar_b = cls.env["resource.calendar"].create(
            {"name": "Calendar B", "company_id": cls.company_b.id}
        )
        cls.company_a.resource_calendar_id = cls.calendar_a
        cls.company_b.resource_calendar_id = cls.calendar_b

        cls.department_a = cls.env["hr.department"].create(
            {"name": "Department A", "company_id": cls.company_a.id}
        )
        cls.department_b = cls.env["hr.department"].create(
            {"name": "Department B", "company_id": cls.company_b.id}
        )
        cls.job_a = cls.env["hr.job"].create(
            {"name": "Job A", "company_id": cls.company_a.id}
        )

        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Scoped Employee",
                "company_id": cls.company_a.id,
                "department_id": cls.department_a.id,
                "job_id": cls.job_a.id,
            }
        )
        cls.env.flush_all()

    def test_copy_into_another_company_drops_the_source_company_values(self):
        copy = self.employee.copy(
            {"company_id": self.company_b.id, "date_version": "2001-01-01"}
        )
        self.env.flush_all()

        self.assertEqual(copy.company_id, self.company_b)
        self.assertFalse(copy.department_id)
        self.assertFalse(copy.job_id)
        self.assertEqual(copy.resource_calendar_id, self.calendar_b)

    def test_copy_into_another_company_keeps_an_explicit_default(self):
        copy = self.employee.copy(
            {
                "company_id": self.company_b.id,
                "department_id": self.department_b.id,
                "date_version": "2001-01-01",
            }
        )
        self.env.flush_all()

        self.assertEqual(copy.department_id, self.department_b)

    def test_copy_within_the_company_keeps_everything(self):
        copy = self.employee.copy({"date_version": "2001-01-01"})
        self.env.flush_all()

        self.assertEqual(copy.company_id, self.company_a)
        self.assertEqual(copy.department_id, self.department_a)
        self.assertEqual(copy.job_id, self.job_a)
        self.assertEqual(copy.resource_calendar_id, self.calendar_a)

    def test_copy_into_another_company_from_a_third_active_company(self):
        # The shape pos_hr's fixture has: the active company is neither the
        # source's nor the copy's, so nothing downstream can fall back to it.
        copy = self.employee.with_company(self.env.ref("base.main_company")).copy(
            {"company_id": self.company_b.id, "date_version": "2001-01-01"}
        )
        self.env.flush_all()

        self.assertEqual(copy.company_id, self.company_b)
        self.assertFalse(copy.department_id)

    def test_version_copy_alone_drops_the_source_company_values(self):
        vals = self.employee.version_id.copy_data(
            {"company_id": self.company_b.id, "date_version": "2001-01-01"}
        )[0]

        self.assertNotIn("department_id", vals)
        self.assertNotIn("job_id", vals)

    def test_a_department_from_another_company_is_still_refused(self):
        # The convergence guard must not swallow a settled violation.
        with self.assertRaises(ValidationError):
            self.employee.department_id = self.department_b
            self.env.flush_all()

    def test_copy_carries_the_name(self):
        # `name` is a STORED related on hr.employee, so it is the employee's own
        # column; a related field defaults to copy=False, which left the copied
        # partner nameless and failing `res_partner_check_name`.
        copy = self.employee.copy({"date_version": "2001-01-01"})
        self.env.flush_all()

        self.assertEqual(copy.name, self.employee.name)
        self.assertEqual(copy.partner_id.name, self.employee.name)

    def test_moving_the_employee_to_another_company_is_still_refused(self):
        # The other half of the convergence guard, and the half a first draft
        # got wrong: it may skip a `company_id` pending recompute, never one the
        # caller is writing. Refusing the transfer until the department is
        # settled is what these constraints are for.
        with self.assertRaises(ValidationError):
            self.employee.company_id = self.company_b
            self.env.flush_all()

    def test_a_historical_version_does_not_block_a_transfer(self):
        # The in-force guard must do real work in the other direction. Every
        # version's `company_id` follows the employee, so a transfer moves the
        # OLD versions too -- but `department_id` is a plain stored field and
        # stays behind, so without the guard an old version's department would
        # refuse a transfer the current version has already settled.
        old = self.employee.version_id.copy({"date_version": "1999-01-01"})
        old.department_id = self.department_a
        self.env.flush_all()
        self.assertNotEqual(old, self.employee.version_id)

        self.employee.department_id = False
        self.employee.job_id = False
        self.employee.company_id = self.company_b
        self.env.flush_all()

        self.assertEqual(self.employee.company_id, self.company_b)
        self.assertEqual(old.department_id, self.department_a)
