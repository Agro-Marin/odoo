from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestMerge(BaseOrderTestCase):
    """t24068 (Loop A audit, HIGH): `_merge_get_line_key` used to match
    lines by (product, UoM, analytic distribution, discount) only, NOT
    `price_unit`/`tax_ids`. Two lines sharing product/UoM/discount but
    priced or taxed differently were silently consolidated into one line
    worth neither source amount, with a tax obligation vanishing entirely
    (`_merge_order_line` sums quantity but takes `min(price_unit)` and keeps
    only the target's own `tax_ids`)."""

    def _order_with_line(self, **line_kw):
        order = self._make_order()
        vals = {"product_qty": 1.0, "price_unit": 100.0}
        vals.update(line_kw)
        self._make_line(order=order, **vals)
        return order

    def _order_with_section(self, prefix):
        order = self._make_order()
        Line = self.env["base.order.test.line"]
        Line.create(
            {
                "order_id": order.id,
                "display_type": "line_section",
                "name": f"{prefix} SECTION",
                "sequence": 10,
            }
        )
        Line.create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_qty": 1.0,
                "price_unit": 10.0 if prefix == "A" else 20.0,
                "name": f"{prefix} line",
                "sequence": 11,
            }
        )
        return order

    def test_merge_does_not_consolidate_lines_with_different_price(self):
        order_a = self._order_with_line(price_unit=100.0)
        order_b = self._order_with_line(price_unit=150.0)

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(
            len(lines), 2, "differently-priced lines must not merge into one"
        )
        self.assertEqual(
            sorted(lines.mapped("price_unit")),
            [100.0, 150.0],
            "neither source line's price should be lost or altered",
        )
        total_qty = sum(lines.mapped("product_qty"))
        self.assertEqual(
            total_qty, 2.0, "quantity must still be preserved across both lines"
        )

    def test_merge_does_not_consolidate_lines_with_different_tax(self):
        tax = self.env["account.tax"].create(
            {
                "name": "Test Tax 15%",
                "amount": 15.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
            }
        )
        order_a = self._order_with_line(tax_ids=[(6, 0, [])])
        order_b = self._order_with_line(tax_ids=[(6, 0, tax.ids)])

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(
            len(lines), 2, "differently-taxed lines must not merge into one"
        )
        self.assertIn(
            tax, lines.mapped("tax_ids"), "the taxed line's tax must survive the merge"
        )

    def test_merge_does_consolidate_identical_lines(self):
        order_a = self._order_with_line(price_unit=100.0)
        order_b = self._order_with_line(price_unit=100.0)

        (order_a | order_b).action_merge()

        target = order_a if order_a.date_order <= order_b.date_order else order_b
        lines = target.line_ids.filtered(lambda line: not line.display_type)
        self.assertEqual(
            len(lines), 1, "identical lines should still consolidate into one"
        )
        self.assertEqual(lines.product_qty, 2.0)
        self.assertEqual(lines.price_unit, 100.0)

    def test_merged_sections_do_not_collide_on_sequence(self):
        """Sequences are per-order, so every source repeats the target's."""
        first = self._order_with_section("A")
        second = self._order_with_section("B")

        (first + second).action_merge()

        target = first if first.state == "draft" else second
        sequences = target.line_ids.mapped("sequence")
        self.assertEqual(
            len(sequences),
            len(set(sequences)),
            f"two merged lines share a sequence: {sorted(sequences)}",
        )
        names = target.line_ids.sorted("sequence").mapped("name")
        self.assertEqual(
            names.index("A SECTION") + 1,
            names.index("A line"),
            "a section must stay immediately above the line it introduces",
        )
        self.assertLess(
            names.index("A SECTION"),
            names.index("B SECTION"),
            "the target's own block comes first",
        )

    def _order_with_identical_lines(self, count):
        order = self._make_order()
        for _index in range(count):
            self._make_line(order=order, product_qty=1.0, price_unit=10.0)
        return order

    def test_a_target_carrying_duplicate_lines_does_not_break_the_merge(self):
        """The index is pruned when equivalent target lines are folded.

        Folding unlinks all but the first, and an index still holding them
        handed a deleted record to the next source line sharing the key -- the
        merge died with MissingError partway through, having already moved
        some lines.
        """
        target = self._order_with_identical_lines(2)
        first_source = self._order_with_identical_lines(1)
        second_source = self._order_with_identical_lines(1)

        (target + first_source + second_source).action_merge()

        self.assertEqual(len(target.line_ids), 1)
        self.assertAlmostEqual(target.line_ids.product_qty, 4.0, places=2)

    def test_folding_conserves_the_total_quantity(self):
        target = self._order_with_identical_lines(3)
        source = self._order_with_identical_lines(2)
        total = sum((target + source).line_ids.mapped("product_qty"))

        (target + source).action_merge()

        self.assertAlmostEqual(
            sum(target.line_ids.mapped("product_qty")),
            total,
            places=2,
        )

    def test_finding_matches_changes_nothing_on_its_own(self):
        """`_merge_find_matching_line` reads; `_merge_collapse_matches` writes."""
        target = self._order_with_identical_lines(2)
        source = self._order_with_identical_lines(1)
        candidates = list(target.line_ids)

        matches = target._merge_find_matching_line(source.line_ids, candidates)

        self.assertEqual(len(matches), 2)
        self.assertEqual(len(target.line_ids), 2, "finding must not fold")
        self.assertEqual(
            target.line_ids.mapped("product_qty"),
            [1.0, 1.0],
            "finding must not move quantity",
        )
