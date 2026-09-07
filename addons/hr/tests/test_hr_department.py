from odoo.exceptions import ValidationError

from odoo.addons.hr.tests.test_multi_company import TestMultiCompany


class TestHrDepartment(TestMultiCompany):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.department = cls.env["hr.department"].create(
            {
                "name": "test department",
                "company_id": cls.company_a.id,
            }
        )
        cls.department_b = cls.env["hr.department"].create(
            {
                "name": "test department of company B",
                "company_id": cls.company_b.id,
            }
        )
        cls.employee_a.department_id = cls.department
        cls.employee_other_a.department_id = cls.department
        cls.employee_b.department_id = cls.department_b

    def test_dapartment_total_employee_count(self):
        self.assertEqual(self.department.with_company(self.company_a).total_employee, 2)
        self.department.invalidate_recordset(["total_employee"])
        self.assertEqual(self.department.total_employee, 2)
        self.assertEqual(self.department_b.total_employee, 1)

    def test_an_employee_cannot_join_another_companys_department(self):
        with self.assertRaises(ValidationError):
            self.employee_b.department_id = self.department

    def test_a_department_cannot_move_away_from_its_members(self):
        with self.assertRaises(ValidationError):
            self.department.company_id = self.company_b

    def test_a_department_with_no_company_holds_anyone(self):
        shared = self.env["hr.department"].create(
            {"name": "shared department", "company_id": False}
        )
        self.employee_a.department_id = shared
        self.employee_b.department_id = shared
        self.assertEqual(shared.total_employee, 2)

    def test_department_company_id(self):
        self.department = self.env["hr.department"].create(
            {"name": "company-hopping department"}
        )
        self.parent_department = self.env["hr.department"].create(
            {
                "name": "parent of the test department",
                "company_id": self.company_a.id,
            }
        )
        self.department.company_id = self.company_b.id
        self.assertTrue(self.department.company_id == self.company_b)
        self.department.parent_id = self.parent_department.id
        self.assertTrue(self.department.company_id == self.company_a)
        self.parent_department.company_id = self.company_b
        self.assertTrue(self.department.company_id == self.company_b)
        self.parent_department.company_id = False

        self.assertTrue(self.department.company_id == self.company_b)

        self.parents_parent_department = self.env["hr.department"].create(
            {
                "name": "grandparent of test department",
                "company_id": False,
            }
        )
        self.parent_department.parent_id = self.parents_parent_department.id

        self.assertFalse(self.parent_department.company_id)
        self.assertTrue(self.department.company_id == self.company_b)

        self.parents_parent_department.company_id = self.company_a.id
        self.assertTrue(self.parent_department.company_id == self.company_a)
        self.assertTrue(self.department.company_id == self.company_a)

    def test_complete_name_follows_root_rename_read_singly(self):
        """A recursive stored compute must reach every descendant with the
        ancestor's new value, whatever order the records are read in.

        `_recompute_singly` used to widen the batch from the record being read,
        so a deep chain renamed at the root and then read one record at a time,
        middle first, stored the pre-rename root name on the deepest levels.
        """
        Department = self.env["hr.department"]
        chain = [Department.create({"name": "R0"})]
        for level in range(1, 6):
            chain.append(
                Department.create({"name": f"L{level}", "parent_id": chain[-1].id})
            )
        self.env.flush_all()
        self.env.invalidate_all()

        chain[0].name = "ROOT"
        for index in (3, 1, 4, 2, 5, 0):
            Department.browse(chain[index].id).complete_name
        self.env.flush_all()
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT complete_name FROM hr_department WHERE id = ANY(%s) ORDER BY id",
            ([department.id for department in chain],),
        )
        self.assertEqual(
            [row[0] for row in self.env.cr.fetchall()],
            [
                "ROOT",
                "ROOT / L1",
                "ROOT / L1 / L2",
                "ROOT / L1 / L2 / L3",
                "ROOT / L1 / L2 / L3 / L4",
                "ROOT / L1 / L2 / L3 / L4 / L5",
            ],
        )

    def test_moving_to_another_company_requires_settling_the_department_first(self):
        """The rule bites on the company change too, not only on the assignment.

        `hr.employee.write` applies employee fields before version fields, so a
        single write carrying both the new company and a cleared department is
        validated with the new company and the old department still in place.
        Settling the department first is therefore the supported order, and it
        is also what a real transfer does.
        """
        employee = self.employee_other_a
        self.assertEqual(employee.department_id, self.department)
        with self.assertRaises(ValidationError):
            employee.company_id = self.company_b
        employee.department_id = False
        employee.company_id = self.company_b
        self.assertEqual(employee.company_id, self.company_b)
