from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestCompletionSequence(TestStockCommon):
    def _receipt(self, qty):
        return self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": qty,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.warehouse_1.in_type_id.id,
            }
        )

    def test_done_order_beats_creation_order(self):
        first_created = self._receipt(1.0)
        second_created = self._receipt(2.0)
        self.assertFalse(first_created.completion_sequence)

        for move in (second_created, first_created):
            move._action_confirm()
            move.quantity = move.product_uom_qty
            move.picked = True
            move._action_done()

        self.assertTrue(second_created.completion_sequence)
        self.assertLess(
            second_created.completion_sequence,
            first_created.completion_sequence,
            "the move done first must sort first, whatever its id",
        )
        self.assertLess(first_created.id, second_created.id)

    def test_a_move_created_done_is_sequenced_too(self):
        move = self._receipt(1.0)
        move._action_confirm()
        move.quantity = 1.0
        move.picked = True
        move._action_done()
        extra = self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1.0,
                "quantity": 1.0,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.warehouse_1.in_type_id.id,
                "state": "done",
            }
        )
        self.assertGreater(extra.completion_sequence, move.completion_sequence)

    def test_copy_does_not_carry_the_sequence(self):
        move = self._receipt(1.0)
        move._action_confirm()
        move.quantity = 1.0
        move.picked = True
        move._action_done()
        # A plain copy keeps its picking, and a move joining a done picking is
        # forced done by _prepare_create_vals, so it is sequenced -- with its
        # own number, never the original's.
        joined = move.copy()
        self.assertEqual(joined.state, "done")
        self.assertTrue(joined.completion_sequence)
        self.assertNotEqual(joined.completion_sequence, move.completion_sequence)
        detached = move.copy({"picking_id": False})
        self.assertNotEqual(detached.state, "done")
        self.assertFalse(detached.completion_sequence)
