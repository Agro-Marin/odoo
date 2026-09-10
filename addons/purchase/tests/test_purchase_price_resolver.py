from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchasePriceResolver(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.resolver = cls.env["purchase.price.resolver"]
        cls.foreign_currency = cls.setup_other_currency("EUR")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.dozen = cls.env.ref("uom.product_uom_dozen")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Resolved product",
                "standard_price": 10.0,
                "uom_id": cls.unit.id,
                "supplier_taxes_id": [Command.clear()],
            }
        )

    def _create_seller(self, **values):
        return self.env["product.supplierinfo"].create(
            {
                "partner_id": self.partner_a.id,
                "product_tmpl_id": self.product.product_tmpl_id.id,
                **values,
            }
        )

    def _get_price_resolution(self, seller, uom, currency):
        return self.resolver._get_price_resolution(
            self.product,
            seller=seller,
            uom=uom,
            currency=currency,
            company=self.env.company,
            date=fields.Date.today(),
            taxes=self.env["account.tax"],
        )

    def test_seller_price_is_converted_to_the_target_currency_and_unit(self):
        seller = self._create_seller(
            price=100.0, discount=5.0, currency_id=self.foreign_currency.id
        )

        resolution = self._get_price_resolution(
            seller, self.dozen, self.env.company.currency_id
        )

        self.assertEqual(resolution.source, "supplierinfo")
        self.assertEqual(resolution.seller, seller)
        self.assertAlmostEqual(resolution.price_unit, 600.0)
        self.assertEqual(resolution.discount, 5.0)

    def test_no_seller_resolves_to_product_cost_in_the_target_currency_and_unit(self):
        resolution = self._get_price_resolution(
            self.env["product.supplierinfo"], self.dozen, self.foreign_currency
        )

        self.assertEqual(resolution.source, "product_cost")
        self.assertAlmostEqual(resolution.price_unit, 240.0)
        self.assertEqual(resolution.discount, 0.0)

    def test_get_seller_honours_the_validity_window(self):
        seller = self._create_seller(
            price=100.0, date_end=fields.Date.today() - timedelta(days=1)
        )

        def resolve(date):
            return self.resolver._get_seller(
                self.product,
                partner=self.partner_a,
                quantity=1.0,
                uom=self.unit,
                date=date,
                company=self.env.company,
            )

        self.assertFalse(resolve(fields.Date.today()))
        self.assertEqual(resolve(fields.Date.today() - timedelta(days=2)), seller)
