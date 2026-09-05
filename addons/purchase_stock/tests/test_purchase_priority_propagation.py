from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestPurchasePriorityPropagation(TransactionCase):
    """An urgent purchase order must produce an urgent receipt.

    `purchase.order.priority` orders the whole application (`_order = "priority
    desc, id desc"`) but never reached the warehouse, where
    `stock.picking.priority` is what decides which transfer reserves first.
    Both selections are `[("0", "Normal"), ("1", "Urgent")]`, so the value
    carries across as-is.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "Urgent vendor"})
        cls.product = cls.env["product.product"].create(
            {"name": "Stocked thing", "type": "consu", "is_storable": True},
        )

    def _order(self, priority="1"):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "priority": priority,
                "line_ids": [
                    Command.create(
                        {
                            "name": self.product.name,
                            "product_id": self.product.id,
                            "product_qty": 3.0,
                            "price_unit": 10.0,
                        },
                    ),
                ],
            },
        )

    def test_the_receipt_is_created_with_the_order_priority(self):
        order = self._order(priority="1")
        order.action_confirm()

        self.assertTrue(order.picking_ids, "fixture guard: a receipt must exist")
        self.assertEqual(order.picking_ids.priority, "1")

    def test_a_normal_order_creates_a_normal_receipt(self):
        order = self._order(priority="0")
        order.action_confirm()

        self.assertEqual(order.picking_ids.priority, "0")

    def test_raising_the_priority_afterwards_reaches_the_open_receipt(self):
        order = self._order(priority="0")
        order.action_confirm()

        order.priority = "1"

        self.assertEqual(order.picking_ids.priority, "1")

    def test_a_finished_receipt_keeps_its_priority(self):
        order = self._order(priority="0")
        order.action_confirm()
        picking = order.picking_ids
        picking.move_ids.quantity = 3.0
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, "done", "fixture guard")

        order.priority = "1"

        self.assertEqual(
            picking.priority,
            "0",
            "a receipt already processed is history, not a plan to re-order",
        )

    def test_locking_an_urgent_order_does_not_downgrade_its_receipt(self):
        order = self._order(priority="1")
        order.action_confirm()
        self.assertEqual(order.picking_ids.priority, "1", "fixture guard")

        order.action_lock()

        self.assertEqual(order.priority, "0", "fixture guard: locking clears priority")
        self.assertEqual(
            order.picking_ids.priority,
            "1",
            "the warehouse keeps the urgency the buyer asked for; locking the "
            "order is a billing/edit guard, not a change of plan",
        )
