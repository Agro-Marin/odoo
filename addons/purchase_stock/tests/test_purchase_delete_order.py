from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import users

from .common import PurchaseTestCommon


class TestDeleteOrder(PurchaseTestCommon):
    @users("purchase_user")
    def test_00_delete_order(self):
        purchase_order_1 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "state": "done",
            }
        )
        with self.assertRaises(UserError):
            purchase_order_1.unlink()

        purchase_order_2 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "state": "done",
            }
        )
        purchase_order_2.action_cancel()
        self.assertEqual(purchase_order_2.state, "cancel", "PO is cancelled!")
        purchase_order_2.unlink()

        purchase_order_3 = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "state": "draft",
            }
        )
        purchase_order_3.action_cancel()
        self.assertEqual(purchase_order_3.state, "cancel", "PO is cancelled!")
        purchase_order_3.unlink()

    def test_01_delete_propagation(self):
        partner = self.env["res.partner"].create({"name": "My Partner"})

        move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        self.assertEqual(
            move.state,
            "confirmed",
            "Move should be confirmed as there is no quantity in stock",
        )

        purchase_order = self.env["purchase.order"].create(
            {
                "partner_id": partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 1.0,
                            "product_uom_id": self.product.uom_id.id,
                            "propagate_cancel": False,
                        }
                    )
                ],
            }
        )
        purchase_order.action_confirm()

        self.env["report.stock.report_reception"].action_assign(
            move.ids, [1], purchase_order.line_ids.move_ids.ids
        )
        self.assertEqual(
            move.state, "waiting", "Move should be waiting for the linked purchase"
        )
        purchase_order.action_cancel()
        self.assertEqual(
            purchase_order.state, "cancel", "Purchase Order should be canceled"
        )
        self.assertEqual(
            purchase_order.line_ids.move_ids.state,
            "cancel",
            "Purchase order move should be canceled",
        )
        self.assertEqual(
            move.state, "confirmed", "Move state should be recomputed to confimed"
        )
