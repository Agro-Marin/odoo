from freezegun.api import freeze_time

from odoo import Command
from odoo.tests import tagged

from .common import PurchaseTestCommon


@tagged("post_install", "-at_install")
class TestCurrencyConversionDate(PurchaseTestCommon):
    """We are UTC-6, so `fields.Date.today()` is already tomorrow after 18:00.

    `_get_conversion_rate` falls back to `fields.Date.context_today(self)` when
    no date is given (odoo/addons/base/models/res_currency.py:389), which is the
    user's own date. Two calls in this module were overriding that fallback with
    the server's UTC date, so a conversion run late in the afternoon picked the
    next day's rate.
    """

    # 02:00 UTC on the 11th is 20:00 on the 10th in Mexico City.
    LATE_AFTERNOON = "2026-03-11 02:00:00"
    LOCAL_RATE = 20.0
    UTC_RATE = 25.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = "America/Mexico_City"
        cls.foreign_currency = cls.env["res.currency"].create(
            {"name": "FCU", "symbol": "F", "rounding": 0.01},
        )
        cls.env["res.currency.rate"].create(
            [
                {
                    "name": "2026-03-10",
                    "company_id": cls.company.id,
                    "currency_id": cls.foreign_currency.id,
                    "rate": cls.LOCAL_RATE,
                },
                {
                    "name": "2026-03-11",
                    "company_id": cls.company.id,
                    "currency_id": cls.foreign_currency.id,
                    "rate": cls.UTC_RATE,
                },
            ],
        )

    def _rate_used(self, amount_in_company_currency, source_amount):
        """The rate a converted amount implies, so failures read as a date."""
        return round(source_amount / amount_in_company_currency, 4)

    @freeze_time(LATE_AFTERNOON)
    def test_the_price_difference_line_uses_our_date_not_the_servers(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.vendor.id,
                "invoice_date": "2026-03-10",
                "currency_id": self.foreign_currency.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        line = bill.invoice_line_ids
        vals = line._prepare_price_difference_vals(
            1.0,
            100.0,
            self.company.expense_account_id,
        )

        self.assertEqual(
            self._rate_used(vals["balance"], 100.0),
            self.LOCAL_RATE,
            "at 20:00 in Mexico the price difference must use the 10th's rate, "
            "not the 11th's",
        )

    @freeze_time(LATE_AFTERNOON)
    def test_a_merged_procurement_line_uses_our_date_not_the_servers(self):
        seller = self.env["product.supplierinfo"].create(
            {
                "partner_id": self.vendor.id,
                "product_tmpl_id": self.product.product_tmpl_id.id,
                "price": 100.0,
                "currency_id": self.foreign_currency.id,
                "min_qty": 0.0,
            },
        )
        order = self._create_purchase(self.product, quantity=1.0, confirm=False)
        line = order.line_ids

        vals = self.env["stock.rule"]._update_purchase_order_line(
            self.product,
            1.0,
            self.product.uom_id,
            self.company,
            {"supplier": seller},
            line,
        )

        self.assertEqual(
            self._rate_used(vals["price_unit"], 100.0),
            self.LOCAL_RATE,
            "at 20:00 in Mexico the merged line must be priced with the 10th's "
            "rate, not the 11th's",
        )
