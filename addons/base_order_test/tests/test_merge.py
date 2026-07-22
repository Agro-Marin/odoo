from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestMerge(BaseOrderTestCase):
    """ t24068 (Loop A audit, HIGH): `_merge_get_line_key` used to match
    lines by (product, UoM, analytic distribution, discount) only, NOT
    `price_unit`/`tax_ids`. Two lines sharing product/UoM/discount but
    priced or taxed differently were silently consolidated into one line
    worth neither source amount, with a tax obligation vanishing entirely
    (`_merge_order_line` sums quantity but takes `min(price_unit)` and keeps
    only the target's own `tax_ids`). """

    def _order_with_line(self, **line_kw):
        order = self._make_order()
        vals = {"product_qty": 1.0, "price_unit": 100.0}
        vals.update(line_kw)
        self._make_line(order=order, **vals)
        return order

    def test_merge_does_not_consolidate_lines_with_different_price(self):
        order_a = self._order_with_line(price_unit=100.0)
        order_b = self._order_with_line(price_unit=150.0)

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(len(lines), 2, "differently-priced lines must not merge into one")
        self.assertEqual(
            sorted(lines.mapped("price_unit")), [100.0, 150.0],
            "neither source line's price should be lost or altered",
        )
        total_qty = sum(lines.mapped("product_qty"))
        self.assertEqual(total_qty, 2.0, "quantity must still be preserved across both lines")

    def test_merge_does_not_consolidate_lines_with_different_tax(self):
        tax = self.env["account.tax"].create({
            "name": "Test Tax 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
        })
        order_a = self._order_with_line(tax_ids=[(6, 0, [])])
        order_b = self._order_with_line(tax_ids=[(6, 0, tax.ids)])

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(len(lines), 2, "differently-taxed lines must not merge into one")
        self.assertIn(tax, lines.mapped("tax_ids"), "the taxed line's tax must survive the merge")

    def test_merge_does_consolidate_identical_lines(self):
        order_a = self._order_with_line(price_unit=100.0)
        order_b = self._order_with_line(price_unit=100.0)

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(len(lines), 1, "identical lines should still consolidate into one")
        self.assertEqual(lines.product_qty, 2.0)
        self.assertEqual(lines.price_unit, 100.0)
