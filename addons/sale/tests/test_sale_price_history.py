from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSalePriceHistory(TransactionCase):
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
                "sale_ok": True,
            }
        )
        cls.customer_a, cls.customer_b = cls.env["res.partner"].create(
            [{"name": "History customer A"}, {"name": "History customer B"}]
        )
        cls.customer_a_branch = cls.env["res.partner"].create(
            {"name": "History customer A branch", "parent_id": cls.customer_a.id}
        )
        cls.now = fields.Datetime.now()

        cls.order_a = cls._create_order(cls.customer_a, 100.0, 10, cls.uom_unit, 30)
        cls.order_b = cls._create_order(cls.customer_b, 120.0, 5, cls.uom_unit, 60)
        cls.order_branch = cls._create_order(
            cls.customer_a_branch, 1200.0, 2, cls.uom_dozen, 200
        )
        cls.order_quotation = cls._create_order(
            cls.customer_b, 500.0, 1, cls.uom_unit, 5, confirm=False
        )
        cls.target = cls._create_order(
            cls.customer_a, 90.0, 3, cls.uom_unit, 0, confirm=False
        )
        cls.target_line = cls.target.line_ids[0]

    @classmethod
    def _create_order(cls, partner, price, qty, uom, days_ago, confirm=True):
        order = cls.env["sale.order"].create(
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
        return self.env["sale.order.line.price.history"].create(
            {"line_id": self.target_line.id, "product_id": self.product.id, **vals}
        )

    def _shortlist(self, **vals):
        wizard_form = Form(
            self.env["sale.order.line.price.history"].with_context(
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
        self.assertAlmostEqual(wizard.avg_price_unit, round(4000 / 39, 2), places=2)
        self.assertEqual(wizard.avg_sample_count, 3)

    def test_price_direction_is_positive_for_sale(self):
        self.assertEqual(self._create_wizard()._get_price_direction(), 1)

    def test_selling_below_the_average_is_unfavorable(self):
        wizard = self._create_wizard()
        self.assertAlmostEqual(wizard.current_price_unit, 90.0)
        self.assertLess(wizard.divergence_pct, 0)
        self.assertFalse(
            wizard.divergence_favorable,
            "Selling under the period average is never favorable on a sale — "
            "the same divergence a buyer wants",
        )

    def test_shortlist_is_scoped_to_the_commercial_partner(self):
        wizard = self._shortlist(partner_id=self.customer_a)
        self.assertEqual(
            wizard.line_ids.line_id.order_id, self.order_a | self.order_branch
        )

    def test_shortlist_adds_quotations_only_when_asked(self):
        self.assertNotIn(
            self.order_quotation, self._shortlist().line_ids.line_id.order_id
        )
        self.assertIn(
            self.order_quotation,
            self._shortlist(include_draft=True).line_ids.line_id.order_id,
        )

    def test_normalized_price_is_comparable_across_units(self):
        row = self._shortlist().line_ids.filtered(
            lambda record: record.line_id.order_id == self.order_branch
        )
        self.assertAlmostEqual(row.price_unit, 1200.0)
        self.assertAlmostEqual(row.price_unit_normalized, 100.0)

    def test_set_price_converts_into_the_target_line_unit(self):
        row = self._shortlist().line_ids.filtered(
            lambda record: record.line_id.order_id == self.order_branch
        )
        row.action_set_price()
        self.assertAlmostEqual(self.target_line.price_unit, 100.0)

    def test_open_history_targets_the_sale_history_action(self):
        action = self._create_wizard(
            partner_id=self.customer_a.id
        ).action_open_history()
        self.assertEqual(action["res_model"], "sale.order.line")
        self.assertEqual(action["view_mode"], "list,pivot,graph")

    def test_sale_history_views_exist(self):
        for xml_id in (
            "sale.view_sale_order_line_list_history",
            "sale.view_sale_history_pivot",
            "sale.view_sale_history_graph",
        ):
            self.assertTrue(self.env.ref(xml_id), xml_id)

    def test_line_carries_the_hoisted_reference_unit_price(self):
        self.assertAlmostEqual(
            self.order_branch.line_ids.price_unit_product_uom,
            100.0,
            msg="price_unit_product_uom now lives on the shared amount mixin, "
            "so a sale line has it too",
        )

    def test_stored_normalization_columns_exist_on_a_sale_line(self):
        line = self.order_branch.line_ids
        self.assertAlmostEqual(line.price_unit_product_uom, 100.0)
        self.assertAlmostEqual(
            line.price_unit_discounted_taxexc_product_uom,
            line.price_subtotal / line.product_uom_qty,
        )

    def test_single_currency_sample_is_not_capped(self):
        self.env["sale.order"].create(
            {
                "partner_id": self.customer_b.id,
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
        self.assertGreater(wizard.avg_sample_count, 600)
        self.assertFalse(wizard.avg_sample_truncated)

    def test_partner_average_above_the_market_is_favorable_on_a_sale(self):
        self.env["sale.order"].create(
            {
                "partner_id": self.customer_a.id,
                "date_order": self.now - timedelta(days=5),
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 10,
                            "product_uom_id": self.uom_unit.id,
                            "price_unit": 500.0,
                        }
                    )
                ],
            }
        ).action_confirm()
        wizard = self._create_wizard(partner_id=self.customer_a.id)
        self.assertGreater(wizard.partner_avg_price_unit, wizard.avg_price_unit)
        self.assertTrue(
            wizard.partner_divergence_favorable,
            "a customer paying above the market is good news for a seller — "
            "the same divergence a buyer would flag red",
        )

    def test_row_divergence_divides_by_the_same_average_as_the_wizard(self):
        wizard = self._shortlist()
        exact = wizard.avg_price_unit_exact
        for row in wizard.line_ids:
            self.assertAlmostEqual(
                row.divergence_pct,
                (row.price_unit_normalized - exact) / exact,
                places=12,
            )

    def test_sale_order_gained_the_comparison_button(self):
        self.assertTrue(
            self.target.show_comparison,
            "another confirmed order carries this product",
        )
        action = self.target.action_price_comparison()
        self.assertEqual(action["res_model"], "sale.order.line")
        self.assertIn(("state", "=", "done"), action["domain"])

    def test_product_buttons_open_the_line_history(self):
        for record in (self.product, self.product.product_tmpl_id):
            self.assertEqual(
                record.action_view_sales()["res_model"],
                "sale.order.line",
                f"{record._name} reaches the lines, not the sale.report pivot",
            )
