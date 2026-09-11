from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.hr_expense.tests.common import TestExpenseCommon
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("-at_install", "post_install")
class TestExpenseEmployeeOnCreate(TestExpenseCommon):
    def _expense_vals(self, **vals):
        return {
            "name": "Taxi",
            "product_id": self.product_c.id,
            "total_amount_currency": 10.0,
            **vals,
        }

    def test_an_expense_for_another_company_is_filed_under_that_companys_employee(self):
        company_2 = self.company_data_2["company"]
        manager = self.expense_user_manager
        Employee = self.env["hr.employee"].sudo()
        Employee.create({"name": "Manager here", "user_id": manager.id})
        manager_there = Employee.create(
            {"name": "Manager there", "user_id": manager.id, "company_id": company_2.id}
        )
        expenses = (
            self.env["hr.expense"]
            .with_user(manager)
            .with_context(allowed_company_ids=[self.env.company.id, company_2.id])
        )

        expense = expenses.create(self._expense_vals(company_id=company_2.id))

        self.assertEqual(expense.employee_id, manager_there)

    def test_an_explicit_employee_is_kept(self):
        expense = (
            self.env["hr.expense"]
            .with_user(self.expense_user_manager)
            .create(self._expense_vals(employee_id=self.expense_employee.id))
        )

        self.assertEqual(expense.employee_id, self.expense_employee)

    def test_a_user_without_an_employee_cannot_start_an_expense(self):
        user = mail_new_test_user(
            self.env, login="no_employee_expense", groups="base.group_user"
        )

        with self.assertRaisesRegex(ValidationError, "no related employee"):
            self.env["hr.expense"].with_user(user).create(self._expense_vals())
