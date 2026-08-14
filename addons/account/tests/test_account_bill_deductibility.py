from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountBillPartialDeductibility(AccountTestInvoicingCommon):
    def test_simple_bill_partial_deductibility(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 3.75,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -115.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

        # Rewriting the bill must not reorder it: the non-deductible block keeps
        # the position it had on creation, before the tax and payment-term lines.
        bill.invoice_line_ids[0].quantity = 2
        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 200.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -50.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 50.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 7.5,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 22.5, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -230.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

        bill.invoice_line_ids[0].price_unit = 50.0
        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 3.75,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -115.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

        bill.invoice_line_ids[0].deductible_amount = 100.0
        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {"display_type": "tax", "name": "15%", "balance": 15.0, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -115.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

        bill.invoice_line_ids[0].deductible_amount = 75.0
        bill.action_post()
        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                # Posting renames the two summary lines after the entry, which
                # is what puts the total ahead of the per-line one here: they
                # share a sequence and assertInvoiceValues breaks ties on name.
                {
                    "display_type": "non_deductible_product_total",
                    "name": bill.name + " - private part",
                    "balance": 25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": bill.name + " - private part (taxes)",
                    "balance": 3.75,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -115.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_identical_lines(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    ),
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 50.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 7.5,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 22.5, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -230.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_several_invoice_lines(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item 1",
                            "price_unit": 100,
                            "quantity": 3,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "name": "Partial item 2",
                            "price_unit": 150,
                            "quantity": 1,
                            "deductible_amount": 80.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "name": "Full item",
                            "price_unit": 200,
                            "quantity": 1,
                            "deductible_amount": 100.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    ),
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Full item",
                    "balance": 200.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "product",
                    "name": "Partial item 1",
                    "balance": 300.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "product",
                    "name": "Partial item 2",
                    "balance": 150.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item 1",
                    "balance": -75.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item 2",
                    "balance": -30.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 105.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 15.75,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 81.75, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -747.5,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_different_taxes(self):
        tax_21 = self.tax_purchase_a.copy(
            {
                "name": "21%",
                "amount": 21,
            }
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [
                                Command.set((self.tax_purchase_a + tax_21).ids),
                            ],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id, tax_21.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id, tax_21.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 9.0,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {"display_type": "tax", "name": "21%", "balance": 15.75, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -136.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_several_lines_with_different_taxes(self):
        tax_21 = self.tax_purchase_a.copy(
            {
                "name": "21%",
                "amount": 21,
            }
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item 1",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [
                                Command.set(self.tax_purchase_a.ids),
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "name": "Partial item 2",
                            "price_unit": 120,
                            "quantity": 2,
                            "deductible_amount": 50.00,
                            "tax_ids": [
                                Command.set(tax_21.ids),
                            ],
                        }
                    ),
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item 1",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "product",
                    "name": "Partial item 2",
                    "balance": 240.0,
                    "tax_ids": [tax_21.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item 1",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item 2",
                    "balance": -120.0,
                    "tax_ids": [tax_21.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 145.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 28.95,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {"display_type": "tax", "name": "21%", "balance": 25.2, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -405.4,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_discounts(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "discount": 50,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 50.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -12.5,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 12.5,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 1.88,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 5.63, "tax_ids": []},
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -57.51,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_with_cash_rounding(self):
        cash_rounding = self.env["account.cash.rounding"].create(
            {
                "name": "Rounding 10",
                "rounding_method": "HALF-UP",
                "rounding": 10,
                "profit_account_id": self.cash_rounding_a.profit_account_id.id,
                "loss_account_id": self.cash_rounding_a.loss_account_id.id,
            }
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_cash_rounding_id": cash_rounding.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": 100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": -25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 3.75,
                    "tax_ids": [],
                },
                {"display_type": "tax", "name": "15%", "balance": 11.25, "tax_ids": []},
                {
                    "display_type": "rounding",
                    "name": "Rounding 10",
                    "balance": 5.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -120.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_simple_refund_partial_deductibility(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_refund",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "Partial item",
                    "balance": -100.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "Partial item",
                    "balance": 25.0,
                    "tax_ids": [self.tax_purchase_a.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": -25.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": -3.75,
                    "tax_ids": [],
                },
                {
                    "display_type": "tax",
                    "name": "15%",
                    "balance": -11.25,
                    "tax_ids": [],
                },
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": 115.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_non_deductible_tax_in_tax_totals(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2024-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        expected_values = {
            "same_tax_base": False,
            "currency_id": self.env.company.currency_id.id,
            "base_amount_currency": 100.0,
            "tax_amount_currency": 15.0,
            "total_amount_currency": 115.0,
            "subtotals": [
                {
                    "name": "Untaxed Amount",
                    "base_amount_currency": 100.0,
                    "tax_amount_currency": 15.0,
                    "tax_groups": [
                        {
                            "id": self.tax_purchase_a.tax_group_id.id,
                            "non_deductible_tax_amount": -3.75,
                            "non_deductible_tax_amount_currency": -3.75,
                            "base_amount_currency": 100.0,
                            "tax_amount_currency": 15.0,
                            "display_base_amount_currency": 75.0,
                        },
                    ],
                },
            ],
        }
        self._assert_tax_totals_summary(bill.tax_totals, expected_values)

    def test_refund_non_deductible_tax_in_tax_totals(self):
        refund = self.env["account.move"].create(
            {
                "move_type": "in_refund",
                "partner_id": self.partner_a.id,
                "invoice_date": "2024-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 75.00,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )

        expected_values = {
            "same_tax_base": False,
            "currency_id": self.env.company.currency_id.id,
            "base_amount_currency": 100.0,
            "tax_amount_currency": 15.0,
            "total_amount_currency": 115.0,
            "subtotals": [
                {
                    "name": "Untaxed Amount",
                    "base_amount_currency": 100.0,
                    "tax_amount_currency": 15.0,
                    "tax_groups": [
                        {
                            "id": self.tax_purchase_a.tax_group_id.id,
                            "non_deductible_tax_amount": -3.75,
                            "non_deductible_tax_amount_currency": -3.75,
                            "base_amount_currency": 100.0,
                            "tax_amount_currency": 15.0,
                            "display_base_amount_currency": 75.0,
                        },
                    ],
                },
            ],
        }
        self._assert_tax_totals_summary(refund.tax_totals, expected_values)

    def test_bill_partial_deductibility_with_reverse_charge(self):
        tax_reverse_charge = self.env["account.tax"].create(
            {
                "name": "Reverse Charge 20%",
                "amount_type": "percent",
                "amount": 20.0,
                "type_tax_use": "purchase",
                "invoice_repartition_line_ids": [
                    Command.create({"repartition_type": "base"}),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 100.0,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": -100.0,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                        }
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create({"repartition_type": "base"}),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 100.0,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                        }
                    ),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": -100.0,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                        }
                    ),
                ],
            }
        )

        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "RC Partial Item",
                            "price_unit": 100,
                            "quantity": 1,
                            "deductible_amount": 60.00,
                            "tax_ids": [Command.set(tax_reverse_charge.ids)],
                        }
                    )
                ],
            }
        )

        self.assertInvoiceValues(
            bill,
            [
                {
                    "display_type": "product",
                    "name": "RC Partial Item",
                    "balance": 100.0,
                    "tax_ids": [tax_reverse_charge.id],
                },
                {
                    "display_type": "non_deductible_product",
                    "name": "RC Partial Item",
                    "balance": -40.0,
                    "tax_ids": [tax_reverse_charge.id],
                },
                {
                    "display_type": "non_deductible_product_total",
                    "name": "private part",
                    "balance": 40.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "non_deductible_tax",
                    "name": "private part (taxes)",
                    "balance": 8.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "tax",
                    "name": "Reverse Charge 20%",
                    "balance": -20.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "tax",
                    "name": "Reverse Charge 20%",
                    "balance": 12.0,
                    "tax_ids": [],
                },
                {
                    "display_type": "payment_term",
                    "name": False,
                    "balance": -100.0,
                    "tax_ids": [],
                },
            ],
            {},
        )

    def test_bill_partial_deductibility_foreign_currency(self):
        """Check the non-deductible lines of a bill in a foreign currency."""
        # The non-deductible lines must carry the company-currency amount in
        # ``balance`` and the document-currency amount in ``amount_currency``; a swap
        # between the two is invisible at rate == 1, hence the foreign currency.
        foreign = self.env["res.currency"].create(
            {"name": "FDX", "symbol": "F", "rounding": 0.01}
        )
        # 1 company-currency unit == 2 FDX at the invoice date.
        self.env["res.currency.rate"].create(
            {
                "name": "2017-01-01",
                "rate": 2.0,
                "currency_id": foreign.id,
                "company_id": self.env.company.id,
            }
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2017-01-01",
                "currency_id": foreign.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Partial item",
                            "price_unit": 200.0,  # 200 FDX == 100 company
                            "quantity": 1,
                            "deductible_amount": 75.00,  # 25% non-deductible
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                ],
            }
        )
        self.assertEqual(bill.invoice_currency_rate, 2.0)

        # 25% of a 200-FDX / 100-company base == 50 FDX / 25 company.
        non_deductible = bill.line_ids.filtered(
            lambda line: line.display_type == "non_deductible_product"
        )
        non_deductible_total = bill.line_ids.filtered(
            lambda line: line.display_type == "non_deductible_product_total"
        )
        self.assertRecordValues(
            non_deductible, [{"balance": -25.0, "amount_currency": -50.0}]
        )
        self.assertRecordValues(
            non_deductible_total, [{"balance": 25.0, "amount_currency": 50.0}]
        )

    def _partial_bill(self, deductible_amounts):
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": f"Item {index}",
                            "price_unit": 100.0 * (index + 1),
                            "quantity": 1,
                            "deductible_amount": deductible,
                            "tax_ids": [Command.set(self.tax_purchase_a.ids)],
                        }
                    )
                    for index, deductible in enumerate(deductible_amounts)
                ],
            }
        )

    def _non_deductible_lines(self, move):
        return move.line_ids.filtered(
            lambda line: (
                line.display_type
                in ("non_deductible_product", "non_deductible_product_total")
            )
        )

    def test_non_deductible_lines_never_migrate_between_moves(self):
        """A batched write must not move lines from one bill onto another.

        The two bills need a different number of non-deductible lines, which is
        what used to make the delete/create lists line up across moves.
        """
        bill_a = self._partial_bill([80.0])
        bill_b = self._partial_bill([80.0, 60.0, 40.0])
        lines_of_b = set(self._non_deductible_lines(bill_b).ids)

        (bill_a | bill_b).write(
            {
                "invoice_line_ids": [
                    Command.update(
                        bill_a.invoice_line_ids[0].id, {"deductible_amount": 70.0}
                    ),
                    *[
                        Command.update(line.id, {"deductible_amount": 100.0})
                        for line in bill_b.invoice_line_ids
                    ],
                ]
            }
        )

        self.assertFalse(
            set(self._non_deductible_lines(bill_a).ids) & lines_of_b,
            "a non-deductible line of the second bill was rewritten onto the first one",
        )
        self.assertFalse(self._non_deductible_lines(bill_b))
        for bill in (bill_a, bill_b):
            self.assertEqual(
                bill.currency_id.round(sum(bill.line_ids.mapped("balance"))),
                0.0,
                "the bill must stay balanced",
            )

    def test_non_deductible_block_keeps_its_position_after_a_write(self):
        """The 'private part' lines must not drift below the payment-term line."""
        bill = self._partial_bill([75.0])
        payment_term = bill.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )

        bill.invoice_line_ids[0].quantity = 3

        for line in self._non_deductible_lines(bill) | bill.line_ids.filtered(
            lambda line: line.display_type == "non_deductible_tax"
        ):
            self.assertLess(
                line.sequence,
                payment_term.sequence,
                f"{line.display_type} sorted after the payment-term line",
            )

    def test_deductible_amount_locked_after_hashing(self):
        """`deductible_amount` must be rejected by the hash guard once posted, same as debit/credit."""
        # Starts fully deductible (100.0): posting creates no non_deductible_*
        # lines, which sidesteps a separate, pre-existing issue where _post()
        # renames those lines AFTER hashing and collides with the guard on
        # `name` itself (unrelated to this fix).
        self.company_data["default_journal_purchase"].restrict_mode_hash_table = True
        bill = self._partial_bill([100.0])
        bill.action_post()
        self.assertNotEqual(bill.inalterable_hash, False)

        product_line = bill.invoice_line_ids[0]
        with self.assertRaisesRegex(UserError, "cannot edit the following fields"):
            product_line.deductible_amount = 50.0
