from unittest import skip

import odoo
from odoo import tools

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPoSOtherCurrencyConfig(TestPoSCommon):

    def setUp(self):
        super().setUp()

        self.config = self.other_currency_config
        self.product1 = self.create_product("Product 1", self.categ_basic, 10.0, 5)
        self.product2 = self.create_product("Product 2", self.categ_basic, 20.0, 10)
        self.product3 = self.create_product("Product 3", self.categ_basic, 30.0, 15)
        self.product4 = self.create_product("Product 4", self.categ_anglo, 100, 50)
        self.product5 = self.create_product("Product 5", self.categ_anglo, 200, 70)
        self.product6 = self.create_product("Product 6", self.categ_anglo, 45.3, 10.73)
        self.product7 = self.create_product(
            "Product 7", self.categ_basic, 7, 7, tax_ids=self.taxes["tax7"].ids
        )
        self.adjust_inventory(
            [
                self.product1,
                self.product2,
                self.product3,
                self.product4,
                self.product5,
                self.product6,
                self.product7,
            ],
            [100, 50, 50, 100, 100, 100, 100],
        )
        pricelist_item = self.env["product.pricelist.item"].create(
            {
                "product_tmpl_id": self.product2.product_tmpl_id.id,
                "fixed_price": 12.99,
            }
        )
        self.config.pricelist_id.write(
            {
                "item_ids": [
                    (6, 0, (self.config.pricelist_id.item_ids | pricelist_item).ids)
                ]
            }
        )

        self.expense_account = self.categ_anglo.property_account_expense_categ_id

    def test_01_check_product_cost(self):

        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product1, 1), 5.00
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product2, 1), 12.99
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product3, 1), 15.00
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product4, 1), 50
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product5, 1), 100
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product6, 1), 22.65
        )
        self.assertAlmostEqual(
            self.config.pricelist_id._get_product_price(self.product7, 1), 3.50
        )

    def test_02_orders_without_invoice(self):

        def _before_closing_cb():
            self.assertEqual(3, self.pos_session.order_count)
            orders_total = sum(
                order.amount_total for order in self.pos_session.order_ids
            )
            self.assertAlmostEqual(
                orders_total,
                self.pos_session.total_payments_amount,
                msg="Total order amount should be equal to the total payment amount.",
            )

        self._run_test(
            {
                "payment_methods": self.cash_pm2 | self.bank_pm2,
                "orders": [
                    {
                        "pos_order_lines_ui_args": [
                            (self.product1, 10),
                            (self.product2, 10),
                            (self.product3, 10),
                        ],
                        "uuid": "00100-010-0001",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product1, 5),
                            (self.product2, 5),
                        ],
                        "uuid": "00100-010-0002",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product2, 5),
                            (self.product3, 5),
                        ],
                        "payments": [(self.bank_pm2, 139.95)],
                        "uuid": "00100-010-0003",
                    },
                ],
                "before_closing_cb": _before_closing_cb,
                "journal_entries_before_closing": {},
                "journal_entries_after_closing": {
                    "session_journal_entry": {
                        "line_ids": [
                            {
                                "account_id": self.sales_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 1119.6,
                                "reconciled": False,
                                "amount_currency": -559.80,
                            },
                            {
                                "account_id": self.bank_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 279.9,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 139.95,
                            },
                            {
                                "account_id": self.cash_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 839.7,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 419.85,
                            },
                        ],
                    },
                    "cash_statement": [
                        (
                            (419.85,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.cash_pm2.journal_id.default_account_id.id,
                                        "partner_id": False,
                                        "debit": 839.7,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 419.85,
                                    },
                                    {
                                        "account_id": self.cash_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 839.7,
                                        "reconciled": True,
                                        "amount_currency": -419.85,
                                    },
                                ]
                            },
                        ),
                    ],
                    "bank_payments": [
                        (
                            (139.95,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.bank_pm2.outstanding_account_id.id,
                                        "partner_id": False,
                                        "debit": 279.9,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 139.95,
                                    },
                                    {
                                        "account_id": self.bank_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 279.9,
                                        "reconciled": True,
                                        "amount_currency": -139.95,
                                    },
                                ]
                            },
                        ),
                    ],
                },
            }
        )

    def test_03_orders_with_invoice(self):

        def _before_closing_cb():
            self.assertEqual(3, self.pos_session.order_count)
            orders_total = sum(
                order.amount_total for order in self.pos_session.order_ids
            )
            self.assertAlmostEqual(
                orders_total,
                self.pos_session.total_payments_amount,
                msg="Total order amount should be equal to the total payment amount.",
            )

        self._run_test(
            {
                "payment_methods": self.cash_pm2 | self.bank_pm2,
                "orders": [
                    {
                        "pos_order_lines_ui_args": [
                            (self.product1, 10),
                            (self.product2, 10),
                            (self.product3, 10),
                        ],
                        "uuid": "00100-010-0001",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product1, 5),
                            (self.product2, 5),
                        ],
                        "is_invoiced": True,
                        "customer": self.customer,
                        "uuid": "00100-010-0002",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product2, 5),
                            (self.product3, 5),
                        ],
                        "payments": [(self.bank_pm2, 139.95)],
                        "is_invoiced": True,
                        "customer": self.customer,
                        "uuid": "00100-010-0003",
                    },
                ],
                "before_closing_cb": _before_closing_cb,
                "journal_entries_before_closing": {
                    "00100-010-0002": {
                        "payments": [
                            (
                                (self.cash_pm2, 89.95),
                                {
                                    "line_ids": [
                                        {
                                            "account_id": self.c1_receivable.id,
                                            "partner_id": self.customer.id,
                                            "debit": 0,
                                            "credit": 179.90,
                                            "reconciled": True,
                                            "amount_currency": -89.95,
                                        },
                                        {
                                            "account_id": self.pos_receivable_account.id,
                                            "partner_id": False,
                                            "debit": 179.90,
                                            "credit": 0,
                                            "reconciled": False,
                                            "amount_currency": 89.95,
                                        },
                                    ]
                                },
                            ),
                        ],
                    },
                    "00100-010-0003": {
                        "payments": [
                            (
                                (self.bank_pm2, 139.95),
                                {
                                    "line_ids": [
                                        {
                                            "account_id": self.c1_receivable.id,
                                            "partner_id": self.customer.id,
                                            "debit": 0,
                                            "credit": 279.9,
                                            "reconciled": True,
                                            "amount_currency": -139.95,
                                        },
                                        {
                                            "account_id": self.pos_receivable_account.id,
                                            "partner_id": False,
                                            "debit": 279.9,
                                            "credit": 0,
                                            "reconciled": False,
                                            "amount_currency": 139.95,
                                        },
                                    ]
                                },
                            ),
                        ],
                    },
                },
                "journal_entries_after_closing": {
                    "session_journal_entry": {
                        "line_ids": [
                            {
                                "account_id": self.sales_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 659.8,
                                "reconciled": False,
                                "amount_currency": -329.90,
                            },
                            {
                                "account_id": self.bank_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 279.9,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 139.95,
                            },
                            {
                                "account_id": self.cash_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 839.7,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 419.85,
                            },
                            {
                                "account_id": self.pos_receivable_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 179.90,
                                "reconciled": True,
                                "amount_currency": -89.95,
                            },
                            {
                                "account_id": self.pos_receivable_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 279.9,
                                "reconciled": True,
                                "amount_currency": -139.95,
                            },
                        ],
                    },
                    "cash_statement": [
                        (
                            (419.85,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.cash_pm2.journal_id.default_account_id.id,
                                        "partner_id": False,
                                        "debit": 839.7,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 419.85,
                                    },
                                    {
                                        "account_id": self.cash_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 839.7,
                                        "reconciled": True,
                                        "amount_currency": -419.85,
                                    },
                                ]
                            },
                        ),
                    ],
                    "bank_payments": [
                        (
                            (139.95,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.bank_pm2.outstanding_account_id.id,
                                        "partner_id": False,
                                        "debit": 279.9,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 139.95,
                                    },
                                    {
                                        "account_id": self.bank_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 279.9,
                                        "reconciled": True,
                                        "amount_currency": -139.95,
                                    },
                                ]
                            },
                        ),
                    ],
                },
            }
        )

    @skip("Temporary to fast merge new valuation")
    def test_04_anglo_saxon_products(self):

        self._run_test(
            {
                "payment_methods": self.cash_pm2,
                "orders": [
                    {
                        "pos_order_lines_ui_args": [
                            (self.product4, 7),
                            (self.product5, 7),
                        ],
                        "uuid": "00100-010-0001",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product5, 6),
                            (self.product4, 6),
                            (self.product6, 49),
                        ],
                        "uuid": "00100-010-0002",
                    },
                    {
                        "pos_order_lines_ui_args": [
                            (self.product5, 2),
                            (self.product6, 13),
                        ],
                        "uuid": "00100-010-0003",
                    },
                    {
                        "pos_order_lines_ui_args": [(self.product6, 1)],
                        "uuid": "00100-010-0004",
                    },
                ],
                "journal_entries_before_closing": {},
                "journal_entries_after_closing": {
                    "session_journal_entry": {
                        "line_ids": [
                            {
                                "account_id": self.sales_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 7153.90,
                                "reconciled": False,
                                "amount_currency": -3576.95,
                            },
                            {
                                "account_id": self.expense_account.id,
                                "partner_id": False,
                                "debit": 2375.99,
                                "credit": 0,
                                "reconciled": False,
                                "amount_currency": 2375.99,
                            },
                            {
                                "account_id": self.cash_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 7153.90,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 3576.95,
                            },
                            {
                                "account_id": self.output_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 2375.99,
                                "reconciled": True,
                                "amount_currency": -2375.99,
                            },
                        ],
                    },
                    "cash_statement": [
                        (
                            (3576.95,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.cash_pm2.journal_id.default_account_id.id,
                                        "partner_id": False,
                                        "debit": 7153.90,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 3576.95,
                                    },
                                    {
                                        "account_id": self.cash_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 7153.90,
                                        "reconciled": True,
                                        "amount_currency": -3576.95,
                                    },
                                ]
                            },
                        ),
                    ],
                    "bank_payments": [],
                },
            }
        )

    def test_05_tax_base_amount(self):
        self._run_test(
            {
                "payment_methods": self.cash_pm2,
                "orders": [
                    {
                        "pos_order_lines_ui_args": [(self.product7, 7)],
                        "uuid": "00100-010-0001",
                    },
                ],
                "journal_entries_before_closing": {},
                "journal_entries_after_closing": {
                    "session_journal_entry": {
                        "line_ids": [
                            {
                                "account_id": self.tax_received_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 3.43,
                                "reconciled": False,
                                "amount_currency": -1.715,
                                "tax_base_amount": 49,
                            },
                            {
                                "account_id": self.sales_account.id,
                                "partner_id": False,
                                "debit": 0,
                                "credit": 49,
                                "reconciled": False,
                                "amount_currency": -24.5,
                                "tax_base_amount": 0,
                            },
                            {
                                "account_id": self.cash_pm2.receivable_account_id.id,
                                "partner_id": False,
                                "debit": 52.43,
                                "credit": 0,
                                "reconciled": True,
                                "amount_currency": 26.215,
                                "tax_base_amount": 0,
                            },
                        ],
                    },
                    "cash_statement": [
                        (
                            (26.215,),
                            {
                                "line_ids": [
                                    {
                                        "account_id": self.cash_pm2.journal_id.default_account_id.id,
                                        "partner_id": False,
                                        "debit": 52.43,
                                        "credit": 0,
                                        "reconciled": False,
                                        "amount_currency": 26.215,
                                    },
                                    {
                                        "account_id": self.cash_pm2.receivable_account_id.id,
                                        "partner_id": False,
                                        "debit": 0,
                                        "credit": 52.43,
                                        "reconciled": True,
                                        "amount_currency": -26.215,
                                    },
                                ]
                            },
                        ),
                    ],
                    "bank_payments": [],
                },
            }
        )

    def test_bank_journal_balance(self):

        self.other_currency_config.open_ui()
        session_id = self.other_currency_config.current_session_id
        order = self.env["pos.order"].create(
            {
                "company_id": self.env.company.id,
                "session_id": session_id.id,
                "partner_id": False,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/0001",
                            "product_id": self.product1.id,
                            "price_unit": 10.00,
                            "discount": 0,
                            "qty": 1,
                            "tax_ids": False,
                            "price_subtotal": 10.00,
                            "price_subtotal_incl": 10.00,
                        },
                    )
                ],
                "pricelist_id": self.other_currency_config.pricelist_id.id,
                "amount_paid": 10.00,
                "amount_total": 10.00,
                "amount_tax": 0.0,
                "amount_return": 0.0,
                "to_invoice": False,
            }
        )

        payment_context = {"active_ids": order.ids, "active_id": order.id}
        order_payment = (
            self.env["pos.make.payment"]
            .with_context(**payment_context)
            .create(
                {"amount": order.amount_total, "payment_method_id": self.bank_pm2.id}
            )
        )
        order_payment.with_context(**payment_context).check()

        session_id.action_pos_session_closing_control(
            bank_payment_method_diffs={self.bank_pm2.id: 10.00}
        )

        for move in session_id._get_related_account_moves():
            debit = credit = 0.0
            for line in move.line_ids:
                debit += line.debit
                credit += line.credit
            self.assertEqual(
                tools.float_compare(
                    debit,
                    credit,
                    precision_rounding=self.other_currency_config.currency_id.rounding,
                ),
                0,
            )

    def test_with_session_check_product_cost(self):
        def find_by(list_of_dicts, key, value):
            return next((d for d in list_of_dicts if d.get(key) == value), None)

        self.other_currency_config.open_ui()
        product = self.other_currency_config.current_session_id.load_data([])[
            "product.product"
        ]

        self.assertAlmostEqual(
            find_by(product, "id", self.product1.id)["lst_price"], 5.00
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product2.id)["lst_price"], 10.00
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product3.id)["lst_price"], 15.00
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product4.id)["lst_price"], 50.00
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product5.id)["lst_price"], 100.00
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product6.id)["lst_price"], 22.65
        )
        self.assertAlmostEqual(
            find_by(product, "id", self.product7.id)["lst_price"], 3.50
        )

    def test_pos_data_standard_price_converted(self):
        self.other_currency_config.open_ui()
        res = self.other_currency_config.current_session_id.load_data({})
        product1_data = next(
            filter(
                lambda product: product["display_name"] == "Product 1",
                res["product.product"],
            )
        )
        self.assertEqual(
            product1_data["standard_price"], 2.5
        )
