from odoo.tests import tagged

from .common import PurchaseTestCommon


@tagged("post_install", "-at_install")
class TestPurchasePriorityPropagation(PurchaseTestCommon):
    """Marking an order urgent has to reach the people who do the work.

    `stock.picking._order` is `priority desc, date_planned asc, id desc`
    (stock/models/stock_picking.py:28) and `stock.move.priority` is computed
    from `picking_id.priority` (stock/models/stock_move.py:718-721), so the
    receipt's priority already drives the warehouse's queue. Only the hand-off
    from the order was missing.
    """

    def test_confirming_an_urgent_order_gives_an_urgent_receipt(self):
        order = self._create_purchase(self.product, quantity=3.0, confirm=False)
        order.priority = "1"
        order.action_confirm()

        self.assertEqual(order.picking_ids.priority, "1")

    def test_raising_the_priority_afterwards_reaches_the_receipt(self):
        order = self._create_purchase(self.product, quantity=3.0, confirm=True)
        self.assertEqual(order.picking_ids.priority, "0")

        order.priority = "1"

        self.assertEqual(order.picking_ids.priority, "1")

    def test_a_normal_order_leaves_the_receipt_normal(self):
        order = self._create_purchase(self.product, quantity=3.0, confirm=True)
        self.assertEqual(order.priority, "0")
        self.assertEqual(order.picking_ids.priority, "0")
