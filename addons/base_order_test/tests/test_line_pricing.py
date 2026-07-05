from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestLinePricing(BaseOrderTestCase):
    def _line(self, **kw):
        order = self._make_order()
        vals = {
            "order_id": order.id,
            "product_id": self.product.id,
            "product_qty": 1.0,
            "price_unit": 100.0,
        }
        vals.update(kw)
        return self.env["base.order.test.line"].create(vals)

    def test_price_unit_gross_no_tax_no_discount(self):
        line = self._line(discount=0.0, tax_ids=False)

        self.assertAlmostEqual(line._get_price_unit_gross(), 100.0, places=2)

    def test_price_unit_gross_applies_discount(self):
        line = self._line(discount=10.0, tax_ids=False)

        self.assertAlmostEqual(line._get_price_unit_gross(), 90.0, places=2)

    def test_should_update_when_price_matches_old_auto(self):
        line = self._line(price_unit=100.0)

        # price_unit == old auto -> not a manual override -> update allowed
        self.assertTrue(line._should_update_price(120.0, 100.0))

    def test_should_not_update_when_manually_overridden(self):
        line = self._line(price_unit=100.0)

        # price_unit (100) != old auto (80) -> manual override -> preserve
        self.assertFalse(line._should_update_price(120.0, 80.0))

    def test_force_recompute_bypasses_manual_protection(self):
        line = self._line(price_unit=100.0)

        # manual override, but force_recompute wins
        self.assertTrue(line._should_update_price(120.0, 80.0, force_recompute=True))

    def test_price_auto_computed_from_hook(self):
        order = self._make_order()

        # No price_unit -> auto price from the hook (product.list_price = 100)
        line = self.env["base.order.test.line"].create(
            {"order_id": order.id, "product_id": self.product.id}
        )

        self.assertAlmostEqual(line.price_unit, 100.0, places=2)
        self.assertAlmostEqual(line.price_unit_auto, 100.0, places=2)

    def test_manual_price_preserved_over_auto(self):
        order = self._make_order()

        line = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "price_unit": 55.0,
            }
        )

        self.assertAlmostEqual(line.price_unit, 55.0, places=2)
