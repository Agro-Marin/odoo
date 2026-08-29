from datetime import date

from odoo import fields
from odoo.tests import Form, tagged

from odoo.addons.hr.tests.common import TestHrCommon


@tagged("post_install", "-at_install")
class TestContractTemplateForm(TestHrCommon):
    """`hr.version` has one form view, and it is the Contract Template one.

    Reaching an employee's own version through it -- which is what opening a
    version record directly does -- used to demand a "Template Name" that an
    employee version has no business carrying, and the record could not be
    saved at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sales = cls.env["hr.department"].create({"name": "Sales"})
        cls.hired = cls.env["hr.employee"].create(
            {"name": "Hired", "date_version": "2020-01-01"}
        )

    def test_an_employee_version_can_be_saved_in_the_template_form(self):
        version = self.hired.version_id
        self.assertFalse(version.name, "an employee version carries no template name")

        form = Form(version, view="hr.hr_contract_template_form_view")
        form.department_id = self.sales
        form.save()

        self.assertEqual(version.department_id, self.sales)

    def test_the_form_names_the_employee_whose_version_it_is(self):
        form = Form(self.hired.version_id, view="hr.hr_contract_template_form_view")
        self.assertEqual(form.employee_id, self.hired)
        self.assertEqual(fields.Date.to_date(form.date_version), date(2020, 1, 1))

    def test_a_real_contract_template_still_needs_a_name(self):
        form = Form(self.env["hr.version"], view="hr.hr_contract_template_form_view")
        with self.assertRaises(AssertionError):
            form.save()
