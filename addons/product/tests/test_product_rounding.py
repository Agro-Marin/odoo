import time

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductRounding(ProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # test-specific currencies
        cls.currency_jpy = cls.env["res.currency"].create(
            {
                "name": "JPX",
                "symbol": "¥",
                "rounding": 1.0,
                "rate_ids": [
                    Command.create(
                        {"rate": 133.6200, "name": time.strftime("%Y-%m-%d")}
                    )
                ],
            }
        )

        cls.currency_cad = cls.env["res.currency"].create(
            {
                "name": "CXD",
                "symbol": "$",
                "rounding": 0.01,
                "rate_ids": [
                    Command.create(
                        {"rate": 1.338800, "name": time.strftime("%Y-%m-%d")}
                    )
                ],
            }
        )

        cls.pricelist_usd = cls.pricelist

        cls.pricelist_jpy = cls.env["product.pricelist"].create(
            {
                "name": "Pricelist Testing JPY",
                "currency_id": cls.currency_jpy.id,
            }
        )

        cls.pricelist_cad = cls.env["product.pricelist"].create(
            {
                "name": "Pricelist Testing CAD",
                "currency_id": cls.currency_cad.id,
            }
        )

        cls.product_1_dollar = cls.env["product.product"].create(
            {
                "name": "Test Product $1",
                "list_price": 1.00,
                "categ_id": cls.product_category.id,
            }
        )

        cls.product_100_dollars = cls.env["product.product"].create(
            {
                "name": "Test Product $100",
                "list_price": 100.00,
                "categ_id": cls.product_category.id,
            }
        )

    def test_no_discount_1_dollar_product(self):
        """Ensure that no discount is applied when there shouldn't be, even for very small amounts."""
        product = self.product_1_dollar

        product_in_jpy = product.with_context(pricelist=self.pricelist_jpy.id)
        discount_jpy = product_in_jpy._get_contextual_discount()
        self.assertAlmostEqual(
            discount_jpy,
            0.0,
            places=6,
            msg="No discount should be applied for $1 product in Testing JPY.",
        )

        product_in_usd = product.with_context(pricelist=self.pricelist_usd.id)
        discount_usd = product_in_usd._get_contextual_discount()
        self.assertAlmostEqual(
            discount_usd,
            0.0,
            places=6,
            msg="No discount should be applied for $1 product in USD.",
        )

        product_in_cad = product.with_context(pricelist=self.pricelist_cad.id)
        discount_cad = product_in_cad._get_contextual_discount()
        self.assertAlmostEqual(
            discount_cad,
            0.0,
            places=6,
            msg="No discount should be applied for $1 product in Testing CAD.",
        )

    def test_no_discount_100_dollars_product(self):
        """Ensure that no discount is applied when there shouldn't be, even for very small amounts."""
        product = self.product_100_dollars

        product_in_jpy = product.with_context(pricelist=self.pricelist_jpy.id)
        discount_jpy = product_in_jpy._get_contextual_discount()
        self.assertAlmostEqual(
            discount_jpy,
            0.0,
            places=6,
            msg="No discount should be applied for $100 product in Testing JPY.",
        )

        product_in_usd = product.with_context(pricelist=self.pricelist_usd.id)
        discount_usd = product_in_usd._get_contextual_discount()
        self.assertAlmostEqual(
            discount_usd,
            0.0,
            places=6,
            msg="No discount should be applied for $100 product in USD.",
        )

        product_in_cad = product.with_context(pricelist=self.pricelist_cad.id)
        discount_cad = product_in_cad._get_contextual_discount()
        self.assertAlmostEqual(
            discount_cad,
            0.0,
            places=6,
            msg="No discount should be applied for $100 product in Testing CAD.",
        )

    def test_discount_percentage_rule(self):
        """A percentage pricelist rule must surface as a contextual discount.

        Guards against `_get_contextual_discount` degenerating into a constant
        0.0 — the zero-discount tests above cannot tell those apart.
        """
        self._enable_pricelists()
        self.pricelist_usd.item_ids = [
            Command.create(
                {
                    "compute_price": "percentage",
                    "percent_price": 10.0,
                }
            )
        ]
        product = self.product_100_dollars.with_context(pricelist=self.pricelist_usd.id)
        self.assertAlmostEqual(product._get_contextual_discount(), 0.10, places=6)

    def test_discount_percentage_rule_cross_currency(self):
        """The contextual discount must hold across a currency conversion."""
        self._enable_pricelists()
        self.pricelist_cad.item_ids = [
            Command.create(
                {
                    "compute_price": "percentage",
                    "percent_price": 25.0,
                }
            )
        ]
        product = self.product_100_dollars.with_context(pricelist=self.pricelist_cad.id)
        self.assertAlmostEqual(product._get_contextual_discount(), 0.25, places=4)

    def test_discount_uses_the_contextual_date_on_both_sides(self):
        """`context['date']` reaches the price but used to be ignored by the
        list price it is compared against.

        `_get_contextual_price` forwards the date down to `_compute_price_rule`,
        while the denominator was converted at `fields.Datetime.now()`. Any
        currency-rate change between the two dates leaked straight into the
        ratio: with the rate below (1.0 then 4.0) a plain 10% rule reported a
        77.5% discount on a back-dated context.
        """
        self._enable_pricelists()
        currency = self.env["res.currency"].create(
            {
                "name": "DXY",
                "symbol": "D",
                "rounding": 0.01,
                "rate_ids": [
                    Command.create({"rate": 1.0, "name": "2020-01-01"}),
                    Command.create({"rate": 4.0, "name": time.strftime("%Y-%m-%d")}),
                ],
            }
        )
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Pricelist Testing Dated",
                "currency_id": currency.id,
                "item_ids": [
                    Command.create(
                        {"compute_price": "percentage", "percent_price": 10.0}
                    )
                ],
            }
        )
        product = self.product_100_dollars.with_context(
            pricelist=pricelist.id, date="2020-06-01 12:00:00"
        )
        self.assertAlmostEqual(
            product._get_contextual_discount(),
            0.10,
            places=6,
            msg="the discount must not absorb the currency-rate change",
        )
