from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProductPurchaseStats(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = new_test_user(
            cls.env,
            login="product_stats_buyer",
            groups="base.group_user,purchase.group_purchase_user",
        )
        cls.outsider = new_test_user(
            cls.env,
            login="product_stats_outsider",
            groups="base.group_user",
        )
        cls.vendor = cls.env["res.partner"].create({"name": "Stats vendor"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Counted widget",
                "type": "consu",
                "purchase_ok": True,
            }
        )

    def _order(self, qty=4, confirm=True):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "user_id": self.buyer.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                        }
                    )
                ],
            }
        )
        if confirm:
            order.action_confirm()
        return order

    def test_quantity_hidden_without_the_purchase_group(self):
        self._order()
        product = self.product.with_user(self.outsider)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_quantity_sums_confirmed_orders(self):
        self._order(qty=4)
        self._order(qty=6)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 10.0)

    def test_draft_orders_are_not_counted(self):
        self._order(qty=5, confirm=False)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_orders_older_than_a_year_are_not_counted(self):
        order = self._order(qty=7)
        order.date_confirmed = fields.Date.today() - timedelta(days=400)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_membership_flag_follows_the_order_context(self):
        order = self._order()
        other = self.env["product.product"].create(
            {
                "name": "Never ordered",
                "type": "consu",
            }
        )
        in_order = self.product.with_context(order_id=order.id)
        in_order.invalidate_recordset(["is_in_purchase_order"])
        self.assertTrue(in_order.is_in_purchase_order)

        outside = other.with_context(order_id=order.id)
        outside.invalidate_recordset(["is_in_purchase_order"])
        self.assertFalse(outside.is_in_purchase_order)

    def test_membership_flag_without_context_is_false(self):
        self._order()
        self.product.invalidate_recordset(["is_in_purchase_order"])
        self.assertFalse(self.product.is_in_purchase_order)

    def test_search_membership_without_context_matches_nothing(self):
        self._order()
        matches = self.env["product.product"].search(
            [("is_in_purchase_order", "=", True)],
        )
        self.assertFalse(matches)

    def test_search_membership_with_context(self):
        order = self._order()
        matches = (
            self.env["product.product"]
            .with_context(
                order_id=order.id,
            )
            .search([("is_in_purchase_order", "=", True)])
        )
        self.assertEqual(matches, self.product)

    def test_type_change_warns_once_purchased(self):
        self._order()
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        warning = product._onchange_type_purchase_warn()
        self.assertIn("cannot change", warning["warning"]["message"])

    def test_type_change_is_silent_for_unpurchased_product(self):
        fresh = self.env["product.product"].create(
            {
                "name": "Untouched",
                "type": "consu",
            }
        )
        self.assertIsNone(fresh._onchange_type_purchase_warn())
