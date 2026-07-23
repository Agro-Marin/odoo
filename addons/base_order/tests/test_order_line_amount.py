# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged

# Part 2 of base_order's by-parts coverage: the line-level amount mixin
# (order.line.amount.mixin), exercised through sale.order.line.


@tagged("post_install", "-at_install")
class TestOrderLineAmountMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Buyer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Item", "list_price": 100.0}
        )
        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})

    def _line(self, **vals):
        line = self.env["sale.order.line"].create(
            {"order_id": self.order.id, "product_id": self.product.id}
        )
        if vals:
            line.write(vals)
        return line

    def test_untaxed_subtotal_is_qty_times_unit(self):
        """Without taxes the line subtotal is quantity times unit price."""
        line = self._line(
            price_unit=100.0, product_qty=2.0, discount=0.0, tax_ids=[(5, 0, 0)]
        )
        self.assertAlmostEqual(line.price_subtotal, 200.0)
        self.assertAlmostEqual(line.price_tax, 0.0)
        self.assertAlmostEqual(line.price_total, 200.0)

    def test_discount_reduces_subtotal_and_unit(self):
        """A percentage discount lowers the subtotal and the discounted unit."""
        line = self._line(
            price_unit=100.0, product_qty=1.0, discount=25.0, tax_ids=[(5, 0, 0)]
        )
        self.assertAlmostEqual(line.price_subtotal, 75.0)
        self.assertAlmostEqual(line.price_unit_discounted_taxexc, 75.0)

    def test_price_total_is_subtotal_plus_tax(self):
        """The line total always equals its subtotal plus its tax."""
        line = self._line(price_unit=100.0, product_qty=1.0)
        self.assertAlmostEqual(line.price_total, line.price_subtotal + line.price_tax)
