from odoo import fields
from odoo.fields import Command
from odoo.libs.numbers import float_compare
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("-at_install", "post_install")
class TestSaleReportCurrencyRate(SaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.usd_cmp = cls.env["res.company"].create(
            {
                "name": "USD Company",
                "currency_id": cls.env.ref("base.USD").id,
            }
        )
        cls.eur_cmp = cls.env["res.company"].create(
            {
                "name": "EUR Company",
                "currency_id": cls.env.ref("base.EUR").id,
            }
        )

    def test_sale_report_foreign_currency(self):
        companies = self.usd_cmp + self.eur_cmp
        today = fields.Date.today()
        past_day = fields.Date.to_date("2020-01-01")
        usd = self.usd_cmp.currency_id
        eur = self.eur_cmp.currency_id
        ars = self._enable_currency("ARS")

        pricelists = self.env["product.pricelist"].create(
            [
                {"name": "Pricelist (USD)", "currency_id": usd.id, "company_id": False},
                {"name": "Pricelist (EUR)", "currency_id": eur.id, "company_id": False},
                {"name": "Pricelist (ARS)", "currency_id": ars.id, "company_id": False},
            ]
        )
        self.env["res.currency.rate"].create(
            [
                {
                    "name": past_day,
                    "rate": 555,
                    "currency_id": ars.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": past_day,
                    "rate": 1.0,
                    "currency_id": eur.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": past_day,
                    "rate": 999,
                    "currency_id": usd.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": past_day,
                    "rate": 3.0,
                    "currency_id": ars.id,
                    "company_id": self.usd_cmp.id,
                },
                {
                    "name": past_day,
                    "rate": 0.1,
                    "currency_id": eur.id,
                    "company_id": self.usd_cmp.id,
                },
                {
                    "name": past_day,
                    "rate": 1.0,
                    "currency_id": usd.id,
                    "company_id": self.usd_cmp.id,
                },
                {
                    "name": today,
                    "rate": 222,
                    "currency_id": ars.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": today,
                    "rate": 1.0,
                    "currency_id": eur.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": today,
                    "rate": 2.9,
                    "currency_id": usd.id,
                    "company_id": self.eur_cmp.id,
                },
                {
                    "name": today,
                    "rate": 101,
                    "currency_id": ars.id,
                    "company_id": self.usd_cmp.id,
                },
                {
                    "name": today,
                    "rate": 0.6,
                    "currency_id": eur.id,
                    "company_id": self.usd_cmp.id,
                },
                {
                    "name": today,
                    "rate": 1.0,
                    "currency_id": usd.id,
                    "company_id": self.usd_cmp.id,
                },
            ]
        )

        self.assertEqual(self.product.currency_id, usd)

        currency_rates = (
            (companies + self.env.company)
            .mapped("currency_id")
            ._get_rates(self.env.company, today)
        )

        sale_orders = self.env["sale.order"]
        expected_reported_amount = (
            0
        )
        qty = 0

        for company in companies:
            SaleOrder = self.env["sale.order"].with_company(company)
            for date in (past_day, today):
                for pricelist in pricelists:
                    qty += 1
                    order = SaleOrder.create(
                        {
                            "partner_id": self.partner.id,
                            "pricelist_id": pricelist.id,
                            "date_order": date,
                            "line_ids": [
                                Command.create(
                                    {"product_id": self.product.id, "product_qty": qty}
                                )
                            ],
                        }
                    )
                    sale_orders |= order

                    expected_so_currency_rate = (
                        self.env["res.currency.rate"]
                        .search(
                            [
                                ("name", "=", date),
                                ("currency_id", "=", pricelist.currency_id.id),
                                ("company_id", "=", company.id),
                            ]
                        )
                        .rate
                    )
                    expected_product_currency_rate = (
                        self.env["res.currency.rate"]
                        .search(
                            [
                                ("name", "=", date),
                                ("currency_id", "=", self.product.currency_id.id),
                                ("company_id", "=", company.id),
                            ]
                        )
                        .rate
                    )

                    price_for_so_company = (
                        self.product.list_price / expected_product_currency_rate
                    )

                    expected_amount_total = pricelist.currency_id.round(
                        qty * price_for_so_company * expected_so_currency_rate
                    )
                    self.assertAlmostEqual(
                        order.currency_rate, expected_so_currency_rate
                    )
                    self.assertAlmostEqual(order.amount_total, expected_amount_total)

                    current_company_rate = currency_rates[
                        self.env.company.currency_id.id
                    ]
                    so_company_rate = currency_rates[company.currency_id.id]
                    conversion_rate = current_company_rate / so_company_rate
                    expected_reported_amount += (
                        order.amount_total / order.currency_rate * conversion_rate
                    )

        report_lines = (
            self.env["sale.report"]
            .sudo()
            .with_context(allow_company_ids=[self.usd_cmp.id, self.eur_cmp.id])
            .search(
                [
                    (
                        "order_reference",
                        "in",
                        [f"sale.order,{so_id}" for so_id in sale_orders.ids],
                    )
                ]
            )
        )

        price_total = sum(report_lines.mapped("price_total"))
        self.assertAlmostEqual(price_total, expected_reported_amount)

    def test_sale_report_with_downpayment(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                        }
                    )
                ],
            }
        )
        order.action_confirm()

        downpayment = (
            self.env["sale.advance.payment.inv"]
            .with_context(active_ids=order.ids)
            .create({"advance_payment_method": "fixed", "fixed_amount": 200})
        )
        downpayment.create_invoices()
        order.invoice_ids.action_post()
        order.line_ids.flush_recordset()

        amount_line = self.env["sale.report"].formatted_read_group(
            [("order_reference", "=", f"sale.order,{order.id}")],
            aggregates=["amount_taxexc_to_invoice:sum", "amount_taxexc_invoiced:sum"],
        )[0]

        self.assertEqual(
            float_compare(
                amount_line["amount_taxexc_invoiced:sum"],
                200,
                precision_rounding=order.currency_id.rounding,
            ),
            0,
        )
        self.assertEqual(
            float_compare(
                amount_line["amount_taxexc_to_invoice:sum"],
                self.product.lst_price - 200,
                precision_rounding=order.currency_id.rounding,
            ),
            0,
        )
