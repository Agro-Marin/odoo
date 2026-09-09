from odoo import Command
from odoo.tests import tagged

from odoo.addons.hr_expense.tests.common import TestExpenseCommon
from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("-at_install", "post_install")
class TestReInvoice(TestExpenseCommon, TestSaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_sale_tax, new_purchase_tax = cls.env["account.tax"].create(
            [
                {
                    "name": "Tax 12.499%",
                    "amount": 12.499,
                    "amount_type": "percent",
                    "type_tax_use": tax_type,
                    "repartition_line_ids": [
                        Command.create(
                            {"document_type": "invoice", "repartition_type": "base"}
                        ),
                        Command.create(
                            {
                                "document_type": "invoice",
                                "repartition_type": "tax",
                                "account_id": cls.company_data[
                                    f"default_account_tax_{tax_type}"
                                ].id,
                            }
                        ),
                        Command.create(
                            {"document_type": "refund", "repartition_type": "base"}
                        ),
                        Command.create(
                            {
                                "document_type": "refund",
                                "repartition_type": "tax",
                                "account_id": cls.company_data[
                                    f"default_account_tax_{tax_type}"
                                ].id,
                            }
                        ),
                    ],
                }
                for tax_type in ("sale", "purchase")
            ]
        )
        cls.company_data.update(
            {
                "service_order_sales_price": cls.env["product.product"]
                .with_company(cls.company_data["company"])
                .create(
                    {
                        "name": "service_order_sales_price",
                        "categ_id": cls.product_category.id,
                        "standard_price": 0.0,
                        "list_price": 280.39,
                        "type": "service",
                        "weight": 0.01,
                        "uom_id": cls.env.ref("uom.product_uom_unit").id,
                        "default_code": "FURN_99991",
                        "invoice_policy": "ordered",
                        "expense_policy": "sales_price",
                        "taxes_id": [Command.set([new_sale_tax.id])],
                        "supplier_taxes_id": [Command.set([new_purchase_tax.id])],
                        "can_be_expensed": True,
                    }
                ),
                "service_delivery_sales_price": cls.env["product.product"]
                .with_company(cls.company_data["company"])
                .create(
                    {
                        "name": "service_order_sales_price",
                        "categ_id": cls.product_category.id,
                        "standard_price": 0.0,
                        "list_price": 280.39,
                        "type": "service",
                        "weight": 0.01,
                        "uom_id": cls.env.ref("uom.product_uom_unit").id,
                        "default_code": "FURN_99992",
                        "invoice_policy": "transferred",
                        "expense_policy": "sales_price",
                        "taxes_id": [Command.set([new_sale_tax.id])],
                        "supplier_taxes_id": [Command.set([new_purchase_tax.id])],
                        "can_be_expensed": True,
                    }
                ),
                "service_delivery_cost_price": cls.env["product.product"]
                .with_company(cls.company_data["company"])
                .create(
                    {
                        "name": "service_delivery_cost_price",
                        "categ_id": cls.product_category.id,
                        "standard_price": 235.28,
                        "list_price": 280.39,
                        "type": "service",
                        "weight": 0.01,
                        "uom_id": cls.env.ref("uom.product_uom_unit").id,
                        "default_code": "FURN_99993",
                        "invoice_policy": "transferred",
                        "expense_policy": "cost",
                        "taxes_id": [Command.set([new_sale_tax.id])],
                        "supplier_taxes_id": [Command.set([new_purchase_tax.id])],
                        "can_be_expensed": True,
                    }
                ),
                "service_order_cost_price": cls.env["product.product"]
                .with_company(cls.company_data["company"])
                .create(
                    {
                        "name": "service_order_cost_price",
                        "categ_id": cls.product_category.id,
                        "standard_price": 235.28,
                        "list_price": 280.39,
                        "type": "service",
                        "weight": 0.01,
                        "uom_id": cls.env.ref("uom.product_uom_unit").id,
                        "default_code": "FURN_99994",
                        "invoice_policy": "ordered",
                        "expense_policy": "cost",
                        "taxes_id": [Command.set([new_sale_tax.id])],
                        "supplier_taxes_id": [Command.set([new_purchase_tax.id])],
                        "can_be_expensed": True,
                    }
                ),
            }
        )
        cls.expense_sale_order = (
            cls.env["sale.order"]
            .with_context(mail_notrack=True, mail_create_nolog=True)
            .create(
                {
                    "partner_id": cls.partner_a.id,
                    "partner_invoice_id": cls.partner_a.id,
                    "partner_shipping_id": cls.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": "expense_employee: expense_1 invoicing=order, expense=sales_price",
                                "product_id": cls.company_data[
                                    "product_order_sales_price"
                                ].id,
                                "product_qty": 3.0,
                                "price_unit": cls.company_data[
                                    "product_order_sales_price"
                                ].standard_price,
                            }
                        )
                    ],
                }
            )
        )
        cls.expense_sale_order.action_confirm()

        cls.sale_exp_order_sale_1 = cls.create_expenses(
            {
                "name": "expense_1 invoicing=order, expense=sales_price",
                "date": "2016-01-01",
                "product_id": cls.company_data["service_order_sales_price"].id,
                "total_amount": 100.34,
                "analytic_distribution": {cls.analytic_account_1.id: 100},
                "employee_id": cls.expense_employee.id,
                "sale_order_id": cls.expense_sale_order.id,
            }
        )
        cls.sale_exp_order_sale_2 = cls.create_expenses(
            {
                "name": "expense_2 invoicing=order, expense=sales_price",
                "date": "2016-01-02",
                "product_id": cls.company_data["service_order_sales_price"].id,
                "total_amount": 100.21,
                "sale_order_id": cls.expense_sale_order.id,
            }
        )
        cls.sale_exp_deliv_sale_3 = cls.create_expenses(
            {
                "name": "expense_3 invoicing=delivery, expense=sales_price",
                "date": "2016-01-03",
                "product_id": cls.company_data["service_delivery_sales_price"].id,
                "total_amount": 10012.49,
                "analytic_distribution": {cls.analytic_account_1.id: 100},
                "sale_order_id": cls.expense_sale_order.id,
            }
        )
        cls.sale_exp_deliv_sale_4 = cls.create_expenses(
            {
                "name": "expense_4 invoicing=delivery, expense=sales_price",
                "date": "2016-01-03",
                "product_id": cls.company_data["service_delivery_sales_price"].id,
                "analytic_distribution": {cls.analytic_account_1.id: 100},
                "total_amount": 10012.49,
                "sale_order_id": cls.expense_sale_order.id,
            }
        )
        cls.sale_exp_deliv_cost_5 = cls.create_expenses(
            {
                "name": "expense_5 invoicing=delivery, expense=cost",
                "date": "2016-01-03",
                "product_id": cls.company_data["service_delivery_cost_price"].id,
                "quantity": 5,
                "sale_order_id": cls.expense_sale_order.id,
            }
        )
        cls.sale_exp_order_cost_6 = cls.create_expenses(
            {
                "name": "expense_6 invoicing=order, expense=cost",
                "date": "2016-01-03",
                "product_id": cls.company_data["service_order_cost_price"].id,
                "quantity": 6,
                "sale_order_id": cls.expense_sale_order.id,
            },
        )
        cls.sale_expense_all = (
            cls.sale_exp_order_sale_1
            | cls.sale_exp_order_sale_2
            | cls.sale_exp_deliv_sale_3
            | cls.sale_exp_deliv_sale_4
            | cls.sale_exp_deliv_cost_5
            | cls.sale_exp_order_cost_6
        )
        cls.sale_expense_all.action_submit()
        cls.sale_expense_all._do_approve()

    def test_expenses_reinvoice_case_1_create_moves(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {
                    "qty_transferred": 0.0,
                    "product_qty": 3.0,
                    "is_expense": False,
                    "expense_ids": [],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_order_sale_1.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_order_sale_2.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_deliv_sale_3.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_deliv_sale_4.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_deliv_cost_5.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "is_expense": True,
                    "expense_ids": [self.sale_exp_order_cost_6.id],
                },
            ],
        )

    def test_expenses_reinvoice_case_2_reset_expense_to_draft(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.sale_expense_all.account_move_id.action_draft()
        self.sale_expense_all.account_move_id.unlink()
        self.sale_expense_all.action_reset()

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
            ],
        )

    def test_expenses_reinvoice_case_3_recreate_move_after_reset(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.sale_expense_all.account_move_id.action_draft()
        self.sale_expense_all.account_move_id.unlink()
        self.sale_expense_all.action_reset()

        self.sale_expense_all.action_submit()
        self.sale_expense_all._do_approve()
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_1.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_2.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_3.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_4.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "expense_ids": [self.sale_exp_deliv_cost_5.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "expense_ids": [self.sale_exp_order_cost_6.id],
                },
            ],
        )

    def test_expenses_reinvoice_case_4_reset_expense_move_to_draft(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.sale_expense_all.account_move_id.action_draft()

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
            ],
        )

    def test_expenses_reinvoice_case_5_repost_expense_move_after_reset_to_draft(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.sale_expense_all.account_move_id.action_draft()

        self.sale_expense_all.account_move_id.action_post()

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_1.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_2.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_3.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_4.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "expense_ids": [self.sale_exp_deliv_cost_5.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "expense_ids": [self.sale_exp_order_cost_6.id],
                },
            ],
        )

    def test_expenses_reinvoice_case_6_reverse_expense_move(self):
        self.post_expenses_with_wizard(self.sale_expense_all)

        self.sale_expense_all.account_move_id._reverse_moves()

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
            ],
        )

    def test_expenses_reinvoice_case_7_ensure_one2one_relationship(self):
        sale_exp_order_sale_1_copy = self.sale_exp_order_sale_1.copy()
        sale_exp_order_sale_2_copy = self.sale_exp_order_sale_2.copy()
        sale_exp_deliv_sale_3_copy = self.sale_exp_deliv_sale_3.copy()
        sale_exp_deliv_sale_4_copy = self.sale_exp_deliv_sale_4.copy()
        sale_exp_deliv_cost_5_copy = self.sale_exp_deliv_cost_5.copy()
        sale_exp_order_cost_6_copy = self.sale_exp_order_cost_6.copy()

        sale_expense_copies_all = (
            sale_exp_order_sale_1_copy
            | sale_exp_order_sale_2_copy
            | sale_exp_deliv_sale_3_copy
            | sale_exp_deliv_sale_4_copy
            | sale_exp_deliv_cost_5_copy
            | sale_exp_order_cost_6_copy
        )
        sale_expense_original_all = self.sale_expense_all
        self.sale_expense_all |= sale_expense_copies_all

        sale_expense_copies_all.action_submit()
        sale_expense_copies_all._do_approve()
        self.post_expenses_with_wizard(sale_expense_original_all)
        self.post_expenses_with_wizard(sale_expense_copies_all)

        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_1.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_order_sale_2.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_3.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [self.sale_exp_deliv_sale_4.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "expense_ids": [self.sale_exp_deliv_cost_5.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "expense_ids": [self.sale_exp_order_cost_6.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_order_sale_1_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_order_sale_2_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_deliv_sale_3_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_deliv_sale_4_copy.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "expense_ids": [sale_exp_deliv_cost_5_copy.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "expense_ids": [sale_exp_order_cost_6_copy.id],
                },
            ],
        )

        sale_expense_original_all.account_move_id.action_draft()
        self.assertRecordValues(
            self.expense_sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 3.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {"qty_transferred": 0.0, "product_qty": 0.0, "expense_ids": []},
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_order_sale_1_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_order_sale_2_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_deliv_sale_3_copy.id],
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "expense_ids": [sale_exp_deliv_sale_4_copy.id],
                },
                {
                    "qty_transferred": 5.0,
                    "product_qty": 5.0,
                    "expense_ids": [sale_exp_deliv_cost_5_copy.id],
                },
                {
                    "qty_transferred": 6.0,
                    "product_qty": 6.0,
                    "expense_ids": [sale_exp_order_cost_6_copy.id],
                },
            ],
        )

    def test_expenses_reinvoice_analytic_distribution(self):

        (
            self.company_data["product_order_sales_price"]
            + self.company_data["product_delivery_sales_price"]
        ).write(
            {
                "can_be_expensed": True,
            }
        )

        sale_order = (
            self.env["sale.order"]
            .with_context(mail_notrack=True, mail_create_nolog=True)
            .create(
                {
                    "partner_id": self.partner_a.id,
                    "partner_invoice_id": self.partner_a.id,
                    "partner_shipping_id": self.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": self.company_data[
                                    "product_order_sales_price"
                                ].name,
                                "product_id": self.company_data[
                                    "product_order_sales_price"
                                ].id,
                                "product_qty": 2.0,
                                "price_unit": 1000.0,
                            }
                        )
                    ],
                }
            )
        )
        sale_order.action_confirm()

        expense = self.create_expenses(
            {
                "name": "expense_1",
                "date": "2016-01-01",
                "product_id": self.company_data["product_order_sales_price"].id,
                "quantity": 2,
                "analytic_distribution": {
                    self.analytic_account_1.id: 50,
                    self.analytic_account_2.id: 50,
                },
                "employee_id": self.expense_employee.id,
                "sale_order_id": sale_order.id,
            }
        )

        expense.action_submit()
        expense.action_approve()
        self.post_expenses_with_wizard(expense)

        self.assertRecordValues(
            sale_order.line_ids,
            [
                {"qty_transferred": 0.0, "product_qty": 2.0, "is_expense": False},
                {"qty_transferred": 2.0, "product_qty": 2.0, "is_expense": True},
            ],
        )

    def test_expense_reinvoice_tax_multine_line(self):
        multi_distribution_tax = self.env["account.tax"].create(
            {
                "name": "Tax 10.00%",
                "amount": 10.00,
                "amount_type": "percent",
                "type_tax_use": "purchase",
                "invoice_repartition_line_ids": [
                    Command.create(
                        {
                            "repartition_type": "base",
                            "use_in_tax_closing": False,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 70,
                            "use_in_tax_closing": False,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 30,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                            "use_in_tax_closing": True,
                        }
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create(
                        {
                            "repartition_type": "base",
                            "use_in_tax_closing": False,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 70,
                            "use_in_tax_closing": False,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 30,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                            "use_in_tax_closing": True,
                        }
                    ),
                ],
            }
        )
        (
            self.company_data["product_order_sales_price"]
            + self.company_data["product_delivery_sales_price"]
        ).write(
            {
                "can_be_expensed": True,
            }
        )

        sale_order = (
            self.env["sale.order"]
            .with_context(mail_notrack=True, mail_create_nolog=True)
            .create(
                {
                    "partner_id": self.partner_a.id,
                    "partner_invoice_id": self.partner_a.id,
                    "partner_shipping_id": self.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": self.company_data[
                                    "product_order_sales_price"
                                ].name,
                                "product_id": self.company_data[
                                    "product_order_sales_price"
                                ].id,
                                "product_qty": 1.0,
                                "price_unit": 1000.0,
                            }
                        )
                    ],
                }
            )
        )
        sale_order.action_confirm()

        expense = self.create_expenses(
            [
                {
                    "name": "expense_1",
                    "date": "2016-01-01",
                    "product_id": self.company_data["product_order_sales_price"].id,
                    "quantity": 1,
                    "employee_id": self.expense_employee.id,
                    "sale_order_id": sale_order.id,
                    "tax_ids": multi_distribution_tax.ids,
                }
            ]
        )

        expense.action_submit()
        expense._do_approve()
        self.post_expenses_with_wizard(expense)

        self.assertRecordValues(
            sale_order.line_ids,
            [
                {
                    "qty_transferred": 0.0,
                    "product_qty": 1.0,
                    "is_expense": False,
                },
                {
                    "qty_transferred": 1.0,
                    "product_qty": 1.0,
                    "is_expense": True,
                },
            ],
        )
