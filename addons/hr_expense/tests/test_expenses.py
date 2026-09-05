from datetime import date

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.hr_expense.tests.common import TestExpenseCommon


@tagged("-at_install", "post_install")
class TestExpenses(TestExpenseCommon):
    def test_expense_main_flow(self):
        self.expense_employee.partner_id.property_supplier_payment_term_id = (
            self.env.ref("account.account_payment_term_30days")
        )
        expenses_by_employee = self.create_expenses(
            [
                {
                    "name": "Employee PA 2*800 + 15%",
                    "employee_id": self.expense_employee.id,
                    "account_id": self.expense_account.id,
                    "product_id": self.product_a.id,
                    "quantity": 2,
                    "payment_mode": "own_account",
                    "company_id": self.company_data["company"].id,
                    "date": "2021-10-14",
                    "analytic_distribution": {self.analytic_account_1.id: 100},
                },
                {
                    "name": "Employee PB 160 + 2*15%",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_b.id,
                    "payment_mode": "own_account",
                    "company_id": self.company_data["company"].id,
                    "date": "2021-10-13",
                    "analytic_distribution": {self.analytic_account_2.id: 100},
                },
            ]
        )
        expenses_by_company = self.create_expenses(
            [
                {
                    "name": "Company PC 1000 + 15%",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount_currency": 1000.00,
                    "date": "2021-10-12",
                    "payment_mode": "company_account",
                    "company_id": self.company_data["company"].id,
                    "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                },
                {
                    "name": "Company PB 160 + 2*15%",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_b.id,
                    "payment_mode": "company_account",
                    "company_id": self.company_data["company"].id,
                    "date": "2021-10-11",
                },
            ]
        )
        all_expenses = expenses_by_employee | expenses_by_company

        self.assertRecordValues(
            all_expenses,
            [
                {
                    "name": "Employee PA 2*800 + 15%",
                    "total_amount_currency": 1600.00,
                    "untaxed_amount_currency": 1391.30,
                    "price_unit": 800.00,
                    "tax_amount_currency": 208.70,
                    "state": "draft",
                },
                {
                    "name": "Employee PB 160 + 2*15%",
                    "total_amount_currency": 160.00,
                    "untaxed_amount_currency": 123.08,
                    "price_unit": 160.00,
                    "tax_amount_currency": 36.92,
                    "state": "draft",
                },
                {
                    "name": "Company PC 1000 + 15%",
                    "total_amount_currency": 1000.00,
                    "untaxed_amount_currency": 869.57,
                    "price_unit": 1000.00,
                    "tax_amount_currency": 130.43,
                    "state": "draft",
                },
                {
                    "name": "Company PB 160 + 2*15%",
                    "total_amount_currency": 160.00,
                    "untaxed_amount_currency": 123.08,
                    "price_unit": 160.00,
                    "tax_amount_currency": 36.92,
                    "state": "draft",
                },
            ],
        )

        all_expenses.action_submit()
        self.assertRecordValues(
            all_expenses,
            [
                {"state": "submitted"},
                {"state": "submitted"},
                {"state": "submitted"},
                {"state": "submitted"},
            ],
        )

        all_expenses.action_approve()
        self.assertRecordValues(
            all_expenses,
            [
                {"state": "approved", "account_move_id": False},
                {"state": "approved", "account_move_id": False},
                {"state": "approved", "account_move_id": False},
                {"state": "approved", "account_move_id": False},
            ],
        )
        expenses_by_company.action_post()
        self.post_expenses_with_wizard(expenses_by_employee[0], date=date(2021, 10, 10))
        self.post_expenses_with_wizard(expenses_by_employee[1], date=date(2021, 10, 31))
        self.assertRecordValues(
            all_expenses,
            [
                {"payment_mode": "own_account", "state": "posted"},
                {"payment_mode": "own_account", "state": "posted"},
                {"payment_mode": "company_account", "state": "paid"},
                {"payment_mode": "company_account", "state": "paid"},
            ],
        )

        employee_partner_id = self.expense_user_employee.partner_id.id
        self.assertRecordValues(
            expenses_by_employee.account_move_id,
            [
                {
                    "amount_total": 1600.00,
                    "ref": "Employee PA 2*800 + 15%",
                    "state": "posted",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 10),
                    "partner_id": employee_partner_id,
                },
                {
                    "amount_total": 160.00,
                    "ref": "Employee PB 160 + 2*15%",
                    "state": "posted",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 31),
                    "partner_id": employee_partner_id,
                },
            ],
        )

        self.assertRecordValues(
            expenses_by_company.account_move_id,
            [
                {
                    "amount_total": 1000.00,
                    "ref": "Company PC 1000 + 15%",
                    "state": "posted",
                    "date": date(2021, 10, 12),
                    "invoice_date": False,
                    "partner_id": False,
                },
                {
                    "amount_total": 160.00,
                    "ref": "Company PB 160 + 2*15%",
                    "state": "posted",
                    "date": date(2021, 10, 11),
                    "invoice_date": False,
                    "partner_id": False,
                },
            ],
        )

        tax_account_id = self.company_data["default_account_tax_purchase"].id
        default_account_payable_id = self.company_data["default_account_payable"].id
        product_b_account_id = self.product_b.property_account_expense_id.id
        product_c_account_id = self.product_c.property_account_expense_id.id
        company_payment_account_id = self.outbound_payment_channel.payment_account_id.id
        self.assertRecordValues(
            all_expenses.account_move_id.line_ids.sorted(
                lambda line: (line.move_id, line)
            ),
            [
                {
                    "balance": 1391.30,
                    "account_id": self.expense_account.id,
                    "name": "expense_employee: Employee PA 2*800 + 15%",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 10),
                },
                {
                    "balance": 208.70,
                    "account_id": tax_account_id,
                    "name": "15%",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 10),
                },
                {
                    "balance": -1600.00,
                    "account_id": default_account_payable_id,
                    "name": False,
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 10),
                },
                {
                    "balance": 123.08,
                    "account_id": product_b_account_id,
                    "name": "expense_employee: Employee PB 160 + 2*15%",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 31),
                },
                {
                    "balance": 18.46,
                    "account_id": tax_account_id,
                    "name": "15%",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 31),
                },
                {
                    "balance": 18.46,
                    "account_id": tax_account_id,
                    "name": "15% (copy)",
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 31),
                },
                {
                    "balance": -160.00,
                    "account_id": default_account_payable_id,
                    "name": False,
                    "date": date(2021, 10, 31),
                    "invoice_date": date(2021, 10, 31),
                },
                {
                    "balance": 869.57,
                    "account_id": product_c_account_id,
                    "name": "expense_employee: Company PC 1000 + 15%",
                    "date": date(2021, 10, 12),
                    "invoice_date": False,
                },
                {
                    "balance": 130.43,
                    "account_id": tax_account_id,
                    "name": "15%",
                    "date": date(2021, 10, 12),
                    "invoice_date": False,
                },
                {
                    "balance": -1000.00,
                    "account_id": company_payment_account_id,
                    "name": "expense_employee: Company PC 1000 + 15%",
                    "date": date(2021, 10, 12),
                    "invoice_date": False,
                },
                {
                    "balance": 123.08,
                    "account_id": product_b_account_id,
                    "name": "expense_employee: Company PB 160 + 2*15%",
                    "date": date(2021, 10, 11),
                    "invoice_date": False,
                },
                {
                    "balance": 18.46,
                    "account_id": tax_account_id,
                    "name": "15%",
                    "date": date(2021, 10, 11),
                    "invoice_date": False,
                },
                {
                    "balance": 18.46,
                    "account_id": tax_account_id,
                    "name": "15% (copy)",
                    "date": date(2021, 10, 11),
                    "invoice_date": False,
                },
                {
                    "balance": -160.00,
                    "account_id": company_payment_account_id,
                    "name": "expense_employee: Company PB 160 + 2*15%",
                    "date": date(2021, 10, 11),
                    "invoice_date": False,
                },
            ],
        )

        self.assertRecordValues(
            expenses_by_employee.account_move_id.line_ids,
            [
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
                {"partner_id": employee_partner_id},
            ],
        )

        in_payment_state = (
            expenses_by_employee.account_move_id._get_invoice_in_payment_state()
        )
        first_expense_by_employee = expenses_by_employee[0]
        first_expense_by_company = expenses_by_company[0]

        payment_1 = self.get_new_payment(first_expense_by_employee, 1000.0)
        liquidity_lines1 = payment_1._seek_for_lines()[0]
        self.assertEqual(first_expense_by_employee.state, in_payment_state)

        payment_2 = self.get_new_payment(first_expense_by_employee, 600.0)
        liquidity_lines2 = payment_2._seek_for_lines()[0]
        self.assertEqual(first_expense_by_employee.state, in_payment_state)

        statement_line = self.env["account.bank.statement.line"].create(
            {
                "journal_id": self.company_data["default_journal_bank"].id,
                "payment_ref": "pay_ref",
                "amount": -1600.0,
                "partner_id": self.expense_employee.partner_id.id,
            }
        )

        _trash, st_suspense_lines, _trash = statement_line.with_context(
            skip_account_move_synchronization=True
        )._seek_for_lines()
        st_suspense_lines.account_id = liquidity_lines1.account_id
        (st_suspense_lines + liquidity_lines1 + liquidity_lines2).reconcile()
        self.assertEqual(first_expense_by_employee.state, "paid")

        with self.assertRaises(UserError):
            (self.analytic_account_1 | self.analytic_account_2).unlink()

        (payment_1 | payment_2).action_draft()
        (payment_1 | payment_2).move_id.line_ids.remove_move_reconcile()
        self.assertEqual(first_expense_by_employee.state, "posted")
        expenses_by_employee.account_move_id.action_draft()
        expenses_by_employee.account_move_id.unlink()
        self.assertFalse(expenses_by_employee.account_move_id)

        first_expense_by_company.account_move_id.origin_payment_id.unlink()
        self.assertFalse(first_expense_by_company.account_move_id)

        self.assertRecordValues(
            first_expense_by_employee | first_expense_by_company,
            [
                {"payment_mode": "own_account", "state": "approved"},
                {"payment_mode": "company_account", "state": "approved"},
            ],
        )

        first_expense_by_employee.action_reset()
        self.assertEqual(first_expense_by_employee.state, "draft")
        first_expense_by_employee.unlink()
        self.analytic_account_1.unlink()

    def test_expense_split_flow(self):
        self.env.user.group_ids += self.env.ref("analytic.group_analytic_accounting")

        expense = self.create_expenses(
            {
                "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                "analytic_distribution": {self.analytic_account_1.id: 100},
            }
        )

        wizard = self.env["hr.expense.split.wizard"].browse(
            expense.action_split_wizard()["res_id"]
        )

        self.assertRecordValues(
            wizard.expense_split_line_ids,
            [
                {
                    "name": expense.name,
                    "wizard_id": wizard.id,
                    "expense_id": expense.id,
                    "product_id": expense.product_id.id,
                    "tax_ids": expense.tax_ids.ids,
                    "total_amount_currency": expense.total_amount_currency / 2,
                    "tax_amount_currency": 65.22,
                    "employee_id": expense.employee_id.id,
                    "company_id": expense.company_id.id,
                    "currency_id": expense.currency_id.id,
                    "analytic_distribution": expense.analytic_distribution,
                }
            ]
            * 2,
        )
        self.assertRecordValues(
            wizard,
            [
                {
                    "split_possible": True,
                    "total_amount_currency": expense.total_amount_currency,
                }
            ],
        )

        with Form(wizard) as form:
            form.expense_split_line_ids.remove(index=0)
            self.assertEqual(form.split_possible, False)

            with form.expense_split_line_ids.edit(0) as line:
                line.total_amount_currency = 200.00
                line.tax_ids.clear()
                line.analytic_distribution = {}
                self.assertEqual(line.total_amount_currency, 200.00)
                self.assertEqual(line.tax_amount_currency, 0.00)
            self.assertEqual(form.split_possible, False)

            with form.expense_split_line_ids.new() as line:
                line.total_amount_currency = 300.00
                self.assertEqual(line.total_amount_currency, 300.00)
                self.assertEqual(line.tax_amount_currency, 39.13)
                self.assertDictEqual(
                    line.analytic_distribution, expense.analytic_distribution
                )
            self.assertEqual(form.split_possible, False)
            self.assertEqual(form.total_amount_currency, 500.00)

            with form.expense_split_line_ids.new() as line:
                line.total_amount_currency = 500.00
                line.tax_ids.add(self.tax_purchase_b)
                line.analytic_distribution = {self.analytic_account_2.id: 100}
                self.assertEqual(line.total_amount_currency, 500.00)
                self.assertEqual(line.tax_amount_currency, 115.38)

        self.assertRecordValues(
            wizard,
            [
                {
                    "total_amount_currency": 1000.00,
                    "total_amount_currency_original": 1000.00,
                    "tax_amount_currency": 154.51,
                    "split_possible": True,
                }
            ],
        )

        wizard.action_split_expense()
        expenses_after_split = self.env["hr.expense"].search(
            [("name", "=", expense.name)]
        )
        self.assertRecordValues(
            expenses_after_split.sorted("total_amount_currency"),
            [
                {
                    "name": expense.name,
                    "employee_id": expense.employee_id.id,
                    "product_id": expense.product_id.id,
                    "total_amount_currency": 200.00,
                    "tax_ids": [],
                    "tax_amount_currency": 0.00,
                    "untaxed_amount_currency": 200.00,
                    "analytic_distribution": False,
                    "split_expense_origin_id": expense.id,
                },
                {
                    "name": expense.name,
                    "employee_id": expense.employee_id.id,
                    "product_id": expense.product_id.id,
                    "total_amount_currency": 300.00,
                    "tax_ids": [self.tax_purchase_a.id],
                    "tax_amount_currency": 39.13,
                    "untaxed_amount_currency": 260.87,
                    "analytic_distribution": {str(self.analytic_account_1.id): 100},
                    "split_expense_origin_id": expense.id,
                },
                {
                    "name": expense.name,
                    "employee_id": expense.employee_id.id,
                    "product_id": expense.product_id.id,
                    "total_amount_currency": 500.00,
                    "tax_ids": [self.tax_purchase_a.id, self.tax_purchase_b.id],
                    "tax_amount_currency": 115.38,
                    "untaxed_amount_currency": 384.62,
                    "analytic_distribution": {str(self.analytic_account_2.id): 100},
                    "split_expense_origin_id": expense.id,
                },
            ],
        )

    def test_expense_multi_currencies(self):
        foreign_currency_1 = self.other_currency
        foreign_currency_2 = self.setup_other_currency(
            "GBP", rounding=0.01, rates=([("2016-01-01", 1 / 1.52)])
        )
        foreign_sale_journal = self.company_data["default_journal_sale"].copy()
        foreign_sale_journal.currency_id = foreign_currency_2.id

        foreign_expense_1, foreign_expense_2, foreign_expense_3 = self.create_expenses(
            [
                {
                    "name": "foreign_expense_1",
                    "payment_mode": "company_account",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount_currency": 1000.00,
                    "date": self.frozen_today,
                    "company_id": self.company_data["company"].id,
                    "currency_id": foreign_currency_1.id,
                    "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                },
                {
                    "name": "foreign_expense_2",
                    "payment_mode": "company_account",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount_currency": 1000.00,
                    "date": self.frozen_today,
                    "company_id": self.company_data["company"].id,
                    "currency_id": foreign_currency_2.id,
                    "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                },
                {
                    "name": "foreign_expense_3",
                    "payment_mode": "company_account",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount_currency": 1000.00,
                    "total_amount": 3000.00,
                    "date": self.frozen_today,
                    "company_id": self.company_data["company"].id,
                    "currency_id": foreign_currency_2.id,
                    "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                },
            ]
        ).sorted("name")
        all_expenses = foreign_expense_1 | foreign_expense_2 | foreign_expense_3
        self.assertRecordValues(
            all_expenses,
            [
                {
                    "total_amount": 500.00,
                    "total_amount_currency": 1000.00,
                    "currency_rate": 0.50,
                },
                {
                    "total_amount": 1520.00,
                    "total_amount_currency": 1000.00,
                    "currency_rate": 1.52,
                },
                {
                    "total_amount": 3000.00,
                    "total_amount_currency": 1000.00,
                    "currency_rate": 3.00,
                },
            ],
        )

        foreign_expense_1.total_amount = 1000.00
        self.assertRecordValues(
            foreign_expense_1,
            [
                {
                    "total_amount": 1000.00,
                    "total_amount_currency": 1000.00,
                    "currency_rate": 1.0,
                },
            ],
        )

        with Form(foreign_expense_2) as expense_form:
            expense_form.total_amount = 2000.00
        self.assertRecordValues(
            foreign_expense_2,
            [
                {
                    "total_amount": 2000.00,
                    "total_amount_currency": 1000.00,
                    "currency_rate": 2.0,
                },
            ],
        )

        all_expenses.action_submit()
        all_expenses._do_approve()
        self.post_expenses_with_wizard(all_expenses, journal=foreign_sale_journal)
        self.assertRecordValues(
            all_expenses.account_move_id.sorted("id"),
            [
                {
                    "amount_total_in_currency_signed": 1000.00,
                    "amount_total_signed": 1000.00,
                    "currency_id": foreign_currency_1.id,
                },
                {
                    "amount_total_in_currency_signed": 1000.00,
                    "amount_total_signed": 2000.00,
                    "currency_id": foreign_currency_2.id,
                },
                {
                    "amount_total_in_currency_signed": 1000.00,
                    "amount_total_signed": 3000.00,
                    "currency_id": foreign_currency_2.id,
                },
            ],
        )
        self.assertRecordValues(
            all_expenses.account_move_id.origin_payment_id.sorted("id"),
            [
                {
                    "amount": 1000.00,
                    "payment_type": "outbound",
                    "currency_id": foreign_currency_1.id,
                },
                {
                    "amount": 1000.00,
                    "payment_type": "outbound",
                    "currency_id": foreign_currency_2.id,
                },
                {
                    "amount": 1000.00,
                    "payment_type": "outbound",
                    "currency_id": foreign_currency_2.id,
                },
            ],
        )

    def test_expense_company_dates(self):
        expenses = self.create_expenses(
            [
                {
                    "name": "Car Travel Expenses",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount": 350.00,
                    "payment_mode": "company_account",
                    "date": "2024-01-01",
                },
                {
                    "name": "Lunch expense",
                    "employee_id": self.expense_employee.id,
                    "product_id": self.product_c.id,
                    "total_amount": 90.00,
                    "payment_mode": "company_account",
                    "date": "2024-01-12",
                },
            ]
        ).sorted()

        expenses.action_submit()
        expenses.action_approve()
        expenses.action_post()

        move_twelve_january, move_first_january = expenses.account_move_id.sorted()

        self.assertEqual(
            move_twelve_january.date,
            fields.Date.to_date("2024-01-12"),
            "move date should be the same as the expense date",
        )
        self.assertEqual(
            move_first_january.date,
            fields.Date.to_date("2024-01-01"),
            "move date should be the same as the expense date",
        )
        self.assertTrue(
            90
            == move_twelve_january.amount_total
            == move_twelve_january.origin_payment_id.amount
        )
        self.assertTrue(
            350
            == move_first_january.amount_total
            == move_first_january.origin_payment_id.amount
        )
        self.assertRecordValues(
            expenses,
            [
                {
                    "date": fields.Date.from_string("2024-01-12"),
                    "total_amount": 90.00,
                    "state": "paid",
                },
                {
                    "date": fields.Date.from_string("2024-01-01"),
                    "total_amount": 350.00,
                    "state": "paid",
                },
            ],
        )

    def test_corner_case_defaults_values_from_product(self):
        self.env.ref("base.group_user").implied_ids -= self.env.ref("uom.group_uom")
        self.expense_user_employee.group_ids -= self.env.ref("uom.group_uom")

        Expense = self.env["hr.expense"].with_user(self.expense_user_employee)

        self.assertFalse(Expense.env.user.has_group("uom.group_uom"))

        product = Expense.env.ref("hr_expense.expense_product_mileage")

        expense_form = Form(Expense)
        expense_form.product_id = product
        expense = expense_form.save()
        self.assertEqual(expense.name, product.display_name)
        self.assertEqual(expense.product_uom_id, product.uom_id)
        self.assertEqual(
            expense.tax_ids,
            product.supplier_taxes_id.filtered_domain(
                self.env["account.tax"]._check_company_domain(expense.company_id)
            ),
        )
        self.assertEqual(expense.account_id, product._get_product_accounts()["expense"])

    def test_attachments_in_move_from_own_expense(self):
        expense = self.create_expenses({"name": "Employee expense"})
        expense_2 = self.create_expenses({"name": "Employee expense 2"})
        attachment = self.env["ir.attachment"].create(
            {
                "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "file1.png",
                "res_model": "hr.expense",
                "res_id": expense.id,
            }
        )
        attachment_2 = self.env["ir.attachment"].create(
            {
                "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "file2.png",
                "res_model": "hr.expense",
                "res_id": expense_2.id,
            }
        )

        expense.message_main_attachment_id = attachment
        expense_2.message_main_attachment_id = attachment_2
        expenses = expense | expense_2

        expenses.action_submit()
        expenses._do_approve()
        self.post_expenses_with_wizard(expenses)

        self.assertRecordValues(
            expenses.account_move_id.attachment_ids.sorted("name"),
            [
                {
                    "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "name": "file1.png",
                    "res_model": "account.move",
                    "res_id": expense.account_move_id.id,
                },
                {
                    "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "name": "file2.png",
                    "res_model": "account.move",
                    "res_id": expense_2.account_move_id.id,
                },
            ],
        )

    def test_attachments_in_move_from_company_expense(self):
        expense = self.create_expenses(
            {
                "name": "Company expense",
                "payment_mode": "company_account",
            }
        )
        expense_2 = self.create_expenses(
            {
                "name": "Company expense 2",
                "payment_mode": "company_account",
            }
        )
        attachment = self.env["ir.attachment"].create(
            {
                "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "file1.png",
                "res_model": "hr.expense",
                "res_id": expense.id,
            }
        )
        attachment_2 = self.env["ir.attachment"].create(
            {
                "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "file2.png",
                "res_model": "hr.expense",
                "res_id": expense_2.id,
            }
        )

        expense.message_main_attachment_id = attachment
        expense_2.message_main_attachment_id = attachment_2
        expenses = expense | expense_2

        expenses.action_submit()
        expenses._do_approve()
        expenses.action_post()

        expense_move = expense.account_move_id
        expense_2_move = expense_2.account_move_id
        self.assertRecordValues(
            expense_move.attachment_ids,
            [
                {
                    "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "name": "file1.png",
                    "res_model": "account.move",
                    "res_id": expense_move.id,
                }
            ],
        )

        self.assertRecordValues(
            expense_2_move.attachment_ids,
            [
                {
                    "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "name": "file2.png",
                    "res_model": "account.move",
                    "res_id": expense_2_move.id,
                }
            ],
        )

    def test_multiple_attachments_in_move_from_company_expense(self):
        expense = self.create_expenses(
            {
                "name": "Company expense",
                "payment_mode": "company_account",
            }
        )
        self.env["ir.attachment"].create(
            [
                {
                    "raw": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "name": f"file{i}.png",
                    "res_model": "hr.expense",
                    "res_id": expense.id,
                }
                for i in range(1, 3)
            ]
        )

        expense.action_submit()
        expense._do_approve()
        expense.action_post()

        self.assertEqual(len(expense.account_move_id.attachment_ids), 2)

    def test_expense_payment_method(self):
        default_payment_channel = self.company_data[
            "default_journal_bank"
        ].outbound_payment_channel_ids[0]
        check_method = (
            self.env["account.payment.method"]
            .sudo()
            .create(
                {
                    "name": "Print checks",
                    "code": "check_printing_expense_test",
                    "payment_type": "outbound",
                }
            )
        )
        new_payment_channel = self.env["account.payment.channel"].create(
            {
                "name": "Check",
                "payment_method_id": check_method.id,
                "journal_id": self.company_data["default_journal_bank"].id,
                "payment_account_id": self.inbound_payment_channel.payment_account_id.id,
            }
        )

        expense = self.create_expenses(
            {
                "payment_channel_id": default_payment_channel.id,
                "payment_mode": "company_account",
            }
        )

        self.assertRecordValues(
            expense, [{"payment_channel_id": default_payment_channel.id}]
        )
        expense.payment_channel_id = new_payment_channel

        expense.action_submit()
        expense.action_approve()
        expense.action_post()
        self.assertRecordValues(
            expense.account_move_id.origin_payment_id,
            [{"payment_channel_id": new_payment_channel.id}],
        )

    @freeze_time("2024-01-01")
    def test_expense_vendor(self):
        vendor_a = self.env["res.partner"].create({"name": "Ruben"})
        expense = self.create_expenses(
            {
                "payment_mode": "company_account",
                "vendor_id": vendor_a.id,
            }
        )
        expense.action_submit()
        expense.action_approve()
        expense.action_post()

        self.assertEqual(vendor_a.id, expense.account_move_id.line_ids.partner_id.id)

    def test_payment_edit_fields(self):
        expense = self.create_expenses(
            {
                "payment_mode": "company_account",
                "total_amount_currency": 1000.00,
            }
        )
        expense.action_submit()
        expense.action_approve()
        expense.action_post()
        payment = expense.account_move_id.origin_payment_id

        with self.assertRaises(
            UserError, msg="Cannot edit payment amount after linking to an expense"
        ):
            payment.write({"amount": 500})

        payment.write({"is_sent": True})

    def test_corner_case_expense_submitted_cannot_be_zero(self):
        expense = self.create_expenses(
            {"total_amount": 0.0, "total_amount_currency": 0.0}
        )

        with self.assertRaises(UserError):
            expense.action_submit()

        expense.total_amount_currency = 1000
        expense.action_submit()
        with self.assertRaises(UserError):
            expense.total_amount_currency = 0.0
        with self.assertRaises(UserError):
            expense.total_amount = 0.0

        expense.action_approve()
        with self.assertRaises(UserError):
            expense.total_amount_currency = 0.0
        with self.assertRaises(UserError):
            expense.total_amount = 0.0

        self.post_expenses_with_wizard(expense)
        with self.assertRaises(UserError):
            expense.total_amount_currency = 0.0
        with self.assertRaises(UserError):
            expense.total_amount = 0.0

        expense.account_move_id.action_draft()
        expense.account_move_id.unlink()
        expense.action_reset()
        expense.write({"total_amount_currency": 0.0, "total_amount": 0.0})

        expense.write({"total_amount_currency": 1000.0, "total_amount": 1000.0})
        with self.assertRaises(UserError):
            expense.write({"total_amount_currency": 0.0, "state": "submitted"})
        with self.assertRaises(UserError):
            expense.write({"total_amount": 0.0, "state": "submitted"})

        expense.write(
            {"total_amount_currency": 0.0, "total_amount": 0.0, "state": "draft"}
        )

    def test_foreign_currencies_total(self):
        self.create_expenses(
            [
                {
                    "name": "Company expense",
                    "payment_mode": "company_account",
                    "total_amount_currency": 1000.00,
                    "employee_id": self.expense_employee.id,
                },
                {
                    "name": "Employee expense",
                    "payment_mode": "own_account",
                    "currency_id": self.other_currency.id,
                    "total_amount_currency": 1000.00,
                    "total_amount": 2000.00,
                    "employee_id": self.expense_employee.id,
                },
            ]
        )
        expense_data = (
            self.env["hr.expense"]
            .with_user(self.expense_user_employee)
            .get_expense_dashboard()
        )
        self.assertEqual(expense_data["draft"]["amount"], 3000.00)

    def test_update_expense_price_on_product_standard_price(self):
        product = self.env["product.product"].create(
            {
                "name": "Product",
                "standard_price": 100.0,
            }
        )
        expenses = expense_no_update, expense_update = self.create_expenses(
            [
                {"name": name, "product_id": product.id, "total_amount": 100.0}
                for name in ("test no update", "test update")
            ]
        ).sorted("name")

        self.assertRecordValues(
            expenses.sorted("name"),
            [
                {
                    "name": "test no update",
                    "price_unit": 100.0,
                    "quantity": 1,
                    "total_amount": 100.0,
                },
                {
                    "name": "test update",
                    "price_unit": 100.0,
                    "quantity": 1,
                    "total_amount": 100.0,
                },
            ],
        )
        expense_no_update.action_submit()

        product.standard_price = 200.0
        self.assertRecordValues(
            expenses.sorted("name"),
            [
                {
                    "name": "test no update",
                    "price_unit": 100.0,
                    "quantity": 1.0,
                    "total_amount": 100.0,
                },
                {
                    "name": "test update",
                    "price_unit": 200.0,
                    "quantity": 1.0,
                    "total_amount": 200.0,
                },
            ],
        )

        expense_update.quantity = 5
        self.assertRecordValues(
            expenses.sorted("name"),
            [
                {
                    "name": "test no update",
                    "price_unit": 100.0,
                    "quantity": 1,
                    "total_amount": 100.0,
                },
                {
                    "name": "test update",
                    "price_unit": 200.0,
                    "quantity": 5,
                    "total_amount": 1000.0,
                },
            ],
        )

        product.standard_price = 0.0
        self.assertRecordValues(
            expenses.sorted("name"),
            [
                {
                    "name": "test no update",
                    "price_unit": 100.0,
                    "quantity": 1,
                    "total_amount": 100.0,
                },
                {
                    "name": "test update",
                    "price_unit": 1000.0,
                    "quantity": 1,
                    "total_amount": 1000.0,
                },
            ],
        )

        expenses.action_submit()
        product.standard_price = 300.0
        self.assertRecordValues(
            expenses.sorted("name"),
            [
                {
                    "name": "test no update",
                    "price_unit": 100.0,
                    "quantity": 1,
                    "total_amount": 100.0,
                },
                {
                    "name": "test update",
                    "price_unit": 1000.0,
                    "quantity": 1,
                    "total_amount": 1000.0,
                },
            ],
        )

    def test_expense_standard_price_update_warning(self):
        expense_cat_A = self.env["product.product"].create(
            {
                "name": "Category A",
                "default_code": "CA",
                "standard_price": 0.0,
            }
        )
        expense_cat_B = self.env["product.product"].create(
            {
                "name": "Category B",
                "default_code": "CB",
                "standard_price": 0.0,
            }
        )
        expense_cat_C = self.env["product.product"].create(
            {
                "name": "Category C",
                "default_code": "CC",
                "standard_price": 0.0,
            }
        )
        self.create_expenses(
            [
                {
                    "name": "Expense 1",
                    "product_id": expense_cat_A.id,
                    "total_amount": 1,
                },
                {
                    "name": "Expense 2",
                    "product_id": expense_cat_B.id,
                    "total_amount": 5,
                },
            ]
        )

        self.assertFalse(expense_cat_A.standard_price_update_warning)
        self.assertFalse(expense_cat_B.standard_price_update_warning)
        self.assertFalse(expense_cat_C.standard_price_update_warning)

        with Form(
            expense_cat_A, view="hr_expense.product_product_expense_form_view"
        ) as form:
            form.standard_price = 5
            self.assertTrue(form.standard_price_update_warning)

        with Form(
            expense_cat_B, view="hr_expense.product_product_expense_form_view"
        ) as form:
            form.standard_price = 5
            self.assertFalse(form.standard_price_update_warning)

        with Form(
            expense_cat_C, view="hr_expense.product_product_expense_form_view"
        ) as form:
            form.standard_price = 5
            self.assertFalse(form.standard_price_update_warning)

    def test_compute_standard_price_update_warning_product_with_and_without_expense(
        self,
    ):
        product_expensed = self.env["product.product"].create(
            {
                "name": "Category A",
                "default_code": "CA",
                "standard_price": 0.0,
            }
        )
        product_not_expensed = self.env["product.product"].create(
            {
                "name": "Category B",
                "default_code": "CB",
                "standard_price": 0.0,
            }
        )
        self.env["hr.expense"].create(
            {
                "employee_id": self.expense_employee.id,
                "name": "Expense 1",
                "product_id": product_expensed.id,
                "total_amount": 1,
            }
        )

        (
            product_expensed | product_not_expensed
        )._compute_standard_price_update_warning()

    def test_expense_multi_company(self):
        main_company = self.company_data["company"]
        other_company = self.company_data_2["company"]
        self.expense_employee.sudo().company_id = other_company

        self.product_a.with_context(
            allowed_company_ids=self.company_data_2["company"].ids
        ).standard_price = 100

        Expense = (
            self.env["hr.expense"]
            .with_user(self.expense_user_employee)
            .with_context(allowed_company_ids=other_company.ids)
        )
        expense_approve = Expense.create(
            [
                {
                    "name": "First Expense for employee",
                    "employee_id": self.expense_employee.id,
                    "date": "2016-01-01",
                    "product_id": self.product_a.id,
                    "quantity": 1200.0,
                }
            ]
        )
        expense_refuse = Expense.create(
            [
                {
                    "name": "Second Expense for employee",
                    "employee_id": self.expense_employee.id,
                    "date": "2016-01-01",
                    "product_id": self.product_a.id,
                    "quantity": 1000.0,
                }
            ]
        )
        expenses = expense_approve | expense_refuse
        self.assertRecordValues(
            expenses,
            [
                {"company_id": self.company_data_2["company"].id},
                {"company_id": self.company_data_2["company"].id},
            ],
        )

        expenses.with_user(self.expense_user_employee).action_submit()

        with self.assertRaises(UserError):
            expense_approve.with_user(self.expense_user_manager).with_context(
                allowed_company_ids=main_company.ids, company_id=main_company.id
            ).action_approve()

        with self.assertRaises(UserError):
            expense_refuse.with_user(self.expense_user_manager).with_context(
                allowed_company_ids=main_company.ids
            )._do_refuse("failed")

        expense_approve.with_user(self.expense_user_manager).with_context(
            allowed_company_ids=other_company.ids
        ).action_approve()
        expense_refuse.with_user(self.expense_user_manager).with_context(
            allowed_company_ids=other_company.ids
        )._do_refuse("failed")

        with self.assertRaises(UserError):
            self.post_expenses_with_wizard(
                expense_approve.with_user(self.env.user).with_context(
                    allowed_company_ids=main_company.ids
                )
            )

        self.post_expenses_with_wizard(
            expense_approve.with_user(self.env.user).with_context(
                allowed_company_ids=other_company.ids
            )
        )

    def test_tax_is_used_when_in_transactions(self):
        tax_expense = self.env["account.tax"].create(
            {
                "name": "test_is_used_expenses",
                "amount": "100",
                "include_base_amount": True,
            }
        )

        self.create_expenses({"tax_ids": [Command.set(tax_expense.ids)]})
        tax_expense.invalidate_model(fnames=["is_used"])
        self.assertTrue(tax_expense.is_used)

    def test_expense_by_company_with_caba_tax(self):
        caba_tag = self.env["account.account.tag"].create(
            {
                "name": "Cash Basis Tag Final Account",
                "applicability": "taxes",
            }
        )
        caba_transition_account = self.env["account.account"].create(
            {
                "name": "Cash Basis Tax Transition Account",
                "account_type": "asset_current",
                "code": "131001",
                "reconcile": True,
            }
        )
        caba_tax = self.env["account.tax"].create(
            {
                "name": "Cash Basis Tax",
                "tax_exigibility": "on_payment",
                "amount": 15,
                "cash_basis_transition_account_id": caba_transition_account.id,
                "invoice_repartition_line_ids": [
                    Command.create(
                        {
                            "factor_percent": 100,
                            "repartition_type": "base",
                        }
                    ),
                    Command.create(
                        {
                            "factor_percent": 100,
                            "repartition_type": "tax",
                            "tag_ids": caba_tag.ids,
                        }
                    ),
                ],
            }
        )

        expense = self.create_expenses(
            {
                "payment_mode": "company_account",
                "tax_ids": [Command.set(caba_tax.ids)],
            }
        )
        expense.action_submit()
        expense.action_approve()
        expense.action_post()
        moves = expense.account_move_id
        tax_lines = moves.line_ids.filtered(lambda line: line.tax_line_id == caba_tax)
        self.assertNotEqual(
            tax_lines.account_id,
            caba_transition_account,
            "The tax should not be on the transition account",
        )
        self.assertEqual(
            tax_lines.tax_tag_ids, caba_tag, "The tax should still retrieve its tags"
        )

    def test_expense_mandatory_analytic_plan_product_category(self):
        self.env["account.analytic.applicability"].create(
            {
                "business_domain": "expense",
                "analytic_plan_id": self.analytic_plan.id,
                "applicability": "mandatory",
                "product_categ_id": self.product_a.categ_id.id,
            }
        )

        expense = self.create_expenses(
            {
                "product_id": self.product_a.id,
                "quantity": 350.00,
                "payment_mode": "company_account",
            }
        )

        expense.action_submit()
        with self.assertRaises(
            ValidationError,
            msg="One or more lines require a 100% analytic distribution.",
        ):
            expense.with_context(validate_analytic=True).action_approve()
        expense.analytic_distribution = {self.analytic_account_1.id: 100.00}
        expense.with_context(validate_analytic=True).action_approve()

    def test_expense_no_stealing_from_employees(self):
        self.expense_employee.partner_id.parent_id = self.env.company.partner_id
        self.assertEqual(
            self.env.company.partner_id,
            self.expense_employee.partner_id.commercial_partner_id,
        )

        expense = self.create_expenses({"employee_id": self.expense_employee.id})
        expense.action_submit()
        expense.action_approve()
        self.post_expenses_with_wizard(expense)
        move = expense.account_move_id

        self.assertNotEqual(move.commercial_partner_id, self.env.company.partner_id)
        self.assertEqual(move.partner_id, self.expense_employee.partner_id)
        self.assertEqual(
            move.commercial_partner_id, self.expense_employee.partner_id
        )

    def test_expense_set_total_amount_to_0(self):
        expense = self.create_expenses(
            {
                "product_id": self.product_c.id,
                "total_amount_currency": 100.0,
            }
        )
        expense.total_amount_currency = 0.0
        self.assertTrue(expense.currency_id.is_zero(expense.tax_amount))
        self.assertTrue(expense.company_currency_id.is_zero(expense.total_amount))

    def test_expense_set_quantity_to_0(self):
        expense = self.create_expenses(
            {"product_id": self.product_b.id, "quantity": 10}
        )
        expense.quantity = 0
        self.assertTrue(expense.currency_id.is_zero(expense.total_amount_currency))
        self.assertEqual(
            expense.company_currency_id.compare_amounts(
                expense.price_unit, self.product_b.standard_price
            ),
            0,
        )

    def test_employee_expense_in_foreign_currency(self):
        expense = self.create_expenses(
            {
                "payment_mode": "own_account",
                "currency_id": self.other_currency.id,
            }
        )
        expense.action_submit()
        expense.action_approve()
        expense._post_without_wizard()
        self.assertRecordValues(
            expense.account_move_id,
            [
                {
                    "amount_total": 500.0,
                    "currency_id": expense.account_move_id.company_currency_id.id,
                }
            ],
        )

    def test_company_expense_sepa_ct_trust_bypass(self):
        self.env.ref("base.EUR").active = True
        bank_journal = self.company_data["default_journal_bank"]
        bank = self.env["res.bank"].create(
            {
                "name": "BNP Paribas",
                "bic": "GEBABEBB",
            }
        )
        bank_journal.write(
            {
                "bank_id": bank.id,
                "bank_acc_number": "BE48363523682327",
                "currency_id": self.env.ref("base.EUR").id,
            }
        )

        sepa_ct_line = bank_journal.outbound_payment_channel_ids.filtered(
            lambda l: l.code == "sepa_ct"
        )
        if not sepa_ct_line:
            self.skipTest(
                "SEPA Credit Transfer payment method not available (account_sepa module not installed)"
            )

        expense = self.create_expenses(
            {
                "name": "Hotel",
                "payment_mode": "company_account",
                "payment_channel_id": sepa_ct_line.id,
                "total_amount_currency": 100.00,
                "currency_id": self.env.ref("base.EUR").id,
            }
        )

        expense.action_submit()
        expense.action_approve()
        expense.action_post()

    def test_expense_analytic_vendor_bill_count(self):
        expense = self.create_expenses(
            [
                {
                    "name": "Employee PA 2*800 + 15%",
                    "analytic_distribution": {self.analytic_account_1.id: 100},
                }
            ]
        )
        expense.action_submit()
        expense.action_approve()
        self.post_expenses_with_wizard(expense)

        self.assertEqual("in_receipt", expense.account_move_id.move_type)

        vendor_bill_view = self.analytic_account_1.action_view_vendor_bill()
        self.assertTrue(expense.account_move_id.id in vendor_bill_view["domain"][0][2])

    def test_expense_paid_company_no_autobalancing_line(self):
        expense = self.create_expenses(
            {
                "name": "Expense for John Smith",
                "employee_id": self.expense_employee.id,
                "total_amount_currency": 100.0,
                "product_id": self.product_c.id,
                "payment_mode": "company_account",
                "company_id": self.company_data["company"].id,
                "tax_ids": [self.tax_sale_a.id],
            }
        )

        expense.action_submit()
        expense.action_approve()
        expense.analytic_distribution = {self.analytic_account_1.id: 100.00}
        expense.action_post()

        self.assertEqual(
            expense.account_move_id.line_ids.mapped("balance"), [86.96, 13.04, -100.0]
        )


@tagged("-at_install", "post_install")
class TestExpenseProductTaxAccess(TestExpenseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company_data = cls.setup_other_company(name="Tax Rule Co")
        cls.other_tax = cls.other_company_data["default_tax_purchase"]
        cls.foreign_taxed_product = cls.env["product.product"].create(
            {
                "name": "Carries another company's tax",
                "type": "service",
                "can_be_expensed": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.set(cls.other_tax.ids)],
            },
        )

    def _reader(self, record):
        return record.with_user(self.expense_user_employee).with_context(
            allowed_company_ids=self.env.company.ids,
        )

    def test_product_has_tax_reads_across_the_company_rule(self):
        expense = self.env["hr.expense"].create(
            {
                "name": "Expense on a foreign-taxed product",
                "employee_id": self.expense_employee.id,
                "product_id": self.foreign_taxed_product.id,
                "total_amount_currency": 100.0,
            },
        )
        reader = self._reader(expense)
        reader.invalidate_recordset()
        self.assertFalse(reader.product_has_tax)

    def test_split_wizard_product_has_tax_reads_across_the_company_rule(self):
        expense = self.env["hr.expense"].create(
            {
                "name": "Expense to split",
                "employee_id": self.expense_employee.id,
                "product_id": self.foreign_taxed_product.id,
                "total_amount_currency": 100.0,
            },
        )
        wizard = self._reader(self.env["hr.expense.split.wizard"]).browse(
            self._reader(expense).action_split_wizard()["res_id"],
        )
        splits = wizard.expense_split_line_ids
        splits.invalidate_recordset()
        self.assertTrue(splits)
        self.assertFalse(any(splits.mapped("product_has_tax")))
