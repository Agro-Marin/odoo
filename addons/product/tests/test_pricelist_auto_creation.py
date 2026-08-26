from odoo.addons.product.tests.common import ProductCommon


class TestPricelistAutoCreation(ProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.currency_euro = cls._enable_currency("EUR")
        cls.currency_usd = cls.env["res.currency"].search([("name", "=", "USD")])
        cls.env["res.company"].search([]).currency_id = cls.currency_euro
        cls.env["res.currency"].search([("name", "!=", "EUR")]).action_archive()

        cls.group_user = cls.env.ref("base.group_user").sudo()
        cls.group_user._remove_group(cls.group_product_pricelist)
        cls.env["product.pricelist"].search([]).unlink()

    def test_inactive_curr_set_on_company(self):
        self.env.company.currency_id = self.currency_usd
        self.assertFalse(
            self.env["product.pricelist"].search(
                [
                    ("currency_id.name", "=", "EUR"),
                    ("company_id", "=", self.env.company.id),
                ]
            )
        )
        self.assertTrue(self.currency_usd.active)
        self.assertTrue(
            self.env["product.pricelist"].search(
                [
                    ("currency_id.name", "=", "USD"),
                    ("company_id", "=", self.env.company.id),
                ]
            )
        )
