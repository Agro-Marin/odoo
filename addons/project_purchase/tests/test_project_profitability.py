from datetime import datetime, timedelta

from odoo import Command
from odoo.libs.numbers import float_compare
from odoo.tests import tagged
from odoo.tools import float_round

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.project.tests.test_project_profitability import (
    TestProjectProfitabilityCommon,
)
from odoo.addons.purchase.tests.test_purchase_invoice import TestPurchaseToInvoiceCommon


@tagged("-at_install", "post_install")
class TestProjectPurchaseProfitability(
    TestProjectProfitabilityCommon,
    TestPurchaseToInvoiceCommon,
    AccountTestInvoicingCommon,
):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("purchase.group_purchase_user")
        cls.company_data_2 = cls.setup_other_company()

    def _create_invoice_for_po(self, purchase_order):
        purchase_order._create_invoices()
        purchase_bill = purchase_order.invoice_ids
        purchase_bill.invoice_date = datetime.today()
        purchase_bill.action_post()
        return purchase_bill

    def test_bills_without_purchase_order_are_accounted_in_profitability_project_purchase(
        self,
    ):
        analytic_distribution = 42
        analytic_contribution = analytic_distribution / 100.0
        price_precision = self.env["decimal.precision"].get_precision("Product Price")
        bill_1 = self.env["account.move"].create(
            {
                "name": "Bill_1 name",
                "move_type": "in_invoice",
                "state": "draft",
                "partner_id": self.partner.id,
                "invoice_date": datetime.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        self.env["account.analytic.line"].create(
            [
                {
                    "name": "extra costs 1",
                    "account_id": self.analytic_account.id,
                    "amount": -50.1,
                },
                {
                    "name": "extra costs 2",
                    "account_id": self.analytic_account.id,
                    "amount": -100,
                },
            ]
        )
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": -self.product_a.standard_price
                        * analytic_contribution,
                        "billed": 0.0,
                    },
                ],
                "total": {
                    "to_bill": -self.product_a.standard_price * analytic_contribution,
                    "billed": -150.1,
                },
            },
        )
        bill_1.action_post()
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": 0.0,
                        "billed": -self.product_a.standard_price
                        * analytic_contribution,
                    },
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -self.product_a.standard_price * analytic_contribution
                    - 150.1,
                },
            },
        )
        bill_2 = self.env["account.move"].create(
            {
                "name": "I have 2 lines",
                "move_type": "in_invoice",
                "state": "draft",
                "partner_id": self.partner.id,
                "invoice_date": datetime.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_distribution
                            },
                            "product_id": self.product_b.id,
                            "quantity": 2,
                            "product_uom_id": self.product_b.uom_id.id,
                            "price_unit": self.product_b.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_distribution
                            },
                            "product_id": self.service_deliver.id,
                            "quantity": 1,
                            "product_uom_id": self.service_deliver.uom_id.id,
                            "price_unit": -self.service_deliver.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                ],
            }
        )
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": -(
                            self.product_a.standard_price
                            + 2 * self.product_b.standard_price
                            - self.service_deliver.standard_price
                        )
                        * analytic_contribution,
                        "billed": -self.product_a.standard_price
                        * analytic_contribution,
                    },
                ],
                "total": {
                    "to_bill": -(
                        self.product_a.standard_price
                        + 2 * self.product_b.standard_price
                        - self.service_deliver.standard_price
                    )
                    * analytic_contribution,
                    "billed": -self.product_a.standard_price * analytic_contribution
                    - 150.1,
                },
            },
        )
        bill_2.action_post()
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": 0.0,
                        "billed": -(
                            2 * self.product_a.standard_price
                            + 2 * self.product_b.standard_price
                            - self.service_deliver.standard_price
                        )
                        * analytic_contribution,
                    },
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -(
                        2 * self.product_a.standard_price
                        + 2 * self.product_b.standard_price
                        - self.service_deliver.standard_price
                    )
                    * analytic_contribution
                    - 150.1,
                },
            },
        )
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_distribution
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()
        self.assertEqual(purchase_order.invoice_state, "to do")
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -self.product_order.standard_price
                        * analytic_contribution,
                        "billed": 0.0,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": 0.0,
                        "billed": -(
                            2 * self.product_a.standard_price
                            + 2 * self.product_b.standard_price
                            - self.service_deliver.standard_price
                        )
                        * analytic_contribution,
                    },
                ],
                "total": {
                    "to_bill": -self.product_order.standard_price
                    * analytic_contribution,
                    "billed": -(
                        2 * self.product_a.standard_price
                        + 2 * self.product_b.standard_price
                        - self.service_deliver.standard_price
                    )
                    * analytic_contribution
                    - 150.1,
                },
            },
        )
        purchase_order._create_invoices()
        self.assertEqual(purchase_order.invoice_ids.state, "draft")
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -self.product_order.standard_price
                        * analytic_contribution,
                        "billed": 0.0,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": 0.0,
                        "billed": -(
                            2 * self.product_a.standard_price
                            + 2 * self.product_b.standard_price
                            - self.service_deliver.standard_price
                        )
                        * analytic_contribution,
                    },
                ],
                "total": {
                    "to_bill": -self.product_order.standard_price
                    * analytic_contribution,
                    "billed": -(
                        2 * self.product_a.standard_price
                        + 2 * self.product_b.standard_price
                        - self.service_deliver.standard_price
                    )
                    * analytic_contribution
                    - 150.1,
                },
            },
        )
        purchase_bill = purchase_order.invoice_ids
        purchase_bill.invoice_date = datetime.today()
        purchase_bill.action_post()
        self.assertEqual(purchase_order.invoice_ids.state, "posted")
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "other_costs_aal",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_costs_aal"
                        ],
                        "to_bill": 0.0,
                        "billed": -150.1,
                    },
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": 0.0,
                        "billed": -self.product_order.standard_price
                        * analytic_contribution,
                    },
                    {
                        "id": "other_purchase_costs",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "other_purchase_costs"
                        ],
                        "to_bill": 0.0,
                        "billed": float_round(
                            -(
                                2 * self.product_a.standard_price
                                + 2 * self.product_b.standard_price
                                - self.service_deliver.standard_price
                            )
                            * analytic_contribution,
                            precision_digits=price_precision,
                        ),
                    },
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -(
                        2 * self.product_a.standard_price
                        + 2 * self.product_b.standard_price
                        - self.service_deliver.standard_price
                        + self.product_order.standard_price
                    )
                    * analytic_contribution
                    - 150.1,
                },
            },
        )

    def test_account_analytic_distribution_ratio(self):
        analytic_ratios = {
            "project_ratio": 60,
            "other_ratio": 40,
        }
        self.assertEqual(sum(ratio for ratio in analytic_ratios.values()), 100)
        other_analytic_account = self.env["account.analytic.account"].create(
            {
                "name": "Not important",
                "code": "KO-1234",
                "plan_id": self.analytic_plan.id,
            }
        )
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                self.analytic_account.id: analytic_ratios[
                                    "project_ratio"
                                ],
                                other_analytic_account.id: analytic_ratios[
                                    "other_ratio"
                                ],
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()
        self.assertEqual(purchase_order.invoice_state, "to do")
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -(
                            self.product_order.standard_price
                            * (analytic_ratios["project_ratio"] / 100)
                        ),
                        "billed": 0.0,
                    }
                ],
                "total": {
                    "to_bill": -(
                        self.product_order.standard_price
                        * (analytic_ratios["project_ratio"] / 100)
                    ),
                    "billed": 0.0,
                },
            },
            "No data should be found since the purchase order is not invoiced.",
        )

        self._create_invoice_for_po(purchase_order)
        self.assertEqual(purchase_order.invoice_state, "done")
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": 0.0,
                        "billed": -(
                            self.product_order.standard_price
                            * (analytic_ratios["project_ratio"] / 100)
                        ),
                    }
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -(
                        self.product_order.standard_price
                        * (analytic_ratios["project_ratio"] / 100)
                    ),
                },
            },
        )

    def test_multi_currency_for_project_purchase_profitability(self):
        project = self.env["project.project"].create({"name": "new project"})
        project._create_analytic_account()
        account = project.account_id
        foreign_company = self.company_data_2["company"]
        foreign_company.currency_id = self.foreign_currency

        analytic_distribution = 42
        analytic_contribution = analytic_distribution / 100.0
        bill_1 = self.env["account.move"].create(
            {
                "name": "Bill foreign currency",
                "move_type": "in_invoice",
                "state": "draft",
                "partner_id": self.partner.id,
                "invoice_date": datetime.today(),
                "date": datetime.today(),
                "invoice_date_due": datetime.today() - timedelta(days=1),
                "company_id": foreign_company.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.foreign_currency.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 2,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.foreign_currency.id,
                        }
                    ),
                ],
            }
        )
        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("other_purchase_costs", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][0]["sequence"],
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 0.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["data"][0]["billed"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 0.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["total"]["billed"])

        bill_2 = self.env["account.move"].create(
            {
                "name": "Bill main currency",
                "move_type": "in_invoice",
                "state": "draft",
                "partner_id": self.partner.id,
                "invoice_date": datetime.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_a.id,
                            "quantity": 2,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": self.product_a.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                ],
            }
        )

        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("other_purchase_costs", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][0]["sequence"],
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["data"][0]["billed"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["total"]["billed"])

        bill_2.action_post()
        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("other_purchase_costs", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][0]["sequence"],
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 0.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3,
                items["data"][0]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 0.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3,
                items["total"]["billed"],
                2,
            ),
            0,
        )

        bill_1.action_post()
        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("other_purchase_costs", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][0]["sequence"],
        )
        self.assertEqual(0.0, items["data"][0]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][0]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["total"]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["total"]["billed"],
                2,
            ),
            0,
        )

        purchase_order_foreign = self.env["purchase.order"].create(
            {
                "name": "A foreign purchase order",
                "partner_id": self.partner_a.id,
                "company_id": foreign_company.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.foreign_currency.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 2,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.foreign_currency.id,
                        }
                    ),
                ],
            }
        )
        purchase_order_foreign.action_confirm()
        self.assertEqual(purchase_order_foreign.invoice_state, "to do")

        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("purchase_order", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()["purchase_order"],
            items["data"][0]["sequence"],
        )
        self.assertEqual(0.0, items["data"][0]["billed"])
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 0.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual("other_purchase_costs", items["data"][1]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][1]["sequence"],
        )
        self.assertEqual(0.0, items["data"][1]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][1]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 0.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["total"]["billed"],
                2,
            ),
            0,
        )

        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A foreign purchase order",
                "partner_id": self.partner_a.id,
                "company_id": self.env.company.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                    Command.create(
                        {
                            "analytic_distribution": {
                                account.id: analytic_distribution
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 2,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                ],
            }
        )
        purchase_order.action_confirm()
        self.assertEqual(purchase_order.invoice_state, "to do")

        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("purchase_order", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()["purchase_order"],
            items["data"][0]["sequence"],
        )
        self.assertEqual(0.0, items["data"][0]["billed"])
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 3.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual("other_purchase_costs", items["data"][1]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][1]["sequence"],
        )
        self.assertEqual(0.0, items["data"][1]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][1]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 3.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["total"]["billed"],
                2,
            ),
            0,
        )

        self._create_invoice_for_po(purchase_order)
        self.assertEqual(purchase_order.invoice_state, "done")
        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("purchase_order", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()["purchase_order"],
            items["data"][0]["sequence"],
        )
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 0.6,
                items["data"][0]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 3,
                items["data"][0]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual("other_purchase_costs", items["data"][1]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][1]["sequence"],
        )
        self.assertEqual(0.0, items["data"][1]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][1]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 0.6,
                items["total"]["to_bill"],
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6
                - self.product_order.standard_price * analytic_contribution * 3,
                items["total"]["billed"],
                2,
            ),
            0,
        )

        self._create_invoice_for_po(purchase_order_foreign)
        self.assertEqual(purchase_order_foreign.invoice_state, "done")
        items = project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual("purchase_order", items["data"][0]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()["purchase_order"],
            items["data"][0]["sequence"],
        )
        self.assertEqual(0.0, items["data"][0]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_order.standard_price * analytic_contribution * 3.6,
                items["data"][0]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual("other_purchase_costs", items["data"][1]["id"])
        self.assertEqual(
            project._get_profitability_sequence_per_invoice_type()[
                "other_purchase_costs"
            ],
            items["data"][1]["sequence"],
        )
        self.assertEqual(0.0, items["data"][1]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6,
                items["data"][1]["billed"],
                2,
            ),
            0,
        )
        self.assertEqual(0.0, items["total"]["to_bill"])
        self.assertEqual(
            float_compare(
                -self.product_a.standard_price * analytic_contribution * 3.6
                - self.product_order.standard_price * analytic_contribution * 3.6,
                items["total"]["billed"],
                2,
            ),
            0,
        )

    def test_project_purchase_order_smart_button(self):
        project = self.env["project.project"].create({"name": "Test Project"})

        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "company_id": self.env.company.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.foreign_currency.id,
                        }
                    )
                ],
                "project_id": project.id,
            }
        )

        action = project.action_view_project_purchase_orders()
        self.assertTrue(action)
        self.assertEqual(action["res_id"], purchase_order.id)

    def test_analytic_distribution_with_included_tax(self):
        included_tax = self.env["account.tax"].create(
            {
                "name": "included tax",
                "amount": "15.0",
                "amount_type": "percent",
                "type_tax_use": "purchase",
                "price_include_override": "tax_included",
            }
        )

        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {self.analytic_account.id: 100},
                            "product_id": self.product_order.id,
                            "product_qty": 2,
                            "tax_ids": [included_tax.id],
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()
        purchase_order._create_invoices()
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -(purchase_order.amount_untaxed),
                        "billed": 0.0,
                    }
                ],
                "total": {
                    "to_bill": -(purchase_order.amount_untaxed),
                    "billed": 0.0,
                },
            },
        )

        purchase_bill = purchase_order.invoice_ids
        purchase_bill.invoice_date = datetime.today()
        purchase_bill.action_post()
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": 0.0,
                        "billed": -(purchase_bill.amount_untaxed),
                    }
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -(purchase_bill.amount_untaxed),
                },
            },
        )

    def test_analytic_distribution_with_mismatched_uom(self):
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {self.analytic_account.id: 100},
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()
        purchase_order.line_ids.product_uom_id = self.env.ref("uom.product_uom_dozen")
        purchase_order._create_invoices()
        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -(purchase_order.amount_untaxed),
                        "billed": 0.0,
                    }
                ],
                "total": {
                    "to_bill": -(purchase_order.amount_untaxed),
                    "billed": 0.0,
                },
            },
        )

    def test_cross_analytics_contribution(self):
        cross_plan = self.env["account.analytic.plan"].create({"name": "Cross Plan"})
        cross_account = self.env["account.analytic.account"].create(
            {
                "name": "Cross Analytic Account",
                "plan_id": cross_plan.id,
                "company_id": self.env.company.id,
            }
        )
        cross_distribution = 42

        cross_order = self.env["purchase.order"].create(
            {
                "name": "Cross Purchase Order",
                "partner_id": self.partner_a.id,
                "company_id": self.env.company.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                f"{self.project.account_id.id},{cross_account.id}": cross_distribution,
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    ),
                ],
            }
        )

        cross_order.action_confirm()
        cross_order._create_invoices()
        items = self.project._get_profitability_items(with_action=False)["costs"]
        self.assertEqual(
            items["data"][0]["to_bill"],
            -(self.product_order.standard_price * cross_distribution / 100),
        )

    def test_vendor_credit_note_profitability(self):
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A Purchase",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {self.analytic_account.id: 100},
                            "product_id": self.product_order.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()
        vendor_bill = self._create_invoice_for_po(purchase_order)

        items = self.project._get_profitability_items(with_action=False)["costs"]
        self.assertDictEqual(
            items["total"],
            {
                "billed": -purchase_order.amount_untaxed,
                "to_bill": 0.0,
            },
        )

        credit_note = vendor_bill._reverse_moves()
        items = self.project._get_profitability_items(with_action=False)["costs"]
        self.assertDictEqual(
            items["total"],
            {
                "billed": -purchase_order.amount_untaxed,
                "to_bill": purchase_order.amount_untaxed,
            },
        )

        credit_note.invoice_date = vendor_bill.invoice_date
        credit_note.action_post()
        items = self.project._get_profitability_items(with_action=False)["costs"]
        self.assertDictEqual(
            items["total"],
            {
                "billed": 0.0,
                "to_bill": 0.0,
            },
        )

    def test_project_purchase_profitability_without_analytic_distribution(self):
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {self.analytic_account.id: 100},
                            "product_id": self.product_order.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()

        vendor_bill = self._create_invoice_for_po(purchase_order)
        vendor_bill.invoice_line_ids.analytic_distribution = False

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -235.0,
                        "billed": 0.0,
                    }
                ],
                "total": {
                    "to_bill": -235.0,
                    "billed": 0.0,
                },
            },
        )

    def test_profitability_foreign_currency_rate_on_bill_date(self):
        CurrencyRate = self.env["res.currency.rate"]
        company = self.env.company

        foreign_currency = self.env["res.currency"].search(
            [("id", "!=", company.currency_id.id)], limit=1
        )
        if not foreign_currency:
            foreign_currency = self.env["res.currency"].create(
                {"name": "USD", "symbol": "$", "rounding": 0.01, "decimal_places": 2}
            )

        today = datetime.today().date()
        yesterday = today - timedelta(days=1)
        rate_today = 1.9
        rate_yesterday = 2.0
        CurrencyRate.create(
            {
                "currency_id": foreign_currency.id,
                "rate": rate_yesterday,
                "name": yesterday,
                "company_id": company.id,
            }
        )
        CurrencyRate.create(
            {
                "currency_id": foreign_currency.id,
                "rate": rate_today,
                "name": today,
                "company_id": company.id,
            }
        )

        price_unit = 150
        bill = self.env["account.move"].create(
            {
                "name": "Bill Foreign Currency",
                "move_type": "in_invoice",
                "state": "draft",
                "partner_id": self.partner.id,
                "invoice_date": yesterday,
                "currency_id": foreign_currency.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {self.analytic_account.id: 100},
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "product_uom_id": self.product_a.uom_id.id,
                            "price_unit": price_unit,
                        }
                    )
                ],
            }
        )

        expected_cost = -(price_unit / rate_yesterday)

        costs = self.project._get_profitability_items(False)["costs"]
        self.assertEqual(len(costs["data"]), 1)
        actual_to_bill = costs["data"][0]["to_bill"]
        self.assertTrue(
            float_compare(actual_to_bill, expected_cost, precision_digits=2) == 0,
            f"Expected to_bill {expected_cost}, got {actual_to_bill}",
        )

        bill.action_post()
        costs = self.project._get_profitability_items(False)["costs"]
        actual_billed = costs["data"][0]["billed"]
        self.assertTrue(
            float_compare(actual_billed, expected_cost, precision_digits=2) == 0,
            f"Expected billed {expected_cost}, got {actual_billed}",
        )

    def test_project_purchase_profitability_with_split_bills(self):

        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "company_id": self.env.company.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_order.id,
                            "price_unit": 100,
                            "tax_ids": [],
                            "product_qty": 5.0,
                        }
                    )
                ],
                "project_id": self.project.id,
            }
        )
        purchase_order.action_confirm()

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -500.0,
                        "billed": 0.0,
                    }
                ],
                "total": {
                    "to_bill": -500.0,
                    "billed": 0.0,
                },
            },
        )

        purchase_order._create_invoices()
        vendor_bill = purchase_order.invoice_ids
        vendor_bill.invoice_date = datetime.today()
        vendor_bill.invoice_line_ids.quantity = 2.0
        vendor_bill.action_post()

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -300.0,
                        "billed": -200.0,
                    }
                ],
                "total": {
                    "to_bill": -300.0,
                    "billed": -200.0,
                },
            },
        )

        purchase_order._create_invoices()
        vendor_bill_2 = purchase_order.invoice_ids[1]
        vendor_bill_2.invoice_date = datetime.today()
        vendor_bill_2.invoice_line_ids.quantity = 3.0
        vendor_bill_2.invoice_line_ids.analytic_distribution = {}
        vendor_bill_2.action_post()

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": -300.0,
                        "billed": -200.0,
                    }
                ],
                "total": {
                    "to_bill": -300.0,
                    "billed": -200.0,
                },
            },
        )

        purchase_order._create_invoices()
        vendor_bill_3 = purchase_order.invoice_ids[2]
        vendor_bill_3.invoice_date = datetime.today()
        vendor_bill_3.invoice_line_ids.quantity = 3.0
        vendor_bill_3.action_post()

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": 0.0,
                        "billed": -500.0,
                    }
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -500.0,
                },
            },
        )

    def test_project_profitability_when_multiple_aa_in_the_same_line(self):
        other_analytic_account = self.env["account.analytic.account"].create(
            {
                "name": "Not important",
                "code": "KO-1234",
                "plan_id": self.analytic_plan.id,
            }
        )
        purchase_order = self.env["purchase.order"].create(
            {
                "name": "A purchase order",
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "analytic_distribution": {
                                f"{self.analytic_account.id},{other_analytic_account.id}": 100,
                            },
                            "product_id": self.product_order.id,
                            "product_qty": 1,
                            "price_unit": self.product_order.standard_price,
                            "currency_id": self.env.company.currency_id.id,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()

        purchase_order._create_invoices()

        vendor_bill = purchase_order.invoice_ids[0]
        vendor_bill.invoice_date = datetime.today()
        vendor_bill.action_post()

        self.assertDictEqual(
            self.project._get_profitability_items(False)["costs"],
            {
                "data": [
                    {
                        "id": "purchase_order",
                        "sequence": self.project._get_profitability_sequence_per_invoice_type()[
                            "purchase_order"
                        ],
                        "to_bill": 0.0,
                        "billed": -235.0,
                    }
                ],
                "total": {
                    "to_bill": 0.0,
                    "billed": -235.0,
                },
            },
        )
