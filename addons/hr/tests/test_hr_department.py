from odoo.addons.hr.tests.test_multi_company import TestMultiCompany


class TestHrDepartment(TestMultiCompany):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.department = cls.env["hr.department"].create(
            {
                "name": "test department",
            }
        )
        cls.employee_a.department_id = cls.department
        cls.employee_other_a.department_id = cls.department
        cls.employee_b.department_id = cls.department

    def test_dapartment_total_employee_count(self):
        employee_count = self.department.with_company(self.company_a).total_employee
        self.assertEqual(employee_count, 2)

        self.department._compute_total_employee()
        employee_count = self.department.total_employee
        self.assertEqual(employee_count, 3)

    def test_department_company_id(self):
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
