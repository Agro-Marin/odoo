from ast import literal_eval

from lxml.etree import fromstring

from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestRemainingAggregates(TestStockValuationCommon):
    """`remaining_qty` and `remaining_value` are computed, not stored, so the
    server cannot put them through SQL: every grouped view leaves the two
    columns blank and there is no way to ask "how much of what is still on hand
    came in each month". Aggregate them in Python for the grouped read.
    """

    def _setup_moves(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)
        self._make_in_move(product, 4, unit_cost=10)
        return product

    def test_read_group_sums_remaining_quantity(self):
        product = self._setup_moves()
        moves = self.env["stock.move"].search(
            [("product_id", "=", product.id), ("is_in", "=", True)]
        )
        self.assertTrue(moves, "the fixture must leave incoming moves behind")
        expected = sum(moves.mapped("remaining_qty"))
        self.assertTrue(expected, "the fixture must leave something remaining")

        [(grouped_product, total)] = self.env["stock.move"]._read_group(
            [("id", "in", moves.ids)],
            ["product_id"],
            ["remaining_qty:sum"],
        )
        self.assertEqual(grouped_product, product)
        self.assertAlmostEqual(total, expected)

    def test_read_group_sums_remaining_value(self):
        product = self._setup_moves()
        moves = self.env["stock.move"].search(
            [("product_id", "=", product.id), ("is_in", "=", True)]
        )
        expected = sum(moves.mapped("remaining_value"))
        self.assertTrue(expected, "the fixture must leave value remaining")

        [(__, total)] = self.env["stock.move"]._read_group(
            [("id", "in", moves.ids)],
            ["product_id"],
            ["remaining_value:sum"],
        )
        self.assertAlmostEqual(total, expected)

    def test_read_group_splits_remaining_across_groups(self):
        """The aggregate is per group, not one total smeared over all of them."""
        product = self._setup_moves()
        other = self.product_fifo.with_company(self.company)
        self._make_in_move(other, 7, unit_cost=5)

        moves = self.env["stock.move"].search(
            [("product_id", "in", (product | other).ids), ("is_in", "=", True)]
        )
        per_product = dict(
            self.env["stock.move"]._read_group(
                [("id", "in", moves.ids)],
                ["product_id"],
                ["remaining_qty:sum"],
            )
        )
        for one in (product, other):
            self.assertAlmostEqual(
                per_product[one],
                sum(
                    moves.filtered(lambda m, p=one: m.product_id == p).mapped(
                        "remaining_qty"
                    )
                ),
            )

    def test_pivot_view_offers_the_remaining_measures(self):
        arch = self.env["stock.move"].get_view(
            view_id=self.env.ref("stock.view_stock_move_pivot").id,
            view_type="pivot",
        )["arch"]
        names = [node.get("name") for node in fromstring(arch).iterfind("./field")]
        for measure in ("remaining_qty", "remaining_value"):
            self.assertIn(
                measure,
                names,
                "the pivot must declare the measure; unstored fields are not"
                " offered by the client on their own",
            )

    def test_aging_report_filter_is_wired_to_the_moves_analysis_action(self):
        aging = self.env.ref("stock_account.filter_stock_move_aging_report")
        # `action_id` is a Many2one on the ir.actions.actions base table, so
        # the act_window record compares equal only by id.
        self.assertEqual(aging.action_id.id, self.env.ref("stock.stock_move_action").id)
        self.assertFalse(aging.user_ids, "the aging report is shared, not personal")
        self.assertEqual(
            literal_eval(aging.context)["pivot_measures"],
            ["remaining_qty", "remaining_value"],
        )
        self.assertTrue(
            self.env["stock.move"].search(literal_eval(aging.domain)) is not None
        )
