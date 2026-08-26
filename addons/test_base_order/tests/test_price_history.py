from odoo import fields
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestPriceHistory(BaseOrderTestCase):
    """`mixin.order.line.price.history`: the statistics behind the widget.

    A quantity-weighted average, the period extremes, the partner-versus-market
    divergence, and the sample cap. Two paths reach them -- one grouped query
    when every matching line is already in the target currency, and a row-by-
    row pass when it is not, because each row converts at its own document
    date. Both shipping wizards live in `sale` and `purchase`, so neither path
    was asserted anywhere.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_partner = cls.env["res.partner"].create({"name": "BO Other Partner"})

    def _confirmed_line(self, price, qty=1.0, partner=None, product=None):
        order = self.env["base.order.test"].create(
            {"partner_id": (partner or self.partner).id}
        )
        line = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "product_id": (product or self.product).id,
                "product_qty": qty,
                "price_unit": price,
                "name": "history line",
            }
        )
        order.action_confirm()
        return line

    def _wizard(self, target, partner=None):
        return self.env["base.order.test.line.price.history"].create(
            {
                "line_id": target.id,
                "product_id": target.product_id.id,
                "partner_id": (partner or self.partner).id,
            }
        )

    # ─── the weighted average ─────────────────────────────────────

    def test_the_average_is_weighted_by_quantity_not_by_line(self):
        """Ten units at 10 and one at 100 average 18.18, not 55."""
        self._confirmed_line(price=10.0, qty=10.0)
        self._confirmed_line(price=100.0, qty=1.0)
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertAlmostEqual(wizard.avg_price_unit, 200.0 / 11.0, places=2)
        self.assertEqual(wizard.avg_sample_count, 2)

    def test_the_extremes_come_from_the_sample(self):
        self._confirmed_line(price=10.0)
        self._confirmed_line(price=70.0)
        self._confirmed_line(price=40.0)
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertAlmostEqual(wizard.min_price_unit, 10.0, places=2)
        self.assertAlmostEqual(wizard.max_price_unit, 70.0, places=2)

    def test_the_target_line_is_excluded_from_its_own_statistics(self):
        self._confirmed_line(price=10.0)
        target = self._confirmed_line(price=1000.0)

        wizard = self._wizard(target)

        self.assertEqual(wizard.avg_sample_count, 1)
        self.assertAlmostEqual(wizard.avg_price_unit, 10.0, places=2)

    def test_a_draft_line_is_not_in_the_statistics(self):
        order = self.env["base.order.test"].create({"partner_id": self.partner.id})
        self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_qty": 1.0,
                "price_unit": 999.0,
                "name": "draft line",
            }
        )
        self._confirmed_line(price=10.0)
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertEqual(wizard.avg_sample_count, 1)

    def test_another_product_is_not_in_the_statistics(self):
        other = self.env["product.product"].create({"name": "Unrelated"})
        self._confirmed_line(price=999.0, product=other)
        self._confirmed_line(price=10.0)
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertEqual(wizard.avg_sample_count, 1)
        self.assertAlmostEqual(wizard.avg_price_unit, 10.0, places=2)

    def test_a_discount_is_taken_off_before_averaging(self):
        line = self._confirmed_line(price=100.0)
        line.discount = 50.0
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertAlmostEqual(wizard.avg_price_unit, 50.0, places=2)

    # ─── divergence ───────────────────────────────────────────────

    def test_divergence_is_relative_to_the_period_average(self):
        self._confirmed_line(price=100.0)
        target = self._confirmed_line(price=120.0)

        wizard = self._wizard(target)

        self.assertAlmostEqual(wizard.current_price_unit, 120.0, places=2)
        self.assertAlmostEqual(wizard.divergence_pct, 0.2, places=4)

    def test_a_higher_price_is_favorable_when_selling(self):
        """`_price_direction` is 1 on a sale-facing model, -1 on a buying one."""
        self.assertEqual(self.env["base.order.test.line"]._price_direction, 1)
        self._confirmed_line(price=100.0)

        above = self._wizard(self._confirmed_line(price=120.0))
        below = self._wizard(self._confirmed_line(price=80.0))

        self.assertTrue(above.divergence_favorable)
        self.assertFalse(below.divergence_favorable)

    def test_no_history_leaves_every_figure_at_zero(self):
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertEqual(wizard.avg_sample_count, 0)
        self.assertAlmostEqual(wizard.avg_price_unit, 0.0, places=2)
        self.assertAlmostEqual(wizard.divergence_pct, 0.0, places=4)
        self.assertFalse(wizard.avg_sample_truncated)

    # ─── the partner cut ──────────────────────────────────────────

    def test_the_partner_average_is_read_against_the_market_one(self):
        self._confirmed_line(price=100.0, partner=self.other_partner)
        self._confirmed_line(price=200.0, partner=self.partner)
        target = self._confirmed_line(price=50.0, partner=self.partner)

        wizard = self._wizard(target, partner=self.partner)

        self.assertEqual(wizard.avg_sample_count, 2)
        self.assertAlmostEqual(wizard.avg_price_unit, 150.0, places=2)
        self.assertEqual(wizard.partner_avg_sample_count, 1)
        self.assertAlmostEqual(wizard.partner_avg_price_unit, 200.0, places=2)
        self.assertAlmostEqual(wizard.partner_divergence_pct, 1 / 3, places=4)

    def test_a_partner_with_no_history_reports_no_partner_sample(self):
        self._confirmed_line(price=100.0, partner=self.other_partner)
        target = self._confirmed_line(price=50.0, partner=self.other_partner)

        wizard = self._wizard(target, partner=self.partner)

        self.assertEqual(wizard.partner_avg_sample_count, 0)

    # ─── period ───────────────────────────────────────────────────

    def test_the_period_start_moves_with_the_selection(self):
        target = self._confirmed_line(price=50.0)
        wizard = self._wizard(target)
        today = fields.Date.context_today(wizard)

        wizard.period = "last_3m"
        three_months = wizard._get_period_start()
        wizard.period = "last_12m"
        twelve_months = wizard._get_period_start()
        wizard.period = "current_year"
        this_year = wizard._get_period_start()

        self.assertLess(twelve_months, three_months)
        self.assertLess(three_months, today)
        self.assertEqual((this_year.month, this_year.day), (1, 1))

    def test_a_line_outside_the_period_is_not_counted(self):
        old = self._confirmed_line(price=999.0)
        old.order_id.date_order = fields.Datetime.subtract(
            fields.Datetime.now(), days=400
        )
        self._confirmed_line(price=10.0)
        target = self._confirmed_line(price=50.0)

        wizard = self._wizard(target)

        self.assertEqual(wizard.avg_sample_count, 1)
        self.assertAlmostEqual(wizard.avg_price_unit, 10.0, places=2)

    # ─── the shortlist and the action ─────────────────────────────

    def test_the_shortlist_is_filled_from_the_filters(self):
        self._confirmed_line(price=10.0)
        self._confirmed_line(price=20.0)
        target = self._confirmed_line(price=50.0)
        wizard = self._wizard(target)

        wizard._onchange_price_history_filters()

        self.assertEqual(len(wizard.line_ids), 2)

    def test_a_shortlist_row_reports_its_own_divergence(self):
        self._confirmed_line(price=100.0)
        target = self._confirmed_line(price=50.0)
        wizard = self._wizard(target)
        wizard._onchange_price_history_filters()

        row = wizard.line_ids[0]

        self.assertAlmostEqual(row.price_unit_normalized, 100.0, places=2)
        self.assertAlmostEqual(row.divergence_pct, 0.0, places=4)

    def test_taking_a_price_from_the_shortlist_writes_it_to_the_target(self):
        self._confirmed_line(price=77.0)
        target = self._confirmed_line(price=50.0)
        wizard = self._wizard(target)
        wizard._onchange_price_history_filters()

        wizard.line_ids[0].action_set_price()

        self.assertAlmostEqual(target.price_unit, 77.0, places=2)

    def test_opening_the_full_history_scopes_it_to_the_product(self):
        target = self._confirmed_line(price=50.0)
        wizard = self._wizard(target)

        action = wizard.action_open_history()

        self.assertIn(("product_id", "=", self.product.id), action["domain"])
        self.assertEqual(action["res_model"], "base.order.test.line")
