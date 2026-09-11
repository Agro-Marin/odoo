from odoo.tests import TransactionCase


class TestDepartmentCompanyOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env["res.company"].create({"name": "Other company"})
        cls.env.user.company_ids |= cls.other_company

    def test_a_sub_department_belongs_to_its_parent_s_company(self):
        parent = self.env["hr.department"].create(
            {"name": "Parent", "company_id": self.other_company.id}
        )

        child = self.env["hr.department"].create(
            {"name": "Child", "parent_id": parent.id}
        )

        self.assertEqual(child.company_id, self.other_company)

    def test_a_department_without_a_parent_belongs_to_the_current_company(self):
        department = self.env["hr.department"].create({"name": "Top"})

        self.assertEqual(department.company_id, self.env.company)

    def test_an_explicit_company_wins_without_a_parent(self):
        department = self.env["hr.department"].create(
            {"name": "Elsewhere", "company_id": self.other_company.id}
        )

        self.assertEqual(department.company_id, self.other_company)
