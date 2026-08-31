from lxml import etree

from odoo.tests import tagged

from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestResUsersDepartment(TestHrCommon):
    """Two users called the same are told apart by their job and department."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales = cls.env["hr.department"].create({"name": "Sales"})
        cls.namesake = mail_new_test_user(
            cls.env,
            email="namesake@example.com",
            login="namesake",
            groups="base.group_user",
            name="Juan Perez",
        )
        cls.env["hr.employee"].create(
            {
                "name": "Juan Perez",
                "user_id": cls.namesake.id,
                "department_id": cls.sales.id,
                "job_title": "Sales Representative",
            }
        )

    def test_a_user_carries_their_employees_department(self):
        self.assertEqual(self.namesake.department_id, self.sales)
        self.assertEqual(self.namesake.job_title, "Sales Representative")

    def test_a_user_with_no_employee_has_no_department(self):
        outsider = mail_new_test_user(
            self.env,
            email="outsider@example.com",
            login="outsider",
            groups="base.group_user",
            name="Outsider",
        )
        self.assertFalse(outsider.department_id)

    def test_the_users_list_offers_job_title_and_department(self):
        view = self.env.ref("base.view_users_tree")
        arch = etree.fromstring(self.env["res.users"].get_view(view.id, "list")["arch"])
        self.assertTrue(arch.xpath("//field[@name='job_title']"))
        self.assertTrue(arch.xpath("//field[@name='department_id']"))
