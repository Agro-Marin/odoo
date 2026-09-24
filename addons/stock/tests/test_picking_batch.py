from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.stock.tests.common import WarehousePickingCase


@tagged("post_install", "-at_install")
class TestPickingBatchWrites(WarehousePickingCase):
    def _batch(self, *pickings):
        return self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.type_out.id,
                "picking_ids": [Command.link(picking.id) for picking in pickings],
            }
        )

    def test_several_batches_are_rescheduled_in_one_write(self):
        first = self._picking(self.type_out)
        second = self._picking(self.type_out)
        (first | second).action_confirm()
        batches = self._batch(first) | self._batch(second)
        date_planned = fields.Datetime.now().replace(microsecond=0) + timedelta(days=4)

        batches.write({"date_planned": date_planned})

        self.assertEqual((first | second).mapped("date_planned"), [date_planned] * 2)

    def test_a_cancelled_transfer_does_not_block_rescheduling_its_batch(self):
        open_picking = self._picking(self.type_out)
        cancelled = self._picking(self.type_out)
        (open_picking | cancelled).action_confirm()
        batch = self._batch(open_picking, cancelled)
        cancelled.action_cancel()
        date_planned = fields.Datetime.now().replace(microsecond=0) + timedelta(days=2)

        batch.write({"date_planned": date_planned})

        self.assertEqual(open_picking.date_planned, date_planned)
        self.assertEqual(cancelled.state, "cancel")

    def test_the_batch_responsible_reaches_its_transfers(self):
        picking = self._picking(self.type_out)
        picking.action_confirm()
        batch = self._batch(picking)
        user = self.env["res.users"].create(
            {
                "name": "Batch responsible",
                "login": "audit_batch_responsible",
                "group_ids": [Command.link(self.env.ref("stock.group_stock_user").id)],
            }
        )

        batch.write({"user_id": user.id})

        self.assertEqual(picking.user_id, user)

    def test_validating_a_batch_detaches_its_empty_transfers(self):
        done = self._assigned(self.type_out)
        unstocked = self.env["product.product"].create(
            {"name": "Nothing on hand", "is_storable": True}
        )
        empty = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "move_ids": [
                    Command.create({"product_id": unstocked.id, "product_uom_qty": 5})
                ],
            }
        )
        empty.action_confirm()
        batch = self._batch(done, empty)
        batch.action_confirm()
        done.move_ids.picked = True

        batch.action_done()

        self.assertEqual(done.state, "done")
        self.assertFalse(empty.batch_id)
        self.assertEqual(batch.state, "done")
