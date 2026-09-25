from odoo.tests import tagged

from odoo.addons.test_trade.tests.common import TestTradeOrderCase


@tagged("post_install", "-at_install")
class TestLinePriceGross(TestTradeOrderCase):
    def _line(self, **kw):
        order = self._make_order()
        vals = {
            "order_id": order.id,
            "product_id": self.product.id,
            "product_qty": 1.0,
            "price_unit": 100.0,
        }
        vals.update(kw)
        return self.env["test_trade.order.line"].create(vals)

    def test_price_unit_gross_no_tax_no_discount(self):
        line = self._line(discount=0.0, tax_ids=False)

        self.assertAlmostEqual(line._get_price_unit_gross(), 100.0, places=2)

    def test_price_unit_gross_applies_discount(self):
        line = self._line(discount=10.0, tax_ids=False)

        self.assertAlmostEqual(line._get_price_unit_gross(), 90.0, places=2)
