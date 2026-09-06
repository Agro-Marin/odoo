from odoo.tests import tagged

from .common import PurchaseTestCommon


@tagged("post_install", "-at_install")
class TestShortReceiptActivity(PurchaseTestCommon):
    """Receiving less than ordered and declining the backorder means the rest is
    never coming. The buyer has to be told.

    `_log_less_quantities_than_expected` (stock/models/stock_picking_backorder.py:122)
    already warns, but it walks `move_dest_ids` DOWN -- it notifies the documents
    waiting for the goods. A purchase order sits UPSTREAM of its receipt, so it
    never appears in those documents. `sale_stock` and `mrp` both override that
    method for their own side; `purchase_stock` did not.
    """

    def _receive_short_without_backorder(self, order, quantity):
        picking = order.picking_ids
        picking.move_ids.quantity = quantity
        picking.move_ids.picked = True
        action = picking.button_validate()
        if action is True:
            # Nothing short, so stock never offers the backorder choice.
            return picking
        wizard = (
            self.env[action["res_model"]].with_context(**action["context"]).create({})
        )
        wizard.action_cancel_backorder()
        return picking

    def test_a_short_receipt_without_backorder_warns_on_the_order(self):
        order = self._create_purchase(self.product, quantity=10.0, confirm=True)
        self.assertFalse(order.activity_ids)

        self._receive_short_without_backorder(order, 6.0)

        self.assertTrue(
            order.activity_ids,
            "the buyer must be warned that the missing 4 units are not coming",
        )
        self.assertEqual(
            order.activity_ids.activity_type_id,
            self.env.ref("mail.mail_activity_data_warning"),
        )

    def test_a_full_receipt_warns_nobody(self):
        order = self._create_purchase(self.product, quantity=10.0, confirm=True)

        self._receive_short_without_backorder(order, 10.0)

        self.assertFalse(order.activity_ids)
