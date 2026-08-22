from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountInvoiceReport(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_currency = cls.setup_other_currency("EUR")
        cls.company_data_2 = cls.setup_other_company()
        pack_of_six = cls.env["uom.uom"].search([("name", "=", "Pack of 6")])
        cls.invoices = cls.env["account.move"].create(
            [
                {
                    "move_type": "out_invoice",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2016-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 3,
                                "price_unit": 4500,
                                "product_uom_id": pack_of_six.id,
                            }
                        ),
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 3000,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "out_receipt",
                    "invoice_date": fields.Date.from_string("2016-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 6000,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "out_refund",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2017-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 1200,
                            }
                        ),
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 3,
                                "price_unit": 4500,
                                "product_uom_id": pack_of_six.id,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "in_invoice",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2016-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 60,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "in_receipt",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2016-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 60,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "in_refund",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2017-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 12,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "out_refund",
                    "partner_id": cls.partner_a.id,
                    "invoice_date": fields.Date.from_string("2017-01-01"),
                    "currency_id": cls.other_currency.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": cls.product_a.id,
                                "quantity": 1,
                                "price_unit": 2400,
                            }
                        ),
                    ],
                },
            ]
        )

    def assertInvoiceReportValues(self, expected_values_list):
        reports = self.env["account.invoice.report"].search(
            [("company_id", "=", self.company_data["company"].id)],
            order="price_subtotal DESC, quantity ASC",
        )
        expected_values_dict = [
            {
                "price_average": vals[0],
                "price_subtotal": vals[1],
                "quantity": vals[2],
                "price_margin": vals[3],
                "inventory_value": vals[4],
            }
            for vals in expected_values_list
        ]

        self.assertRecordValues(reports, expected_values_dict)

    def test_invoice_report_multiple_types(self):
        self.assertInvoiceReportValues(
            [
                [
                    250,
                    4500,
                    18,
                    -9900,
                    -14400,
                ],
                [2000, 2000, 1, 1200, -800],
                [1000, 1000, 1, 200, -800],
                [6, 6, 1, 0, -800],
                [20, -20, -1, 0, 800],
                [20, -20, -1, 0, 800],
                [600, -600, -1, 200, 800],
                [1200, -1200, -1, -400, 800],
                [
                    375,
                    -6750,
                    -18,
                    7650,
                    14400,
                ],
            ]
        )

    def test_invoice_report_multicompany_product_cost(self):
        self.product_a.with_company(self.company_data_2.get("company")).write(
            {"standard_price": 700.0}
        )
        self.assertInvoiceReportValues(
            [
                [
                    250,
                    4500,
                    18,
                    -9900,
                    -14400,
                ],
                [2000, 2000, 1, 1200, -800],
                [1000, 1000, 1, 200, -800],
                [6, 6, 1, 0, -800],
                [20, -20, -1, 0, 800],
                [20, -20, -1, 0, 800],
                [600, -600, -1, 200, 800],
                [1200, -1200, -1, -400, 800],
                [
                    375,
                    -6750,
                    -18,
                    7650,
                    14400,
                ],
            ]
        )

    def test_avg_price_calculation(self):
        product = self.product_a.copy()
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.from_string("2016-01-01"),
                "currency_id": self.env.company.currency_id.id,
                "invoice_line_ids": [
                    (
                        0,
                        None,
                        {
                            "product_id": product.id,
                            "quantity": 10,
                            "price_unit": 10,
                        },
                    ),
                    (
                        0,
                        None,
                        {
                            "product_id": product.id,
                            "quantity": 5,
                            "price_unit": 5,
                        },
                    ),
                    (
                        0,
                        None,
                        {
                            "product_id": product.id,
                            "quantity": 20,
                            "price_unit": 2,
                        },
                    ),
                ],
            }
        )
        invoice.action_post()
        self.env.flush_all()

        report = self.env["account.invoice.report"].formatted_read_group(
            [("product_id", "=", product.id)],
            [],
            ["price_subtotal:sum", "quantity:sum", "price_average:avg"],
        )
        self.assertEqual(report[0]["quantity:sum"], 35)
        self.assertEqual(report[0]["price_subtotal:sum"], 165)
        self.assertEqual(round(report[0]["price_average:avg"], 2), 4.71)

        report = self.env["account.invoice.report"].formatted_read_group(
            [("product_id", "=", product.id)],
            [],
            ["price_average:avg"],
        )
        self.assertEqual(round(report[0]["price_average:avg"], 2), 4.71)

    def test_avg_price_group_by_month(self):
        self.env["account.move"].search([]).unlink()
        invoices = self.env["account.move"].create(
            [
                {
                    "move_type": "out_invoice",
                    "partner_id": self.partner_a.id,
                    "invoice_date": fields.Date.from_string("2025-01-01"),
                    "currency_id": self.env.company.currency_id.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": self.product_a.id,
                                "quantity": 10,
                                "price_unit": 10,
                            }
                        ),
                        Command.create(
                            {
                                "product_id": self.product_a.id,
                                "quantity": 5,
                                "price_unit": 5,
                            }
                        ),
                    ],
                },
                {
                    "move_type": "out_invoice",
                    "partner_id": self.partner_a.id,
                    "invoice_date": fields.Date.from_string("2025-02-01"),
                    "currency_id": self.env.company.currency_id.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "product_id": self.product_a.id,
                                "quantity": 0,
                                "price_unit": 5,
                            }
                        ),
                    ],
                },
            ]
        )
        invoices.action_post()

        report = self.env["account.invoice.report"].formatted_read_group(
            [("product_id", "=", self.product_a.id)],
            ["invoice_date:month"],
            ["__count", "price_subtotal:sum", "quantity:sum", "price_average:avg"],
        )

        self.assertEqual(report[0]["__count"], 2)
        self.assertEqual(report[0]["quantity:sum"], 15.0)
        self.assertEqual(report[0]["price_subtotal:sum"], 125.0)
        self.assertEqual(round(report[0]["price_average:avg"], 2), 8.33)

        self.assertEqual(report[1]["__count"], 1)
        self.assertEqual(report[1]["quantity:sum"], 0.0)
        self.assertEqual(report[1]["price_subtotal:sum"], 0.0)
        self.assertEqual(report[1]["price_average:avg"], 0.00)

    def test_inventory_margin_currency(self):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "price_unit": 750,
                        }
                    ),
                ],
            }
        )
        egy_company = self.env["res.company"].create(
            {
                "name": "Egyptian Company",
                "currency_id": self.env.ref("base.EGP").id,
                "user_ids": [Command.set(self.env.user.ids)],
            }
        )
        orig_company = self.env.company
        report = self.env["account.invoice.report"].search(
            [("move_id", "=", invoice.id)],
        )
        self.assertEqual(report.inventory_value, -800)
        self.assertEqual(report.price_margin, -50)
        self.env.user.company_id = egy_company
        self.env["res.currency.rate"].create(
            {
                "name": "2017-11-03",
                "rate": 0.5,
                "currency_id": orig_company.currency_id.id,
            }
        )
        self.env.flush_all()
        self.env["account.invoice.report"].invalidate_model()
        report = self.env["account.invoice.report"].search(
            [("move_id", "=", invoice.id)],
        )
        self.assertEqual(report.inventory_value, -1600)
        self.assertEqual(report.price_margin, -100)
