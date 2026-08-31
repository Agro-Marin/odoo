from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import mail_new_test_user


class TestHrEmployee(TestHrCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.res_users_without_hr_right = mail_new_test_user(
            cls.env,
            email="nhr@example.com",
            login="nhr",
            groups="base.group_user,base.group_partner_manager",
            name="No HR Right",
        )

    def test_access_related_field_to_hr_employee(self):
        # Check if a related field related to hr_employee is accessible.
        self.env["hr.employee.public"].with_user(
            self.res_users_without_hr_right
        ).search([("email", "!=", False)])

    def test_access_search_on_users_department(self):
        User = self.env["res.users"].with_user(self.res_users_without_hr_right)
        User.search([("employee_id.department_id", "=", 1)])


class TestHrEmployeePublicCacheCopy(TestHrCommon):
    """`_copy_cache_from` hand-copies public values past the ACL.

    It must never hand one employee's value to another: the whole point of the
    hack is that a user who cannot read `hr.employee` still sees the public
    subset, and a value landing on the wrong record is a leak dressed as a
    cache entry.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ana, cls.beto = cls.env["hr.employee"].create(
            [{"name": "Ana"}, {"name": "Beto"}]
        )

    def test_a_missing_public_value_does_not_shift_onto_another_employee(self):
        public = self.env["hr.employee.public"].browse((self.ana.id, self.beto.id))
        public.fetch(["name"])
        public_name = public._fields["name"]
        # `fetch` fills both, so the gap is opened by hand. What is under test is
        # not how an entry goes missing but what the copy does when the sequence
        # it reads is shorter than the recordset it writes into.
        self.env.cache.remove(public[0], public_name)

        employees = self.env["hr.employee"].browse((self.ana.id, self.beto.id))
        employee_name = employees._fields["name"]
        self.env.cache.invalidate([(employee_name, employees.ids)])
        employees._copy_cache_from(public, ["name"])

        self.assertEqual(
            self.env.cache.get(employees[1], employee_name, None),
            "Beto",
            "Beto's public name has to land on Beto",
        )
        self.assertNotEqual(
            self.env.cache.get(employees[0], employee_name, None),
            "Beto",
            "Ana has no public value to copy and must not inherit Beto's",
        )
