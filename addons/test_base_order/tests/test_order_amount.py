from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderAmountMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Buyer"})
        cls.product_a = cls.env["product.product"].create(
            {"name": "Item A", "list_price": 100.0}
        )
        cls.product_b = cls.env["product.product"].create(
            {"name": "Item B", "list_price": 50.0}
        )

    def _order(self, products):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [(0, 0, {"product_id": p.id}) for p in products],
            }
        )

    def test_untaxed_amount_aggregates_line_subtotals(self):
        order = self._order([self.product_a, self.product_b])
        self.assertGreater(order.amount_total, 0)
        self.assertEqual(
            order.amount_untaxed, sum(order.line_ids.mapped("price_subtotal"))
        )

    def test_total_is_untaxed_plus_tax(self):
        order = self._order([self.product_a])
        self.assertEqual(order.amount_total, order.amount_untaxed + order.amount_tax)

    def test_order_without_lines_has_zero_amounts(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.assertEqual(order.amount_untaxed, 0.0)
        self.assertEqual(order.amount_total, 0.0)
