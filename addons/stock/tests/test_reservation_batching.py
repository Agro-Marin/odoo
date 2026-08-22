from odoo import Command
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestReservationBatching(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Res P", "is_storable": True, "uom_id": cls.uom_unit.id}
        )
        cls.serial_product = cls.env["product.product"].create(
            {"name": "Res SN", "is_storable": True, "tracking": "serial"}
        )
        cls.lot_product = cls.env["product.product"].create(
            {"name": "Res Lot", "is_storable": True, "tracking": "lot"}
        )

    def _stock(self, product, qty, location=None, lot=None):
        self.env["stock.quant"]._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot
        )

    def _out_move(self, product, qty, uom=None):
        return self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": (uom or product.uom_id).id,
                "product_uom_qty": qty,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

    def _reserved(self, product, location=None):
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "child_of", (location or self.stock_location).id),
            ]
        )
        return sum(quants.mapped("reserved_quantity"))

    def test_batch_divides_insufficient_stock_in_order(self):
        self._stock(self.product, 15.0)
        moves = (
            self._out_move(self.product, 10.0)
            | self._out_move(self.product, 10.0)
            | self._out_move(self.product, 10.0)
        )
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(moves[0].state, "assigned")
        self.assertEqual(moves[0].quantity, 10.0)
        self.assertEqual(moves[1].state, "partially_available")
        self.assertEqual(moves[1].quantity, 5.0)
        self.assertEqual(moves[2].state, "confirmed")
        self.assertEqual(moves[2].quantity, 0.0)
        self.assertEqual(self._reserved(self.product), 15.0)

    def test_batch_serves_everyone_when_stock_suffices(self):
        self._stock(self.product, 100.0)
        moves = (
            self._out_move(self.product, 10.0)
            | self._out_move(self.product, 20.0)
            | self._out_move(self.product, 30.0)
        )
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(moves.mapped("state"), ["assigned"] * 3)
        self.assertEqual(moves.mapped("quantity"), [10.0, 20.0, 30.0])
        self.assertEqual(self._reserved(self.product), 60.0)

    def test_batch_spans_several_quants_in_removal_order(self):
        self._stock(self.product, 6.0, location=self.shelf_1)
        self._stock(self.product, 6.0, location=self.shelf_2)
        moves = self._out_move(self.product, 8.0) | self._out_move(self.product, 8.0)
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(moves[0].quantity, 8.0)
        self.assertEqual(moves[1].quantity, 4.0)
        self.assertEqual(moves[1].state, "partially_available")
        self.assertEqual(self._reserved(self.product), 12.0)

    def test_serial_moves_get_one_line_per_unit(self):
        lots = self.env["stock.lot"].create(
            [
                {"name": f"res-sn-{i}", "product_id": self.serial_product.id}
                for i in range(3)
            ]
        )
        for lot in lots:
            self._stock(self.serial_product, 1.0, lot=lot)

        moves = self._out_move(self.serial_product, 2.0) | self._out_move(
            self.serial_product, 2.0
        )
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(len(moves[0].move_line_ids), 2)
        self.assertEqual(moves[0].state, "assigned")
        self.assertEqual(len(moves[1].move_line_ids), 1)
        self.assertEqual(moves[1].state, "partially_available")
        used = moves.move_line_ids.lot_id
        self.assertEqual(len(used), 3)
        self.assertEqual(self._reserved(self.serial_product), 3.0)

    def test_lot_moves_share_a_lot_across_the_batch(self):
        lot = self.env["stock.lot"].create(
            {"name": "res-lot-a", "product_id": self.lot_product.id}
        )
        self._stock(self.lot_product, 12.0, lot=lot)
        moves = self._out_move(self.lot_product, 8.0) | self._out_move(
            self.lot_product, 8.0
        )
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(moves[0].quantity, 8.0)
        self.assertEqual(moves[1].quantity, 4.0)
        self.assertEqual(moves.move_line_ids.lot_id, lot)
        self.assertEqual(self._reserved(self.lot_product), 12.0)

    def test_a_move_in_a_foreign_uom_reserves_the_product_quantity(self):
        self._stock(self.product, 30.0)
        move = self._out_move(self.product, 2.0, uom=self.uom_dozen)
        move._action_confirm()
        move._action_assign()

        self.assertEqual(move.state, "assigned")
        self.assertEqual(move.quantity, 2.0)
        self.assertEqual(self._reserved(self.product), 24.0)

    def test_a_partially_reserved_move_tops_up_rather_than_duplicating(self):
        self._stock(self.product, 4.0)
        move = self._out_move(self.product, 10.0)
        move._action_confirm()
        move._action_assign()
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.quantity, 4.0)

        self._stock(self.product, 6.0)
        move._action_assign()
        self.assertEqual(
            len(move.move_line_ids), 1, "the existing line must be topped up"
        )
        self.assertEqual(move.quantity, 10.0)
        self.assertEqual(move.state, "assigned")
        self.assertEqual(self._reserved(self.product), 10.0)

    def test_bypassed_moves_reserve_nothing_on_quants(self):
        self._stock(self.product, 5.0)
        receipt = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 7.0,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        delivery = self._out_move(self.product, 5.0)
        moves = receipt | delivery
        moves._action_confirm()
        moves._action_assign()

        self.assertEqual(receipt.state, "assigned")
        self.assertEqual(receipt.quantity, 7.0)
        self.assertEqual(delivery.state, "assigned")
        self.assertEqual(delivery.quantity, 5.0)
        self.assertEqual(self._reserved(self.product), 5.0)

    def test_chained_moves_distribute_what_their_origin_brought(self):
        self._stock(self.product, 10.0)
        pick = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 6.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
            }
        )
        pick._action_confirm()
        pick._action_assign()
        pick.picked = True
        pick._action_done()

        ship_a = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 4.0,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "move_orig_ids": [Command.link(pick.id)],
            }
        )
        ship_b = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 4.0,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "move_orig_ids": [Command.link(pick.id)],
            }
        )
        ships = ship_a | ship_b
        ships._action_confirm()
        ships._action_assign()

        self.assertEqual(
            ship_a.quantity + ship_b.quantity,
            6.0,
            "the two legs together may not exceed what the pick brought",
        )
        self.assertEqual(ship_a.quantity, 4.0)
        self.assertEqual(ship_b.quantity, 2.0)
        self.assertEqual(self._reserved(self.product, location=self.pack_location), 6.0)

    def test_reassigning_an_already_assigned_batch_is_idempotent(self):
        self._stock(self.product, 20.0)
        moves = self._out_move(self.product, 5.0) | self._out_move(self.product, 5.0)
        moves._action_confirm()
        moves._action_assign()
        reserved_once = self._reserved(self.product)

        moves._action_assign()
        self.assertEqual(self._reserved(self.product), reserved_once)
        self.assertEqual(moves.mapped("quantity"), [5.0, 5.0])
        self.assertEqual(len(moves.move_line_ids), 2)

    def test_a_batch_creates_its_move_lines_in_one_call(self):
        self._stock(self.product, 500.0)
        moves = self.env["stock.move"].browse()
        for _i in range(6):
            moves |= self._out_move(self.product, 5.0)
        moves._action_confirm()

        calls = []
        MoveLine = type(self.env["stock.move.line"])
        original_create = MoveLine.create

        def counting_create(self_ml, vals_list):
            if isinstance(vals_list, dict):
                vals_list = [vals_list]
            if vals_list:
                calls.append(len(vals_list))
            return original_create(self_ml, vals_list)

        self.patch(MoveLine, "create", counting_create)
        moves._action_assign()

        self.assertEqual(
            len(calls),
            1,
            f"six moves must create their lines in one call, got {len(calls)}: {calls}",
        )
        self.assertEqual(calls[0], 6)
        self.assertEqual(moves.mapped("state"), ["assigned"] * 6)
        self.assertEqual(self._reserved(self.product), 30.0)

    def test_the_ledger_is_scoped_to_one_run(self):
        self._stock(self.product, 10.0)
        move = self._out_move(self.product, 4.0)
        move._action_confirm()
        move._action_assign()
        self.assertIsNone(self.env.context.get("reservation_ledger"))
        self.assertEqual(self._reserved(self.product), 4.0)

        move2 = self._out_move(self.product, 8.0)
        move2._action_confirm()
        move2._action_assign()
        self.assertEqual(move2.quantity, 6.0)
        self.assertEqual(move2.state, "partially_available")
        self.assertEqual(self._reserved(self.product), 10.0)
