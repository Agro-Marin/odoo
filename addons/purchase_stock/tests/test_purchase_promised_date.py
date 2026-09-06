from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import PurchaseTestCommon


@tagged("post_install", "-at_install")
class TestPurchasePromisedDate(PurchaseTestCommon):
    """The vendor is graded against what it promised, not against the buyer's
    running estimate.

    `date_commitment` is editable after confirmation on purpose
    (`purchase_stock/models/purchase_order_line.py:576-585`). While the on-time
    rate read that same field, pushing the expected arrival back because the
    vendor said it would be late also erased the lateness from its record.
    """

    def _late_order(self):
        """An order the vendor promised for 10 days ago and has not delivered."""
        order = self._create_purchase(self.product, quantity=5.0, confirm=False)
        order.line_ids.date_commitment = fields.Datetime.now() - timedelta(days=10)
        order.action_confirm()
        return order

    def test_confirmation_freezes_the_promised_date(self):
        order = self._late_order()
        line = order.line_ids
        self.assertEqual(line.date_promised, line.date_commitment)

        line.date_commitment = fields.Datetime.now() + timedelta(days=5)
        self.assertNotEqual(
            line.date_promised,
            line.date_commitment,
            "moving the expected arrival must not move the promise",
        )

    def test_a_draft_order_has_no_promised_date(self):
        order = self._create_purchase(self.product, quantity=5.0, confirm=False)
        self.assertFalse(order.line_ids.date_promised)

    def test_moving_the_expected_arrival_does_not_clear_the_vendor_record(self):
        order = self._late_order()
        # The buyer learns the goods are late and pushes the expected arrival.
        order.line_ids.date_commitment = fields.Datetime.now() + timedelta(days=5)
        self._receive(order)
        order.line_ids.flush_recordset()
        order.picking_ids.move_ids.flush_recordset()
        self.vendor.invalidate_recordset(fnames=["on_time_rate"])
        self.assertEqual(
            self.vendor.on_time_rate,
            0.0,
            "a delivery after the promised date is late, whatever the buyer "
            "moved the expected arrival to",
        )

    def test_a_delivery_within_the_promise_still_counts_as_on_time(self):
        order = self._create_purchase(self.product, quantity=5.0, confirm=False)
        order.line_ids.date_commitment = fields.Datetime.now() + timedelta(days=10)
        order.action_confirm()
        self._receive(order)
        order.line_ids.flush_recordset()
        order.picking_ids.move_ids.flush_recordset()
        self.vendor.invalidate_recordset(fnames=["on_time_rate"])
        self.assertEqual(self.vendor.on_time_rate, 100.0)

    def test_a_line_added_after_confirmation_is_promised_too(self):
        """The vendor accepted the extra line, so it is graded on it as well."""
        order = self._late_order()
        added = self.env["purchase.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_qty": 2.0,
                "product_uom_id": self.product.uom_id.id,
                "price_unit": 100.0,
            },
        )
        self.assertTrue(
            added.date_promised,
            "a line added to a confirmed order must count towards the rate",
        )

    def test_the_receipt_deadline_still_follows_the_expected_arrival(self):
        """Deliberate scope cut, pinned here.

        Upstream also makes the promised date drive `move.date_deadline` and the
        expected arrival drive `move.date`. That half is not taken: four existing
        tests here pin deadline propagation from the expected arrival, and it
        feeds stock's reservation ordering and the MTO chain. The promise is a
        vendor record in this fork, not a warehouse instruction.
        """
        order = self._late_order()
        moves = order.picking_ids.move_ids
        pushed = fields.Datetime.now() + timedelta(days=5)
        order.line_ids.date_commitment = pushed
        self.assertEqual(moves.date_deadline, pushed)
