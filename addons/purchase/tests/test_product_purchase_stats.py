from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProductPurchaseStats(TransactionCase):
    """Purchase statistics and order membership exposed on the product."""

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
        # the order must belong to the buyer: group_purchase_user only sees
        # its own orders, so a foreign order would read as zero purchases.
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
        """A user outside the purchase group never sees the statistic."""
        self._order()
        product = self.product.with_user(self.outsider)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_quantity_sums_confirmed_orders(self):
        """Confirmed orders within the year feed the purchased quantity."""
        self._order(qty=4)
        self._order(qty=6)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 10.0)

    def test_draft_orders_are_not_counted(self):
        """An order that was never confirmed does not count."""
        self._order(qty=5, confirm=False)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_orders_older_than_a_year_are_not_counted(self):
        """The statistic only looks back one year (boundary)."""
        order = self._order(qty=7)
        order.date_confirmed = fields.Date.today() - timedelta(days=400)
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        self.assertEqual(product.purchased_product_qty, 0.0)

    def test_membership_flag_follows_the_order_context(self):
        """is_in_purchase_order answers for the order given in context."""
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
        """With no order in context nothing is reported as a member."""
        self._order()
        self.product.invalidate_recordset(["is_in_purchase_order"])
        self.assertFalse(self.product.is_in_purchase_order)

    def test_search_membership_without_context_matches_nothing(self):
        """The search guard returns an empty match instead of a bad domain."""
        self._order()
        matches = self.env["product.product"].search(
            [("is_in_purchase_order", "=", True)],
        )
        self.assertFalse(matches)

    def test_search_membership_with_context(self):
        """With an order in context the search returns its products."""
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
        """Changing the type of an already purchased product warns the user."""
        self._order()
        product = self.product.with_user(self.buyer)
        product.invalidate_recordset(["purchased_product_qty"])
        warning = product._onchange_type_purchase_warn()
        self.assertIn("cannot change", warning["warning"]["message"])

    def test_type_change_is_silent_for_unpurchased_product(self):
        """A product nobody bought changes type without a warning."""
        fresh = self.env["product.product"].create(
            {
                "name": "Untouched",
                "type": "consu",
            }
        )
        self.assertIsNone(fresh._onchange_type_purchase_warn())
