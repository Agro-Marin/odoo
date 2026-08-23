from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchasePriceHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.product = cls.env["product.product"].create(
            {
                "name": "History widget",
                "type": "consu",
                "uom_id": cls.uom_unit.id,
                "purchase_ok": True,
            }
        )
        cls.vendor_a, cls.vendor_b = cls.env["res.partner"].create(
            [{"name": "History vendor A"}, {"name": "History vendor B"}]
        )
        cls.vendor_a_branch = cls.env["res.partner"].create(
            {"name": "History vendor A branch", "parent_id": cls.vendor_a.id}
        )
        cls.now = fields.Datetime.now()

        cls.order_a = cls._create_order(cls.vendor_a, 100.0, 10, cls.uom_unit, 30)
        cls.order_b = cls._create_order(cls.vendor_b, 120.0, 5, cls.uom_unit, 60)
        cls.order_branch = cls._create_order(
            cls.vendor_a_branch, 1200.0, 2, cls.uom_dozen, 200
        )
        cls.order_stale = cls._create_order(cls.vendor_b, 999.0, 1, cls.uom_unit, 800)
        cls.order_draft = cls._create_order(
            cls.vendor_b, 500.0, 1, cls.uom_unit, 5, confirm=False
        )
        cls.target = cls._create_order(
            cls.vendor_a, 130.0, 3, cls.uom_unit, 0, confirm=False
        )
        cls.target_line = cls.target.line_ids[0]

    @classmethod
    def _create_order(cls, partner, price, qty, uom, days_ago, confirm=True):
        order = cls.env["purchase.order"].create(
            {
                "partner_id": partner.id,
                "date_order": cls.now - timedelta(days=days_ago),
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": qty,
                            "product_uom_id": uom.id,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        if confirm:
            order.action_confirm()
        return order

    def _create_wizard(self, **vals):
        return self.env["purchase.order.line.price.history"].create(
            {
                "line_id": self.target_line.id,
                "product_id": self.product.id,
                **vals,
            }
        )

    def _shortlist(self, **vals):
        wizard_form = Form(
            self.env["purchase.order.line.price.history"].with_context(
                default_line_id=self.target_line.id,
                default_product_id=self.product.id,
            )
        )
        for name, value in vals.items():
            setattr(wizard_form, name, value)
        return wizard_form.save()

    def test_average_is_quantity_weighted_across_units(self):
        wizard = self._create_wizard()
        # 100 x 10 units + 120 x 5 units + 100 x 24 units (2 dozen at 1200)
        self.assertAlmostEqual(
            wizard.avg_price_unit,
            round(4000 / 39, 2),
            places=2,
            msg="a Monetary is rounded to the currency's precision on read",
        )
        self.assertAlmostEqual(wizard.min_price_unit, 100.0)
        self.assertAlmostEqual(wizard.max_price_unit, 120.0)
        self.assertEqual(wizard.avg_sample_count, 3)
        self.assertFalse(wizard.avg_sample_truncated)

    def test_statistics_ignore_draft_and_out_of_period_documents(self):
        wizard = self._create_wizard(include_draft=True)
        self.assertEqual(
            wizard.avg_sample_count,
            3,
            "Statistics read confirmed, in-period documents only, whatever "
            "the shortlist toggle says",
        )

    def test_statistics_exclude_the_target_line(self):
        wizard = self._create_wizard()
        self.assertNotIn(
            self.target_line,
            self.env["purchase.order.line"].search(wizard._get_domain_price_stats()),
        )

    def test_current_price_divergence_is_unfavorable_when_buying_high(self):
        wizard = self._create_wizard()
        self.assertAlmostEqual(wizard.current_price_unit, 130.0)
        self.assertGreater(wizard.divergence_pct, 0)
        self.assertFalse(
            wizard.divergence_favorable,
            "Paying above the period average is never favorable on a purchase",
        )

    def test_price_direction_is_negative_for_purchase(self):
        self.assertEqual(self._create_wizard()._get_price_direction(), -1)

    def test_shortlist_is_scoped_to_the_commercial_partner(self):
        wizard = self._shortlist(partner_id=self.vendor_a)
        self.assertEqual(
            wizard.line_ids.line_id.order_id,
            self.order_a | self.order_branch,
            "A branch of the selected vendor belongs in its history",
        )

    def test_shortlist_without_partner_covers_every_vendor(self):
        wizard = self._shortlist()
        self.assertEqual(
            wizard.line_ids.line_id.order_id,
            self.order_a | self.order_b | self.order_branch,
        )

    def test_shortlist_respects_the_period(self):
        self.assertNotIn(
            self.order_stale,
            self._shortlist().line_ids.line_id.order_id,
            "An order older than the period is out of the shortlist",
        )
        self.assertIn(self.order_branch, self._shortlist().line_ids.line_id.order_id)
        self.assertNotIn(
            self.order_branch,
            self._shortlist(period="last_3m").line_ids.line_id.order_id,
        )

    def test_shortlist_adds_rfqs_only_when_asked(self):
        self.assertNotIn(self.order_draft, self._shortlist().line_ids.line_id.order_id)
        self.assertIn(
            self.order_draft,
            self._shortlist(include_draft=True).line_ids.line_id.order_id,
        )

    def test_shortlist_never_shows_the_target_line(self):
        self.assertNotIn(
            self.target_line, self._shortlist(include_draft=True).line_ids.line_id
        )

    def test_normalized_price_is_comparable_across_units(self):
        wizard = self._shortlist()
        row = wizard.line_ids.filtered(
            lambda record: record.line_id.order_id == self.order_branch
        )
        self.assertAlmostEqual(row.price_unit, 1200.0, msg="raw price is per dozen")
        self.assertAlmostEqual(
            row.price_unit_normalized,
            100.0,
            msg="the normalized column is per reference unit",
        )

    def test_set_price_converts_into_the_target_line_unit(self):
        wizard = self._shortlist()
        row = wizard.line_ids.filtered(
            lambda record: record.line_id.order_id == self.order_branch
        )
        row.action_set_price()
        self.assertAlmostEqual(
            self.target_line.price_unit,
            100.0,
            msg="1200 per dozen must land as 100 per unit, not as 1200",
        )

    def test_set_price_closes_the_dialog(self):
        wizard = self._shortlist()
        self.assertEqual(
            wizard.line_ids[0].action_set_price()["type"],
            "ir.actions.act_window_close",
        )

    def test_open_history_targets_the_full_history_action(self):
        action = self._create_wizard(partner_id=self.vendor_a.id).action_open_history()
        self.assertEqual(action["res_model"], "purchase.order.line")
        self.assertEqual(action["view_mode"], "list,pivot,graph")
        self.assertIn(("state", "=", "done"), action["domain"])
        self.assertIn(
            ("partner_id", "child_of", self.vendor_a.commercial_partner_id.ids),
            action["domain"],
        )

    def test_currency_defaults_to_the_target_line_currency(self):
        self.assertEqual(
            self._create_wizard().currency_id, self.target_line.currency_id
        )
        self.assertEqual(
            self.env["purchase.order.line.price.history"]
            .create({"product_id": self.product.id})
            .currency_id,
            self.env.company.currency_id,
        )

    def test_history_list_row_action_exists(self):
        view = self.env.ref("purchase.view_purchase_order_line_list_history")
        self.assertTrue(
            hasattr(self.env["purchase.order.line"], "action_view_order"),
            "The history list opens each row through this method",
        )
        self.assertIn("action_view_order", view.arch)

    def test_comparison_action_reads_confirmed_orders_only(self):
        action = self.target.action_price_comparison()
        self.assertIn(
            ("state", "=", "done"),
            action["domain"],
            "A price comparison that counts cancelled and draft lines is not a "
            "comparison",
        )

    def test_stored_normalization_columns_agree_across_units(self):
        per_unit = self.order_a.line_ids
        per_dozen = self.order_branch.line_ids
        self.assertAlmostEqual(per_unit.price_unit_product_uom, 100.0)
        self.assertAlmostEqual(
            per_dozen.price_unit_product_uom,
            100.0,
            msg="1200 per dozen is 100 per unit, and the column says so",
        )
        self.assertAlmostEqual(
            per_dozen.price_unit_discounted_taxexc_product_uom,
            100.0,
            msg="no discount here, so the net column matches the gross one",
        )

    def test_net_column_is_the_subtotal_over_the_reference_quantity(self):
        line = self.order_a.line_ids
        line.discount = 10.0
        self.assertAlmostEqual(
            line.price_unit_discounted_taxexc_product_uom,
            line.price_subtotal / line.product_uom_qty,
            msg="the stored column and the weighted average read one number",
        )
        self.assertAlmostEqual(line.price_unit_product_uom, 100.0, msg="gross is gross")

    def test_single_currency_sample_is_not_capped(self):
        self.env["purchase.order"].create(
            {
                "partner_id": self.vendor_b.id,
                "date_order": self.now - timedelta(days=10),
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 1,
                            "product_uom_id": self.uom_unit.id,
                            "price_unit": 110.0,
                        }
                    )
                    for _index in range(600)
                ],
            }
        ).action_confirm()
        wizard = self._create_wizard()
        self.assertGreater(
            wizard.avg_sample_count,
            600,
            "the grouped query has no sample cap to hit",
        )
        self.assertFalse(wizard.avg_sample_truncated)

    def test_mixed_currency_sample_converts_row_by_row(self):
        other = self.env.ref("base.EUR")
        other.active = True
        self.env["res.currency.rate"].create(
            {
                "currency_id": other.id,
                "company_id": self.env.company.id,
                "name": (self.now - timedelta(days=10)).date(),
                "rate": 2.0,
            }
        )
        self.env["purchase.order"].create(
            {
                "partner_id": self.vendor_b.id,
                "currency_id": other.id,
                "date_order": self.now - timedelta(days=10),
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 1,
                            "product_uom_id": self.uom_unit.id,
                            "price_unit": 300.0,
                        }
                    )
                ],
            }
        ).action_confirm()
        wizard = self._create_wizard()
        # 100x10 + 120x5 + 100x24 + 150x1, over 40 reference units
        self.assertAlmostEqual(wizard.avg_price_unit_exact, 4150 / 40, places=4)
        self.assertEqual(wizard.avg_sample_count, 4)

    def test_partner_average_is_scoped_to_the_commercial_group(self):
        wizard = self._create_wizard(partner_id=self.vendor_a.id)
        # vendor A bought 10 units at 100, its branch 24 units at 100
        self.assertAlmostEqual(wizard.partner_avg_price_unit, 100.0)
        self.assertEqual(wizard.partner_avg_sample_count, 2)
        self.assertLess(
            wizard.partner_divergence_pct,
            0,
            "this vendor sits under the all-partner average",
        )
        self.assertTrue(
            wizard.partner_divergence_favorable,
            "under the market is where a buyer wants their vendor",
        )

    def test_partner_average_is_absent_without_a_partner(self):
        wizard = self._create_wizard()
        self.assertEqual(wizard.partner_avg_sample_count, 0)
        self.assertFalse(wizard.partner_avg_price_unit)

    def test_row_divergence_divides_by_the_same_average_as_the_wizard(self):
        wizard = self._shortlist()
        exact = wizard.avg_price_unit_exact
        self.assertNotAlmostEqual(
            exact,
            wizard.avg_price_unit,
            places=6,
            msg="the fixture is only meaningful while the Monetary rounds",
        )
        for row in wizard.line_ids:
            self.assertAlmostEqual(
                row.divergence_pct,
                (row.price_unit_normalized - exact) / exact,
                places=12,
                msg="a row must not divide by the rounded average",
            )

    def test_comparison_is_shared_with_sale_through_the_order_mixin(self):
        self.assertIn(
            "show_comparison",
            self.env["mixin.order"]._fields,
            "the flag is order-shaped, not purchase-shaped",
        )
        self.assertTrue(self.target.show_comparison)
        action = self.target.action_price_comparison()
        self.assertEqual(action["res_model"], "purchase.order.line")
        self.assertIn(("state", "=", "done"), action["domain"])

    def test_product_buttons_open_the_line_history(self):
        for record in (self.product, self.product.product_tmpl_id):
            self.assertEqual(
                record.action_view_po()["res_model"],
                "purchase.order.line",
                f"{record._name} should reach the lines, not an aggregate",
            )
