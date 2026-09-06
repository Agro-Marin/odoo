from odoo.tests import tagged

from .common import PurchaseTestCommon


@tagged("post_install", "-at_install")
class TestReceiptOriginVendorRef(PurchaseTestCommon):
    """The warehouse receives against the vendor's delivery note, which carries
    the VENDOR's number, not ours.

    With only `P00042` in the origin, matching the paper in the driver's hand to
    the transfer on screen means opening the order to read `partner_ref`.
    """

    def test_the_receipt_origin_carries_the_vendor_reference(self):
        order = self._create_purchase(self.product, quantity=3.0, confirm=False)
        order.partner_ref = "ALB-778"
        order.action_confirm()

        picking = order.picking_ids
        self.assertIn(order.name, picking.origin)
        self.assertIn(
            "ALB-778",
            picking.origin,
            "the vendor's own reference must reach the receipt",
        )

    def test_the_move_origin_carries_it_too(self):
        """The move keeps its own origin, so it has to be set in both places."""
        order = self._create_purchase(self.product, quantity=3.0, confirm=False)
        order.partner_ref = "ALB-778"
        order.action_confirm()

        self.assertIn("ALB-778", order.picking_ids.move_ids.origin)

    def test_an_order_without_a_vendor_reference_is_unchanged(self):
        order = self._create_purchase(self.product, quantity=3.0, confirm=False)
        self.assertFalse(order.partner_ref)
        order.action_confirm()

        self.assertEqual(order.picking_ids.origin, order.name)
