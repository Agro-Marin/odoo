from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestLineAmounts(BaseOrderTestCase):
    """Assertions on `mixin.order.line.amount._compute_amounts` itself.

    The module's other amount tests build a `sale.order.line`, so until this
    file existed the mixin's own computation could be changed arbitrarily --
    doubling every subtotal, zeroing every tax -- without a single test
    failing. Everything here runs against the mixin, through the concrete test
    model that carries nothing but it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tax_15 = cls.env["account.tax"].create(
            {
                "name": "BO Tax 15",
                "amount": 15.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include_override": "tax_excluded",
            }
        )

    def _line(self, **kw):
        vals = {"product_qty": 1.0, "price_unit": 100.0, "tax_ids": False}
        vals.update(kw)
        return self._make_line(**vals)

    def test_subtotal_is_quantity_times_unit_price(self):
        line = self._line(product_qty=3.0, price_unit=25.0)

        self.assertAlmostEqual(line.price_subtotal, 75.0, places=2)

    def test_discount_reduces_the_subtotal(self):
        line = self._line(product_qty=2.0, price_unit=100.0, discount=25.0)

        self.assertAlmostEqual(line.price_subtotal, 150.0, places=2)

    def test_tax_lands_on_price_tax_and_price_total(self):
        line = self._line(product_qty=2.0, price_unit=100.0, tax_ids=self.tax_15.ids)

        self.assertAlmostEqual(line.price_subtotal, 200.0, places=2)
        self.assertAlmostEqual(line.price_tax, 30.0, places=2)
        self.assertAlmostEqual(line.price_total, 230.0, places=2)

    def test_untaxed_line_has_no_tax(self):
        line = self._line(product_qty=2.0, price_unit=100.0)

        self.assertAlmostEqual(line.price_tax, 0.0, places=2)
        self.assertAlmostEqual(line.price_total, line.price_subtotal, places=2)

    def test_total_is_always_subtotal_plus_tax(self):
        line = self._line(product_qty=7.0, price_unit=13.37, discount=11.0)
        line.tax_ids = self.tax_15

        self.assertAlmostEqual(
            line.price_total,
            line.price_subtotal + line.price_tax,
            places=2,
        )

    def test_a_display_line_carries_no_amounts(self):
        order = self._make_order()
        section = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "display_type": "line_section",
                "name": "A section",
            }
        )

        self.assertFalse(section.price_subtotal)
        self.assertFalse(section.price_tax)
        self.assertFalse(section.price_total)

    def test_amounts_follow_a_quantity_change(self):
        line = self._line(product_qty=1.0, price_unit=100.0)
        self.assertAlmostEqual(line.price_subtotal, 100.0, places=2)

        line.product_qty = 4.0

        self.assertAlmostEqual(line.price_subtotal, 400.0, places=2)

    def test_a_batch_computes_each_line_on_its_own_values(self):
        order = self._make_order()
        lines = self.env["base.order.test.line"].create(
            [
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "name": "L%d" % qty,
                    "product_qty": qty,
                    "price_unit": 10.0,
                }
                for qty in (1.0, 2.0, 3.0)
            ]
        )

        self.assertEqual(
            [line.price_subtotal for line in lines],
            [10.0, 20.0, 30.0],
        )

    def test_order_amounts_aggregate_the_line_subtotals(self):
        order = self._make_order()
        self._make_line(order=order, product_qty=2.0, price_unit=100.0)
        self._make_line(order=order, product_qty=1.0, price_unit=50.0)

        self.assertAlmostEqual(order.amount_untaxed, 250.0, places=2)
        self.assertAlmostEqual(order.amount_total, 250.0, places=2)
