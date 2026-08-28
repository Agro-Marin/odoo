from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PurchaseTestCommon


class AuditCommon(PurchaseTestCommon):
    def _new_product(self, name="Audit product", **vals):
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "purchase_ok": True,
                "uom_id": self.uom.id,
                "standard_price": 10.0,
                **vals,
            },
        )


@tagged("post_install", "-at_install")
class TestPurchaseOrderWriteGuards(AuditCommon):
    def _make_order(self, confirm=False):
        product = self._new_product()
        self._use_route_buy(product)
        return self._create_purchase(product, quantity=10.0, confirm=confirm)

    def test_write_lines_while_confirming_does_not_raise(self):
        order = self._make_order()
        order.write(
            {
                "state": "done",
                "line_ids": [Command.update(order.line_ids.id, {"product_qty": 4.0})],
            },
        )
        self.assertEqual(order.state, "done")
        self.assertEqual(order.line_ids.product_qty, 4.0)

    def test_write_lines_on_several_orders_does_not_raise(self):
        first, second = self._make_order(confirm=True), self._make_order(confirm=True)
        (first | second).write(
            {
                "line_ids": [
                    Command.update(first.line_ids.id, {"product_qty": 2.0}),
                    Command.update(second.line_ids.id, {"product_qty": 3.0}),
                ],
            },
        )
        self.assertEqual(first.line_ids.product_qty, 2.0)
        self.assertEqual(second.line_ids.product_qty, 3.0)

    def test_decrease_is_logged_for_every_order_not_just_the_last(self):
        first, second = self._make_order(confirm=True), self._make_order(confirm=True)
        logged = []
        self.patch(
            type(first),
            "_log_decrease_ordered_quantity",
            lambda records, quantities: logged.append(records.id),
        )
        (first | second).write(
            {
                "line_ids": [
                    Command.update(first.line_ids.id, {"product_qty": 2.0}),
                    Command.update(second.line_ids.id, {"product_qty": 3.0}),
                ],
            },
        )
        self.assertEqual(sorted(logged), sorted([first.id, second.id]))


@tagged("post_install", "-at_install")
class TestPurchaseOrderLineWriteGuards(AuditCommon):
    def test_price_reaches_the_moves_when_quantity_is_resent_unchanged(self):
        product = self._new_product()
        self._use_route_buy(product)
        order = self._create_purchase(product, quantity=10.0, price_unit=10.0)
        self.assertEqual(order.line_ids.move_ids.mapped("price_unit"), [10.0])

        order.line_ids.write({"price_unit": 20.0, "product_qty": 10.0})

        self.assertEqual(
            order.line_ids.move_ids.mapped("price_unit"),
            [20.0],
            "a price change must reach the moves even when product_qty is resent "
            "with the value it already had",
        )


@tagged("post_install", "-at_install")
class TestVendorOnTimeRate(AuditCommon):
    def test_on_time_rate_survives_a_cleared_expected_arrival(self):
        product = self._new_product()
        self._use_route_buy(product)
        order = self._create_purchase(product, quantity=5.0, receive=True)

        order.line_ids.write({"date_commitment": False})
        self.env.invalidate_all()

        self.assertFalse(order.line_ids.date_commitment)
        self.assertIsInstance(order.partner_id.on_time_rate, float)
        self.assertIsInstance(order.on_time_rate, float)


@tagged("post_install", "-at_install")
class TestOrderpointVendorWithoutBuyRoute(AuditCommon):
    def test_setting_a_vendor_without_a_buy_route_raises_a_user_error(self):
        product = self._new_product()
        seller = self.env["product.supplierinfo"].create(
            {
                "partner_id": self.vendor.id,
                "product_tmpl_id": product.product_tmpl_id.id,
                "price": 7.0,
            },
        )
        self.env["stock.rule"].sudo().with_context(active_test=False).search(
            [("action", "=", "buy")],
        ).active = False
        self.env.flush_all()
        self.assertFalse(self.env["stock.rule"].sudo()._search_buy_rules())

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "warehouse_id": self.warehouse.id,
                "product_min_qty": 1,
                "product_max_qty": 5,
            },
        )
        orderpoint.route_id = False
        self.env.flush_all()

        with self.assertRaises(UserError):
            orderpoint.supplier_id = seller
            self.env.flush_all()


@tagged("post_install", "-at_install")
class TestPurchaseSuggestScope(AuditCommon):
    def test_suggest_does_not_build_a_line_for_every_catalogue_entry(self):
        self.env["product.product"].create(
            [
                {
                    "name": f"Suggest filler {i}",
                    "is_storable": True,
                    "purchase_ok": True,
                }
                for i in range(40)
            ],
        )
        order = self._create_purchase(self._new_product(), quantity=1.0, confirm=False)
        order.line_ids.unlink()
        self.env.flush_all()
        self.env.invalidate_all()

        context = {
            "suggest_based_on": "30_days",
            "suggest_days": 7,
            "suggest_percent": 100,
        }
        with self.assertQueryCount(__system__=25):
            order.with_context(**context).action_purchase_order_suggest()

    def test_suggest_still_adds_and_prunes(self):
        needed = self._new_product("Needed product")
        self.env["stock.quant"]._update_available_quantity(
            needed, self.warehouse.lot_stock_id, -8
        )
        context = {
            "suggest_based_on": "actual_demand",
            "suggest_percent": 100,
            "warehouse_id": self.warehouse.id,
        }
        order = self._create_purchase(needed, quantity=1.0, confirm=False)
        order.line_ids.unlink()
        self.env.invalidate_all()

        order.with_context(**context).action_purchase_order_suggest()
        self.assertIn(needed, order.line_ids.product_id)

        stale = self._new_product("Stale product")
        order.with_context(**context).write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": stale.id,
                            "product_qty": 3.0,
                            "price_unit": 1.0,
                        },
                    ),
                ],
            },
        )
        order.with_context(**context).action_purchase_order_suggest()
        self.assertNotIn(stale, order.line_ids.product_id)


@tagged("post_install", "-at_install")
class TestBuyRuleHelpers(AuditCommon):
    def test_route_and_rule_predicates_answer_different_questions(self):
        buy_rule = self.warehouse.buy_pull_id
        self.assertTrue(buy_rule.route_id._has_buy_rule())
        self.assertTrue(buy_rule._has_buy_action())

        other_rule = buy_rule.route_id.rule_ids.filtered(
            lambda rule: rule.action != "buy",
        )
        if other_rule:
            self.assertFalse(
                other_rule._has_buy_action(),
                "a non-buy rule must not answer for its route",
            )
            self.assertTrue(other_rule.route_id._has_buy_rule())

    def test_buy_rule_search_honours_its_scopes(self):
        rules = self.env["stock.rule"]
        self.assertIn(self.warehouse.buy_pull_id, rules._search_buy_rules())
        self.assertIn(
            self.warehouse.buy_pull_id,
            rules._search_buy_rules(warehouse=self.warehouse),
        )
        self.assertIn(
            self.warehouse.buy_pull_id,
            rules._search_buy_rules(company=self.company),
        )
        self.assertFalse(rules._search_buy_rules(picking_code="outgoing"))
