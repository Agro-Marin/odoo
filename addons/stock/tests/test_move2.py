from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form

from odoo.addons.stock.tests.common import TestStockCommon


class TestPickShip(TestStockCommon):
    def create_pick_ship(self):
        picking_client = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        dest = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_client.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "state": "waiting",
                "procure_method": "make_to_order",
            }
        )

        picking_pick = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "move_dest_ids": [Command.link(dest.id)],
                "state": "confirmed",
            }
        )
        return picking_pick, picking_client

    def create_pick_pack_ship(self):
        picking_ship = self.env["stock.picking"].create(
            {
                "location_id": self.output_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        ship = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_ship.id,
                "location_id": self.output_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        picking_pack = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.output_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        pack = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_pack.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.output_location.id,
                "move_dest_ids": [Command.link(ship.id)],
            }
        )

        picking_pick = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "move_dest_ids": [Command.link(pack.id)],
                "state": "confirmed",
            }
        )
        return picking_pick, picking_pack, picking_ship

    def test_unreserve_only_required_quantity(self):
        product_unreserve = self.env["product.product"].create(
            {
                "name": "product unreserve",
                "is_storable": True,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product_unreserve, self.stock_location, 4.0
        )
        quants = self.env["stock.quant"]._gather(
            product_unreserve, self.stock_location, strict=True
        )
        self.assertEqual(quants[0].reserved_quantity, 0)
        move = self.MoveObj.create(
            {
                "product_id": product_unreserve.id,
                "product_uom_qty": 3,
                "product_uom_id": product_unreserve.uom_id.id,
                "state": "confirmed",
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_assign()
        self.assertEqual(quants[0].reserved_quantity, 3)
        move_2 = self.MoveObj.create(
            {
                "product_id": product_unreserve.id,
                "product_uom_qty": 2,
                "quantity": 2,
                "product_uom_id": product_unreserve.uom_id.id,
                "state": "confirmed",
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move_2._action_assign()
        move_2.picked = True
        move_2._action_done()
        quants = self.env["stock.quant"]._gather(
            product_unreserve, self.stock_location, strict=True
        )
        self.assertEqual(quants[0].reserved_quantity, 2)

    def test_mto_moves(self):
        picking_pick, picking_client = self.create_pick_ship()

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        self.assertEqual(
            picking_client.state,
            "assigned",
            "The state of the client should be assigned",
        )

        picking_client.move_ids[0].move_line_ids[0].quantity = 5
        picking_client.move_ids[0].picked = True
        picking_client._action_done()

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", picking_client.id)]
        )
        self.assertEqual(
            backorder.state, "confirmed", "Backorder should be waiting for reservation"
        )

    def test_mto_to_mts(self):
        picking_pick, picking_ship = self.create_pick_ship()
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": self.stock_location.id,
                "quantity": 10,
            }
        )
        (picking_pick + picking_ship).action_assign()
        self.assertEqual(picking_pick.state, "assigned")
        self.assertEqual(picking_ship.state, "waiting")
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_order")
        picking_pick.location_dest_id = self.output_location
        picking_pick.move_ids.location_dest_id = self.output_location
        picking_pick.move_ids.picked = True
        picking_pick.button_validate()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_ship.state, "confirmed")
        self.assertEqual(picking_ship.location_id.id, self.pack_location.id)
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_stock")

    def test_mto_to_mts_2(self):
        picking_pick, picking_ship = self.create_pick_ship()
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": self.stock_location.id,
                "quantity": 10,
            }
        )
        (picking_pick + picking_ship).action_assign()
        self.assertEqual(picking_pick.state, "assigned")
        self.assertEqual(picking_ship.state, "waiting")
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_order")
        picking_pick.move_ids.propagate_cancel = False
        picking_pick.action_cancel()
        self.assertEqual(picking_pick.state, "cancel")
        self.assertEqual(picking_ship.state, "confirmed")
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_stock")

    def test_mto_to_mts_3(self):
        picking_pick, picking_ship = self.create_pick_ship()
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": self.stock_location.id,
                "quantity": 10,
            }
        )
        (picking_pick + picking_ship).action_assign()
        self.assertEqual(picking_pick.state, "assigned")
        self.assertEqual(picking_ship.state, "waiting")
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_order")
        picking_ship.location_id = self.output_location
        picking_ship.move_ids.location_id = self.output_location
        picking_pick.move_ids.picked = True
        picking_pick.button_validate()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_ship.state, "confirmed")
        self.assertEqual(picking_pick.location_dest_id.id, self.pack_location.id)
        self.assertEqual(picking_ship.move_ids.procure_method, "make_to_stock")

    def test_mto_moves_transfer(self):
        picking_pick, picking_client = self.create_pick_ship()
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 5.0
        )

        self.assertEqual(
            len(self.env["stock.quant"]._gather(self.productA, self.stock_location)),
            1.0,
        )
        self.assertEqual(
            len(self.env["stock.quant"]._gather(self.productA, self.pack_location)), 1.0
        )

        (picking_pick + picking_client).action_assign()

        move_pick = picking_pick.move_ids
        move_cust = picking_client.move_ids
        self.assertEqual(move_pick.state, "assigned")
        self.assertEqual(picking_pick.state, "assigned")
        self.assertEqual(move_cust.state, "waiting")
        self.assertEqual(
            picking_client.state,
            "waiting",
            "The picking should not assign what it does not have",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            0.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            5.0,
        )

        move_pick.move_line_ids[0].quantity = 10.0
        move_pick.picked = True
        picking_pick._action_done()

        self.assertEqual(move_pick.state, "done")
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(move_cust.state, "assigned")
        self.assertEqual(
            picking_client.state,
            "assigned",
            "The picking should not assign what it does not have",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            0.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            5.0,
        )
        self.assertEqual(
            sum(
                self.env["stock.quant"]
                ._gather(self.productA, self.stock_location)
                .mapped("quantity")
            ),
            0.0,
        )
        self.assertEqual(
            len(self.env["stock.quant"]._gather(self.productA, self.pack_location)), 1.0
        )

    def test_mto_moves_return(self):
        picking_pick, picking_client = self.create_pick_ship()
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )

        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_client.state, "assigned")

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_pick.ids,
                active_id=picking_pick.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 2.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_pick = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )
        return_pick.move_ids[0].move_line_ids[0].quantity = 2.0
        return_pick.move_ids[0].picked = True
        return_pick._action_done()
        self.assertEqual(picking_client.state, "confirmed")

    def test_mto_moves_extra_qty(self):
        picking_pick, picking_client = self.create_pick_ship()
        self.productA.route_ids = [Command.link(self.route_mto.id)]
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 15.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_client.state, "assigned")

        picking_client.move_ids[0].move_line_ids[0].quantity = 15.0
        picking_client.move_ids[0].picked = True
        picking_client.move_ids._action_done()
        self.assertEqual(len(picking_client.move_ids), 1)
        move = picking_client.move_ids
        self.assertEqual(move.procure_method, "make_to_order")
        self.assertEqual(move.product_uom_qty, 10.0)
        self.assertEqual(move.quantity, 15.0)

    def test_mto_moves_return_extra(self):
        picking_pick, picking_client = self.create_pick_ship()
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )

        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_client.state, "assigned")

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_pick.ids,
                active_id=picking_pick.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 12.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_pick = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )

        self.assertAlmostEqual(return_pick.move_ids.product_uom_qty, 12.0)
        self.assertAlmostEqual(return_pick.move_ids.quantity, 10.0)

    def test_mto_resupply_cancel_ship(self):
        picking_pick, picking_pack, picking_ship = self.create_pick_pack_ship()
        warehouse_1 = self.warehouse_1
        warehouse_1.delivery_steps = "pick_pack_ship"
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Small Warehouse", "code": "SWH"}
        )
        warehouse_1.resupply_wh_ids = [Command.set([warehouse_2.id])]
        resupply_route = self.env["stock.route"].search(
            [
                ("supplier_wh_id", "=", warehouse_2.id),
                ("supplied_wh_id", "=", warehouse_1.id),
            ]
        )
        self.assertTrue(resupply_route)
        self.productA.route_ids = [Command.set([resupply_route.id, self.route_mto.id])]

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )

        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        picking_pack.action_assign()
        picking_pack.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pack.move_ids[0].picked = True
        picking_pack._action_done()

        picking_ship.action_cancel()
        picking_ship.move_ids.procure_method = "make_to_order"

        self.env["stock.scheduler"].run()
        next_activity = self.env["mail.activity"].search(
            [
                ("res_model", "=", "product.template"),
                ("res_id", "=", self.productA.product_tmpl_id.id),
            ]
        )
        self.assertEqual(picking_ship.state, "cancel")
        self.assertFalse(
            next_activity,
            "If a next activity has been created if means that scheduler failed\
        and the end of this test do not have sense.",
        )
        self.assertEqual(
            len(picking_ship.move_ids.mapped("move_orig_ids")),
            0,
            "Scheduler should not create picking pack and pick since ship has been manually cancelled.",
        )

    def test_no_backorder_1(self):
        picking_pick, picking_client = self.create_pick_ship()

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 5.0
        picking_pick.move_ids[0].picked = True

        picking_pick._action_done()
        picking_pick_backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", picking_pick.id)]
        )
        self.assertEqual(picking_pick_backorder.state, "confirmed")
        self.assertEqual(picking_pick_backorder.move_ids.product_qty, 5.0)

        self.assertEqual(picking_client.state, "assigned")

        picking_pick_backorder.action_cancel()
        self.assertEqual(picking_client.state, "assigned")

    def test_edit_done_chained_move(self):
        picking_pick, picking_client = self.create_pick_ship()

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        self.assertEqual(
            picking_pick.state, "done", "The state of the pick should be done"
        )
        self.assertEqual(
            picking_client.state,
            "assigned",
            "The state of the client should be assigned",
        )
        self.assertEqual(
            picking_pick.move_ids.quantity, 10.0, "Wrong quantity for pick move"
        )
        self.assertEqual(
            picking_client.move_ids.product_qty,
            10.0,
            "Wrong initial demand for client move",
        )
        self.assertEqual(
            picking_client.move_ids.quantity,
            10.0,
            "Wrong quantity already reserved for client move",
        )

        picking_pick.move_ids[0].move_line_ids[0].quantity = 5.0
        self.assertEqual(
            picking_pick.state, "done", "The state of the pick should be done"
        )
        self.assertEqual(
            picking_client.state,
            "assigned",
            "The state of the client should be partially available",
        )
        self.assertEqual(
            picking_pick.move_ids.quantity, 5.0, "Wrong quantity for pick move"
        )
        self.assertEqual(
            picking_client.move_ids.product_qty,
            10.0,
            "Wrong initial demand for client move",
        )
        self.assertEqual(
            picking_client.move_ids.quantity,
            5.0,
            "Wrong quantity already reserved for client move",
        )

        picking_client.action_assign()

    def test_edit_done_chained_move_with_lot(self):
        self.productA.tracking = "lot"
        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
            }
        )
        lot2 = self.env["stock.lot"].create(
            {
                "name": "lot2",
                "product_id": self.productA.id,
            }
        )
        picking_pick, picking_client = self.create_pick_ship()

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].write(
            {
                "quantity": 10.0,
                "lot_id": lot1.id,
            }
        )
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        self.assertEqual(
            picking_pick.state, "done", "The state of the pick should be done"
        )
        self.assertEqual(
            picking_client.state,
            "assigned",
            "The state of the client should be assigned",
        )
        self.assertEqual(
            picking_pick.move_ids.quantity, 10.0, "Wrong quantity for pick move"
        )
        self.assertEqual(
            picking_client.move_ids.product_qty,
            10.0,
            "Wrong initial demand for client move",
        )
        self.assertEqual(
            picking_client.move_ids.move_line_ids.lot_id,
            lot1,
            "Wrong lot for client move line",
        )
        self.assertEqual(
            picking_client.move_ids.quantity,
            10.0,
            "Wrong quantity already reserved for client move",
        )

        picking_pick.move_ids[0].move_line_ids[0].lot_id = lot2.id
        self.assertEqual(
            picking_pick.state, "done", "The state of the pick should be done"
        )
        self.assertEqual(
            picking_client.state,
            "assigned",
            "The state of the client should be partially available",
        )
        self.assertEqual(
            picking_pick.move_ids.quantity, 10.0, "Wrong quantity for pick move"
        )
        self.assertEqual(
            picking_client.move_ids.product_qty,
            10.0,
            "Wrong initial demand for client move",
        )
        self.assertEqual(
            picking_client.move_ids.move_line_ids.lot_id,
            lot2,
            "Wrong lot for client move line",
        )
        self.assertEqual(
            picking_client.move_ids.quantity,
            10.0,
            "Wrong quantity already reserved for client move",
        )

        picking_client.action_assign()

    def test_chained_move_with_uom(self):
        picking_client = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        dest = self.MoveObj.create(
            {
                "product_id": self.gB.id,
                "product_uom_qty": 5,
                "product_uom_id": self.uom_kg.id,
                "picking_id": picking_client.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "state": "waiting",
            }
        )

        picking_pick = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        self.MoveObj.create(
            {
                "product_id": self.gB.id,
                "product_uom_qty": 5,
                "product_uom_id": self.uom_kg.id,
                "picking_id": picking_pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "move_dest_ids": [Command.link(dest.id)],
                "state": "confirmed",
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.gB, self.stock_location, 10000.0
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.gB, self.pack_location
            ),
            0.0,
        )
        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 5.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.gB, self.stock_location
            ),
            5000.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._gather(self.gB, self.pack_location).quantity,
            5000.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.gB, self.pack_location
            ),
            0.0,
        )
        self.assertEqual(picking_client.state, "assigned")
        self.assertEqual(picking_client.move_ids.quantity, 5.0)

    def test_pick_ship_return(self):
        picking_pick, picking_ship = self.create_pick_ship()
        picking_ship.picking_type_id.return_picking_type_id = False
        self.productA.tracking = "lot"
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.productA.id,
                "name": "123456789",
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0, lot_id=lot
        )

        picking_pick.action_assign()
        picking_pick.move_ids.picked = True
        picking_pick._action_done()
        self.assertEqual(picking_pick.state, "done")
        self.assertEqual(picking_ship.state, "assigned")

        picking_ship.action_assign()
        picking_ship.move_ids.picked = True
        picking_ship._action_done()

        customer_quantity = self.env["stock.quant"]._get_available_quantity(
            self.productA, self.customer_location, lot_id=lot
        )
        self.assertEqual(customer_quantity, 10, "It should be one product in customer")

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_pick.ids,
                active_id=picking_pick.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 10.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_pick_picking = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )

        self.assertEqual(return_pick_picking.state, "waiting")

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_ship.ids,
                active_id=picking_ship.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 10.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_ship_picking = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )

        self.assertEqual(
            return_ship_picking.state,
            "assigned",
            "Return ship picking should automatically be assigned",
        )
        """ We created the return for ship picking. The origin/destination
        link between return moves should have been created during return creation.
        """
        self.assertTrue(
            return_ship_picking.move_ids
            in return_pick_picking.move_ids.mapped("move_orig_ids"),
            "The pick return picking's moves should have the ship return picking's moves as origin",
        )

        self.assertTrue(
            return_pick_picking.move_ids
            in return_ship_picking.move_ids.mapped("move_dest_ids"),
            "The ship return picking's moves should have the pick return picking's moves as destination",
        )

        return_ship_picking.move_ids[0].move_line_ids[0].write(
            {
                "quantity": 10.0,
                "lot_id": lot.id,
            }
        )
        return_ship_picking.move_ids.picked = True
        return_ship_picking._action_done()
        self.assertEqual(return_ship_picking.state, "done")
        self.assertEqual(return_pick_picking.state, "assigned")

        customer_quantity = self.env["stock.quant"]._get_available_quantity(
            self.productA, self.customer_location, lot_id=lot
        )
        self.assertEqual(customer_quantity, 0, "It should be one product in customer")

        pack_quantity = self.env["stock.quant"]._get_available_quantity(
            self.productA, self.pack_location, lot_id=lot
        )
        self.assertEqual(
            pack_quantity,
            0,
            "It should be one product in pack location but is reserved",
        )

        return_pick_picking.move_ids[0].move_line_ids[0].quantity = 10.0
        return_pick_picking.move_ids[0].picked = True
        return_pick_picking._action_done()
        self.assertEqual(return_pick_picking.state, "done")

        stock_quantity = self.env["stock.quant"]._get_available_quantity(
            self.productA, self.stock_location, lot_id=lot
        )
        self.assertEqual(stock_quantity, 10, "The product is not back in stock")

    def test_pick_pack_ship_return(self):
        picking_pick, picking_pack, picking_ship = self.create_pick_pack_ship()
        self.productA.tracking = "serial"
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.productA.id,
                "name": "123456789",
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 1.0, lot_id=lot
        )

        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 1.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()

        picking_pack.action_assign()
        picking_pack.move_ids[0].move_line_ids[0].quantity = 1.0
        picking_pack.move_ids[0].picked = True
        picking_pack._action_done()

        picking_ship.action_assign()
        picking_ship.move_ids[0].move_line_ids[0].quantity = 1.0
        picking_ship.move_ids[0].picked = True
        picking_ship._action_done()

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_ship.ids,
                active_id=picking_ship.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 1.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_ship_picking = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )

        return_ship_picking.move_ids[0].move_line_ids[0].write(
            {
                "quantity": 1.0,
                "lot_id": lot.id,
            }
        )
        return_ship_picking.move_ids[0].picked = True
        return_ship_picking._action_done()

        stock_quant = self.env["stock.quant"]._gather(
            self.productA, self.stock_location, lot_id=lot
        )
        self.assertEqual(stock_quant.quantity, 1)

        self.assertEqual(
            len(picking_pick.move_ids.move_orig_ids),
            0,
            "Picking pick should not have origin moves",
        )
        self.assertEqual(
            set(picking_pick.move_ids.move_dest_ids.ids), set(picking_pack.move_ids.ids)
        )

        self.assertEqual(
            set(picking_pack.move_ids.move_orig_ids.ids), set(picking_pick.move_ids.ids)
        )
        self.assertEqual(
            set(picking_pack.move_ids.move_dest_ids.ids), set(picking_ship.move_ids.ids)
        )

        self.assertEqual(
            set(picking_ship.move_ids.move_orig_ids.ids), set(picking_pack.move_ids.ids)
        )
        self.assertEqual(
            set(picking_ship.move_ids.move_dest_ids.ids),
            set(return_ship_picking.move_ids.ids),
        )

        self.assertEqual(
            set(return_ship_picking.move_ids.move_orig_ids.ids),
            set(picking_ship.move_ids.ids),
        )
        self.assertEqual(len(return_ship_picking.move_ids.move_dest_ids), 0)

    def test_merge_move_mto_mts(self):
        _picking_pick, picking_client = self.create_pick_ship()

        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_client.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "origin": "MPS",
                "procure_method": "make_to_stock",
            }
        )
        picking_client.action_confirm()
        self.assertEqual(len(picking_client.move_ids), 2, "Moves should not be merged")

    def test_mto_cancel_move_line(self):
        picking_pick, picking_client = self.create_pick_ship()

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.move_ids.quantity = 5.0
        picking_pick.move_ids.picked = True
        backorder_wizard_values = picking_pick.button_validate()
        backorder_wizard = (
            self.env[(backorder_wizard_values.get("res_model"))]
            .browse(backorder_wizard_values.get("res_id"))
            .with_context(backorder_wizard_values["context"])
        )
        backorder_wizard.process()

        self.assertTrue(picking_client.move_line_ids, "A move line should be created.")
        self.assertEqual(
            picking_client.move_line_ids.quantity,
            5,
            "The move line should have 5 unit reserved.",
        )

        picking_client.move_line_ids.unlink()

        self.assertEqual(
            picking_client.move_ids.state,
            "waiting",
            "The move state should be waiting since nothing is reserved and another origin move still in progess.",
        )
        self.assertEqual(
            picking_client.state,
            "waiting",
            "The picking state should not be ready anymore.",
        )

        picking_client.action_assign()

        back_order = self.env["stock.picking"].search(
            [("backorder_id", "=", picking_pick.id)]
        )
        back_order.move_ids.quantity = 5
        back_order.move_ids.picked = True
        back_order.button_validate()

        self.assertEqual(
            picking_client.move_ids.quantity,
            10,
            "The total quantity should be reserved since everything is available.",
        )
        picking_client.move_line_ids.unlink()

        self.assertEqual(
            picking_client.move_ids.state,
            "confirmed",
            "The move should be confirmed since all the origin moves are processed.",
        )
        self.assertEqual(
            picking_client.state,
            "confirmed",
            "The picking should be confirmed since all the moves are confirmed.",
        )

    def test_unreserve(self):
        picking_pick, picking_client = self.create_pick_ship()

        self.assertEqual(picking_pick.state, "confirmed")
        picking_pick.do_unreserve()
        self.assertEqual(picking_pick.state, "confirmed")
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick.action_assign()
        self.assertEqual(picking_pick.state, "assigned")
        picking_pick.do_unreserve()
        self.assertEqual(picking_pick.state, "confirmed")

        self.assertEqual(picking_client.state, "waiting")
        picking_client.do_unreserve()
        self.assertEqual(picking_client.state, "waiting")

    def test_return_only_one_product(self):
        picking_client = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
                "move_ids": [
                    Command.create(
                        {
                            "product_id": p.id,
                            "product_uom_qty": 10 + i,
                            "product_uom_id": p.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "state": "waiting",
                            "procure_method": "make_to_order",
                        }
                    )
                    for i, p in enumerate((self.productA, self.productB, self.productC))
                ],
            }
        )
        for move in picking_client.move_ids:
            move.quantity = move.product_uom_qty
        picking_client.move_ids.picked = True
        picking_client.button_validate()
        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_client.ids,
                active_id=picking_client.ids[0],
                active_model="stock.picking",
            )
        )
        return1 = stock_return_picking_form.save()
        return1.product_return_moves.filtered(
            lambda l: l.product_id.id == self.productB.id
        ).quantity = 5.0
        return_pick = return1.action_create_returns()
        return_pick = self.env["stock.picking"].browse(return_pick["res_id"])
        self.assertEqual(len(return_pick.move_ids), 1)
        self.assertEqual(return_pick.move_ids.product_id, self.productB)
        self.assertEqual(return_pick.move_ids.product_uom_qty, 5)
        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_client.ids,
                active_id=picking_client.ids[0],
                active_model="stock.picking",
            )
        )
        return2 = stock_return_picking_form.save()
        return_pick_leftorvers = return2.action_create_returns_all()
        return_pick_leftorvers = self.env["stock.picking"].browse(
            return_pick_leftorvers["res_id"]
        )
        self.assertRecordValues(
            return_pick_leftorvers.move_ids.sorted("product_uom_qty"),
            [
                {"product_id": self.productB.id, "product_uom_qty": 6},
                {"product_id": self.productA.id, "product_uom_qty": 10},
                {"product_id": self.productC.id, "product_uom_qty": 12},
            ],
        )

    def test_return_location(self):
        return_warehouse = self.env["stock.warehouse"].create(
            {"name": "return warehouse", "code": "rw"}
        )
        return_location = self.env["stock.location"].create(
            {
                "name": "return internal",
                "usage": "internal",
                "location_id": return_warehouse.view_location_id.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        picking_pick, picking_client = self.create_pick_ship()

        picking_pick.action_assign()
        picking_pick.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick.move_ids[0].picked = True
        picking_pick._action_done()
        picking_client.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_client.move_ids[0].picked = True
        picking_client._action_done()

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_client.ids,
                active_id=picking_client.ids[0],
                active_model="stock.picking",
            )
        )
        return1 = stock_return_picking_form.save()
        return1.product_return_moves.quantity = 5.0
        return_to_pick_picking_action = return1.action_create_returns()

        return_to_pick_picking = self.env["stock.picking"].browse(
            return_to_pick_picking_action["res_id"]
        )
        return_to_pick_picking.move_ids[0].move_line_ids[0].quantity = 5.0
        return_to_pick_picking.move_ids[0].picked = True
        return_to_pick_picking._action_done()

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_client.ids,
                active_id=picking_client.ids[0],
                active_model="stock.picking",
            )
        )
        return2 = stock_return_picking_form.save()
        return2.product_return_moves.quantity = 5.0
        return_to_return_picking_action = return2.action_create_returns()

        return_to_return_picking = self.env["stock.picking"].browse(
            return_to_return_picking_action["res_id"]
        )
        return_to_return_picking.location_dest_id = return_location
        return_to_return_picking.move_ids[0].move_line_ids[0].quantity = 5.0
        return_to_return_picking.move_ids[0].picked = True
        return_to_return_picking._action_done()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            5.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, return_location
            ),
            5.0,
        )
        self.assertEqual(
            len(
                self.env["stock.quant"].search(
                    [("product_id", "=", self.productA.id), ("quantity", "!=", 0)]
                )
            ),
            2,
        )

    def test_return_lot(self):
        self.productA.tracking = "lot"
        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
            }
        )
        lot2 = self.env["stock.lot"].create(
            {
                "name": "lot2",
                "product_id": self.productA.id,
            }
        )
        lot3 = self.env["stock.lot"].create(
            {
                "name": "lot3",
                "product_id": self.productA.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 7.0, lot_id=lot1
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 7.0, lot_id=lot2
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 7.0, lot_id=lot3
        )

        picking_pick, picking_client = self.create_pick_ship()
        picking_pick.action_confirm()
        picking_pick.action_assign()
        picking_pick.move_ids.picked = True
        picking_pick._action_done()
        picking_client.action_confirm()
        picking_client.action_assign()
        picking_client.move_ids.picked = True
        picking_client._action_done()

        picking_pick, picking_client = self.create_pick_ship()
        picking_pick.action_confirm()
        picking_pick.action_assign()
        picking_pick.move_ids.picked = True
        picking_pick._action_done()
        picking_client.action_confirm()
        picking_client.action_assign()
        picking_client.move_ids.picked = True
        picking_client._action_done()

        self.assertEqual(picking_client.move_line_ids[0].lot_id, lot2)
        self.assertEqual(picking_client.move_line_ids[0].quantity, 4)
        self.assertEqual(picking_client.move_line_ids[1].lot_id, lot3)
        self.assertEqual(picking_client.move_line_ids[1].quantity, 6)

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_client.ids,
                active_id=picking_client.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 10.0
        return_pick = self.env["stock.picking"].browse(
            stock_return_picking.action_create_returns()["res_id"]
        )

        self.assertEqual(len(return_pick.move_line_ids), 2)
        self.assertEqual(return_pick.move_line_ids[0].lot_id, lot2)
        self.assertEqual(return_pick.move_line_ids[0].quantity, 4)
        self.assertEqual(return_pick.move_line_ids[1].lot_id, lot3)
        self.assertEqual(return_pick.move_line_ids[1].quantity, 6)
        self.assertEqual(
            return_pick.picking_type_id,
            picking_client.location_id.warehouse_id.in_type_id,
        )


class TestSinglePicking(TestStockCommon):
    def test_source_location_change_batch_preserves_valid_moves(self):
        storable = self.env["product.product"].create(
            [
                {"name": "SLC stray", "is_storable": True, "type": "consu"},
                {"name": "SLC valid", "is_storable": True, "type": "consu"},
            ]
        )
        product_stray, product_valid = storable
        self.env["stock.quant"]._update_available_quantity(
            product_stray, self.shelf_2, 10
        )
        self.env["stock.quant"]._update_available_quantity(
            product_valid, self.shelf_1, 10
        )

        def make_move(product):
            move = self.MoveObj.create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 5,
                    "product_uom_id": product.uom_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                }
            )
            move._action_confirm()
            move._action_assign()
            return move

        origin_move = make_move(product_valid)
        move_stray = make_move(product_stray)
        move_valid = make_move(product_valid)
        move_valid.move_orig_ids = [(6, 0, origin_move.ids)]

        self.assertEqual(move_stray.move_line_ids.location_id, self.shelf_2)
        self.assertEqual(move_valid.move_line_ids.location_id, self.shelf_1)

        (move_stray | move_valid).write({"location_id": self.shelf_1.id})

        self.assertFalse(move_stray.move_line_ids)
        self.assertEqual(move_valid.move_line_ids.location_id, self.shelf_1)
        self.assertEqual(move_valid.move_orig_ids, origin_move)
        self.assertEqual(move_valid.procure_method, "make_to_stock")

    def test_backorder_1(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 2
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

        delivery_order.move_ids[0].move_line_ids[0].quantity = 1
        delivery_order.move_ids[0].picked = True
        delivery_order._action_done()
        self.assertNotEqual(delivery_order.date_done, False)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            1.0,
        )

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", delivery_order.id)]
        )
        self.assertEqual(backorder.state, "confirmed")
        backorder.action_assign()
        self.assertEqual(backorder.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

    def test_backorder_2(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 1
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

        delivery_order.move_ids[0].move_line_ids[0].quantity = 1
        delivery_order.move_ids[0].picked = True
        delivery_order._action_done()
        self.assertNotEqual(delivery_order.date_done, False)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", delivery_order.id)]
        )
        self.assertEqual(backorder.state, "confirmed")

    def test_backorder_3(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 2
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 2
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")

        delivery_order.move_ids[0].move_line_ids[0].quantity = 2
        delivery_order.move_ids[0].picked = True
        delivery_order._action_done()

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", delivery_order.id)]
        )
        self.assertEqual(backorder.state, "confirmed")

    def test_backorder_4(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 2
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.pack_location, 2
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")

        delivery_order.move_ids[0].move_line_ids[0].quantity = 2
        delivery_order.move_ids[0].picked = True

        res_dict = delivery_order.button_validate()
        backorder_wizard = Form(
            self.env["stock.backorder.confirmation"].with_context(res_dict["context"])
        ).save()
        backorder_wizard.process_cancel_backorder()

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", delivery_order.id)]
        )
        self.assertFalse(backorder)
        self.assertEqual(delivery_order.state, "done")
        self.assertEqual(delivery_order.move_ids[1].state, "cancel")

    def test_assign_deadline(self):
        delivery_order = self.PickingObj.create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.env["ir.config_parameter"].create(
            {"key": "stock.merge_only_same_date", "value": True}
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 4,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "date_deadline": datetime.now() + relativedelta(days=1),
            }
        )
        move2 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 4,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "date_deadline": datetime.now() + relativedelta(days=2),
            }
        )
        move3 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "date": datetime.now() + relativedelta(days=10),
            }
        )
        move4 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "date": datetime.now() + relativedelta(days=0),
            }
        )

        self.StockQuantObj._update_available_quantity(
            self.productA, self.pack_location, 2
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()

        self.assertEqual(
            move1.quantity, 2, "Earlier deadline should have reserved quantity"
        )
        self.assertEqual(
            move2.quantity, 0, "Later deadline should not have reserved quantity"
        )

        self.StockQuantObj._update_available_quantity(
            self.productA, self.pack_location, 2
        )
        delivery_order.action_assign()
        self.assertEqual(
            move1.quantity, 4, "Earlier deadline should have reserved quantity"
        )
        self.assertEqual(
            move2.quantity, 0, "Later deadline should not have reserved quantity"
        )

        self.StockQuantObj._update_available_quantity(
            self.productA, self.pack_location, 1
        )
        delivery_order.action_assign()
        self.assertEqual(
            move1.quantity, 4, "Earlier deadline should have reserved quantity"
        )
        self.assertEqual(move2.quantity, 1, "Move with deadline should take priority")
        self.assertEqual(
            move3.quantity, 0, "Move without deadline should not have reserved quantity"
        )
        self.assertEqual(
            move4.quantity, 0, "Move without deadline should not have reserved quantity"
        )

        self.StockQuantObj._update_available_quantity(
            self.productA, self.pack_location, 4
        )
        delivery_order.action_assign()
        self.assertEqual(
            move1.quantity, 4, "Earlier deadline should have reserved quantity"
        )
        self.assertEqual(move2.quantity, 4, "Move with deadline should take priority")
        self.assertEqual(
            move3.quantity,
            0,
            "Latest move without deadline should not have reserved quantity",
        )
        self.assertEqual(
            move4.quantity, 1, "Earlier move without deadline should take the priority"
        )

    def test_extra_move_1(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 1
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            1.0,
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

        delivery_order.move_ids[0].move_line_ids[0].quantity = 2
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )
        delivery_order.move_ids[0].picked = True
        delivery_order._action_done()
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location, allow_negative=True
            ),
            -1.0,
        )

        self.assertEqual(move1.product_qty, 1.0)
        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(move1.state, "done")

    def test_extra_move_2(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.pack_location, 1
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            1.0,
        )

        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )

        delivery_order.move_ids[0].move_line_ids[0].quantity = 3
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )
        delivery_order.move_ids[0].picked = True
        delivery_order._action_done()
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            0.0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location, allow_negative=True
            ),
            -2.0,
        )

        self.assertEqual(move1.product_qty, 1.0)
        self.assertEqual(move1.quantity, 3.0)
        self.assertEqual(move1.state, "done")

    def test_extra_move_3(self):
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )

        receipt.action_confirm()
        receipt.action_assign()
        self.assertEqual(receipt.state, "assigned")

        receipt.move_ids[0].move_line_ids[0].quantity = 2
        receipt.move_ids[0].picked = True
        receipt._action_done()
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            2.0,
        )

        self.assertEqual(move1.product_qty, 1.0)
        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(move1.state, "done")

    def test_extra_move_4(self):
        delivery = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 5,
                "quantity": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 5
        )
        delivery.action_confirm()
        delivery.action_assign()

        delivery.write(
            {
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 0,
                            "quantity": 10,
                            "state": "assigned",
                            "product_uom_id": self.productA.uom_id.id,
                            "picking_id": delivery.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ]
            }
        )
        delivery.move_ids.picked = True
        delivery._action_done()
        self.assertEqual(
            len(delivery.move_ids), 2, "Move should not be merged together"
        )
        for move in delivery.move_ids:
            self.assertNotEqual(
                move.quantity,
                move.product_uom_qty,
                "Initial demand shouldn't be modified",
            )

    def test_recheck_availability_1(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 1.0
        )
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "partially_available")

        self.assertEqual(move1.quantity, 1.0)
        self.assertEqual(len(move1.move_line_ids), 1)

        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": self.stock_location.id,
                "product_id": self.productA.id,
                "inventory_quantity": 2,
            }
        )
        inventory_quant.action_apply_inventory()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "assigned")

        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(len(move1.move_line_ids), 1)

    def test_recheck_availability_2(self):
        self.productA.tracking = "lot"
        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 1.0, lot_id=lot1
        )
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "partially_available")

        self.assertEqual(move1.quantity, 1.0)
        self.assertEqual(len(move1.move_line_ids), 1)

        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": self.stock_location.id,
                "product_id": self.productA.id,
                "inventory_quantity": 2,
                "lot_id": lot1.id,
            }
        )
        inventory_quant.action_apply_inventory()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "assigned")

        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(len(move1.move_line_ids), 1)
        self.assertEqual(move1.move_line_ids.lot_id.id, lot1.id)
        self.assertEqual(move1.move_line_ids.quantity, 2)

    def test_recheck_availability_3(self):
        self.productA.tracking = "lot"
        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
            }
        )
        lot2 = self.env["stock.lot"].create(
            {
                "name": "lot2",
                "product_id": self.productA.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 1.0, lot_id=lot1
        )
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "partially_available")

        self.assertEqual(move1.quantity, 1.0)
        self.assertEqual(len(move1.move_line_ids), 1)

        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": self.stock_location.id,
                "product_id": self.productA.id,
                "inventory_quantity": 1,
                "lot_id": lot2.id,
            }
        )
        inventory_quant.action_apply_inventory()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "assigned")

        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(len(move1.move_line_ids), 2)
        move_lines = move1.move_line_ids.sorted()
        self.assertEqual(move_lines[0].lot_id.id, lot1.id)
        self.assertEqual(move_lines[1].lot_id.id, lot2.id)

    def test_recheck_availability_4(self):
        self.productA.tracking = "serial"
        serial1 = self.env["stock.lot"].create(
            {
                "name": "serial1",
                "product_id": self.productA.id,
            }
        )
        serial2 = self.env["stock.lot"].create(
            {
                "name": "serial2",
                "product_id": self.productA.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 1.0, lot_id=serial1
        )
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "partially_available")

        self.assertEqual(move1.quantity, 1.0)
        self.assertEqual(len(move1.move_line_ids), 1)

        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": self.stock_location.id,
                "product_id": self.productA.id,
                "inventory_quantity": 1,
                "lot_id": serial2.id,
            }
        )
        inventory_quant.action_apply_inventory()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(move1.state, "assigned")

        self.assertEqual(move1.quantity, 2.0)
        self.assertEqual(len(move1.move_line_ids), 2)
        move_lines = move1.move_line_ids.sorted()
        self.assertEqual(move_lines[0].lot_id.id, serial1.id)
        self.assertEqual(move_lines[1].lot_id.id, serial2.id)

    def test_use_create_lot_use_existing_lot_1(self):
        self.picking_type_out.write(
            {
                "use_create_lots": False,
                "use_existing_lots": False,
            }
        )
        self.productA.tracking = "lot"

        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        delivery_order.action_confirm()
        delivery_order.move_ids.quantity = 2
        delivery_order.move_ids.picked = True
        delivery_order._action_done()

    def test_use_create_lot_use_existing_lot_2(self):
        self.picking_type_out.write(
            {
                "use_create_lots": True,
                "use_existing_lots": True,
            }
        )
        self.productA.tracking = "lot"

        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        delivery_order.action_confirm()
        delivery_order.move_ids.quantity = 2
        move_line = delivery_order.move_ids.move_line_ids
        delivery_order.move_ids.picked = True

        with self.assertRaises(UserError):
            delivery_order._action_done()

        move_line.lot_name = "newlot"
        delivery_order._action_done()

    def test_use_create_lot_use_existing_lot_3(self):
        self.picking_type_out.write(
            {
                "use_create_lots": True,
                "use_existing_lots": False,
            }
        )
        self.productA.tracking = "lot"

        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        delivery_order.action_confirm()
        delivery_order.move_ids.quantity = 2
        move_line = delivery_order.move_ids.move_line_ids
        delivery_order.move_ids.picked = True

        with self.assertRaises(UserError):
            delivery_order._action_done()

        move_line.lot_name = "newlot"
        delivery_order._action_done()

    def test_use_create_lot_use_existing_lot_4(self):
        self.picking_type_out.write(
            {
                "use_create_lots": False,
                "use_existing_lots": True,
            }
        )
        self.productA.tracking = "lot"

        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        delivery_order.action_confirm()
        delivery_order.move_ids.quantity = 2
        move_line = delivery_order.move_ids.move_line_ids
        delivery_order.move_ids.picked = True

        with self.assertRaises(UserError):
            delivery_order._action_done()

        with self.assertRaises(UserError):
            self.env["stock.lot"].with_context(
                active_picking_id=delivery_order.id
            ).create(
                {
                    "name": "lot1",
                    "product_id": self.productA.id,
                }
            )

        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
            }
        )
        move_line.lot_id = lot1
        delivery_order._action_done()

    def test_use_create_lot_use_existing_lot_5(self):
        self.picking_type_in.write(
            {
                "use_create_lots": False,
                "use_existing_lots": False,
            }
        )
        self.productA.tracking = "lot"

        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 2,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )

        receipt.action_confirm()
        receipt.move_ids.quantity = 2
        receipt.move_ids.picked = True

        receipt._action_done()
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.productA.id),
                ("location_id", "=", self.stock_location.id),
                ("lot_id", "=", False),
            ]
        )
        self.assertTrue(quant, "A quant without lot should exist")
        self.assertEqual(
            quant.quantity, 2, "The quantity of the quant without lot should be 2"
        )
        lot = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": self.productA.id,
                "company_id": self.env.company.id,
            }
        )
        new_quant = self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": self.stock_location.id,
                "lot_id": lot.id,
            }
        )
        out_move = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        out_move._action_confirm()
        out_move._action_assign()
        out_move.move_line_ids.lot_id = lot
        out_move.move_line_ids.quantity = 1
        out_move.picked = True
        out_move._action_done()
        self.assertEqual(
            new_quant.quantity, 0, "The quant with lot should remain untouched  1"
        )
        self.assertEqual(
            quant.quantity, 1, "The quantity of the quant without lot should be 1"
        )

    def test_merge_moves_1(self):
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 5,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 5,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        receipt.action_confirm()
        self.assertEqual(len(receipt.move_ids), 2, "Moves were not merged")
        self.assertEqual(
            receipt.move_ids.filtered(
                lambda m: m.product_id == self.productA
            ).product_uom_qty,
            9,
            "Merged quantity is not correct",
        )
        self.assertEqual(
            receipt.move_ids.filtered(
                lambda m: m.product_id == self.productB
            ).product_uom_qty,
            5,
            "Merge should not impact product B reserved quantity",
        )

    def test_merge_moves_2(self):
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "origin": "MPS",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 5,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "origin": "PO0001",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "origin": "MPS",
            }
        )
        receipt.action_confirm()
        self.assertEqual(len(receipt.move_ids), 1, "Moves were not merged")
        self.assertEqual(
            receipt.move_ids.origin.count("MPS"),
            1,
            "Origin not merged together or duplicated",
        )
        self.assertEqual(
            receipt.move_ids.origin.count("PO0001"),
            1,
            "Origin not merged together or duplicated",
        )

    def test_merge_moves_3(self):
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        move_1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "origin": "MPS",
            }
        )
        move_2 = self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "origin": "PO0001",
            }
        )
        move_1.quantity = 5
        move_2.quantity = 5
        receipt.button_validate()
        self.assertEqual(len(receipt.move_ids), 2, "Moves were not merged")

    def test_merge_moves_never_attributes(self):
        product_attribute = self.env["product.attribute"].create(
            {
                "name": "PA",
                "create_variant": "no_variant",
            }
        )

        self.env["product.attribute.value"].create(
            [
                {"name": "PAV" + str(i), "attribute_id": product_attribute.id}
                for i in range(2)
            ]
        )

        tmpl_attr_lines = self.env["product.template.attribute.line"].create(
            {
                "attribute_id": product_attribute.id,
                "product_tmpl_id": self.productA.product_tmpl_id.id,
                "value_ids": [Command.set(product_attribute.value_ids.ids)],
            }
        )
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "never_product_template_attribute_value_ids": tmpl_attr_lines.product_template_value_ids[
                    0
                ],
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 5,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "never_product_template_attribute_value_ids": tmpl_attr_lines.product_template_value_ids[
                    1
                ],
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "never_product_template_attribute_value_ids": tmpl_attr_lines.product_template_value_ids[
                    1
                ],
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        receipt.action_confirm()
        self.assertEqual(len(receipt.move_ids), 3, "Moves were not merged")
        self.assertEqual(
            receipt.move_ids.filtered(
                lambda m: (
                    m.product_id == self.productA
                    and m.never_product_template_attribute_value_ids
                    == tmpl_attr_lines.product_template_value_ids[1]
                )
            ).product_uom_qty,
            6,
            "Merged quantity is not correct",
        )

    def test_merge_chained_moves(self):
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "TEST WAREHOUSE",
                "code": "TEST1",
                "reception_steps": "three_steps",
            }
        )
        ref = self.env["stock.reference"].create({"name": "purchase order"})
        receipt1 = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.wh_input_stock_loc_id.id,
                "picking_type_id": warehouse.in_type_id.id,
                "state": "draft",
            }
        )
        receipt2 = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.wh_input_stock_loc_id.id,
                "picking_type_id": warehouse.in_type_id.id,
                "state": "draft",
            }
        )
        move_values = {
            "product_id": self.productA.id,
            "product_uom_id": self.productA.uom_id.id,
            "location_id": self.supplier_location.id,
            "location_dest_id": warehouse.wh_input_stock_loc_id.id,
            "reference_ids": [Command.link(ref.id)],
        }
        move_receipt_1, move_receipt_2 = self.MoveObj.create(
            [
                {**move_values, "product_uom_qty": 5, "picking_id": receipt1.id},
                {**move_values, "product_uom_qty": 3, "picking_id": receipt2.id},
            ]
        )
        receipt1.action_confirm()
        receipt2.action_confirm()
        (receipt1 | receipt2).button_validate()

        self.assertTrue(move_receipt_1.move_dest_ids, "No move created from push rules")
        self.assertTrue(move_receipt_2.move_dest_ids, "No move created from push rules")
        self.assertEqual(
            move_receipt_1.move_dest_ids.picking_id,
            move_receipt_2.move_dest_ids.picking_id,
            "Destination moves should be in the same picking",
        )

        input_move = move_receipt_2.move_dest_ids
        self.assertEqual(
            len(input_move.move_dest_ids), 0, "Push rule not yet triggered"
        )
        self.assertEqual(
            set(input_move.move_orig_ids.ids),
            set((move_receipt_2 | move_receipt_1).ids),
            "Move from input to QC should be merged and have the two receipt moves as origin.",
        )
        self.assertEqual(move_receipt_1.move_dest_ids, input_move)
        self.assertEqual(move_receipt_2.move_dest_ids, input_move)
        input_move.picking_id.button_validate()
        self.assertEqual(len(input_move.move_dest_ids), 1)

        qc_move = input_move.move_dest_ids
        self.assertEqual(len(qc_move), 1)
        self.assertTrue(
            qc_move.move_orig_ids == input_move,
            "Move between QC and stock should only have the input move as origin",
        )

    def test_prevent_merge_moves_without_stock_reference(self):
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "TEST WAREHOUSE",
                "code": "TEST1",
                "reception_steps": "three_steps",
            }
        )
        receipt1 = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.wh_input_stock_loc_id.id,
                "picking_type_id": warehouse.in_type_id.id,
                "state": "draft",
            }
        )
        receipt2 = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.wh_input_stock_loc_id.id,
                "picking_type_id": warehouse.in_type_id.id,
                "state": "draft",
            }
        )
        move_values = {
            "product_id": self.productA.id,
            "product_uom_id": self.productA.uom_id.id,
            "product_uom_qty": 5,
            "location_id": self.supplier_location.id,
            "location_dest_id": warehouse.wh_input_stock_loc_id.id,
        }
        self.MoveObj.create(
            [
                {**move_values, "picking_id": receipt1.id},
                {**move_values, "picking_id": receipt2.id},
            ]
        )
        self.assertFalse((receipt1 | receipt2).reference_ids)
        (receipt1 | receipt2).button_validate()
        self.assertNotEqual(
            receipt1._get_next_transfers(),
            receipt2._get_next_transfers(),
            "Input→QC pickings should not merged without stock reference.",
        )

    def test_empty_moves_validation_1(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        with self.assertRaises(UserError):
            delivery_order.button_validate()

    def test_empty_moves_validation_2(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        move_a = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move_b = self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 0,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        move_a.quantity = 1
        move_a.picked = True
        delivery_order.button_validate()

        self.assertEqual(move_a.state, "done")
        self.assertEqual(move_b.state, "cancel")
        back_order = self.env["stock.picking"].search(
            [("backorder_id", "=", delivery_order.id)]
        )
        self.assertFalse(back_order, "There should be no back order")

    def test_unlink_move_1(self):
        picking = Form(self.env["stock.picking"])
        picking.picking_type_id = self.picking_type_out
        with picking.move_ids.new() as move:
            move.product_id = self.productA
            move.quantity = 10
        picking = picking.save()
        self.assertEqual(picking.state, "assigned")

        picking = Form(picking)
        picking.move_ids.remove(0)
        picking = picking.save()
        self.assertEqual(len(picking.move_ids), 0)

    def test_additional_move_1(self):
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        move_1 = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        move_2 = self.MoveObj.create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        receipt.action_confirm()
        move_1.quantity = 10
        move_2.quantity = 10
        receipt.move_ids.picked = True
        receipt.button_validate()
        self.assertEqual(self.productA.qty_available, 10)
        self.assertEqual(self.productB.qty_available, 10)

        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_type": "one",
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": delivery_order.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        delivery_order.action_confirm()
        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")

        delivery_order = Form(delivery_order)
        with delivery_order.move_ids.new() as move:
            move.product_id = self.productB
            move.product_uom_qty = 10
        delivery_order = delivery_order.save()

        self.assertEqual(delivery_order.state, "confirmed")
        self.assertEqual(delivery_order.show_check_availability, True)

        delivery_order.action_assign()
        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(delivery_order.show_check_availability, False)

        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.productA, self.stock_location)
            .reserved_quantity,
            10.0,
        )
        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.productB, self.stock_location)
            .reserved_quantity,
            10.0,
        )

    def test_additional_move_2(self):
        delivery_order = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "quantity": 5,
                        }
                    )
                ],
            }
        )
        self.assertEqual(delivery_order.state, "assigned")

        delivery_order = Form(delivery_order)
        with delivery_order.move_ids.new() as move:
            move.product_id = self.productB
        delivery_order = delivery_order.save()

        self.assertEqual(delivery_order.state, "assigned")
        self.assertEqual(delivery_order.show_check_availability, False)

    def test_owner_1(self):
        self.env.user.group_ids += self.env.ref("stock.group_tracking_owner")
        """Make a receipt, set an owner and validate"""
        owner1 = self.env["res.partner"].create({"name": "owner"})
        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        receipt.action_confirm()
        receipt = Form(receipt)
        receipt.owner_id = owner1
        receipt = receipt.save()
        receipt.button_validate()

        supplier_quant = self.env["stock.quant"]._gather(
            self.productA, self.supplier_location
        )
        stock_quant = self.env["stock.quant"]._gather(
            self.productA, self.stock_location
        )

        self.assertEqual(supplier_quant.owner_id, owner1)
        self.assertEqual(supplier_quant.quantity, -1)
        self.assertEqual(stock_quant.owner_id, owner1)
        self.assertEqual(stock_quant.quantity, 1)

    def test_putaway_for_picking_sml(self):
        partner = self.env["res.partner"].create({"name": "Partner"})
        shelf_location = self.env["stock.location"].create(
            {
                "name": "shelf1",
                "usage": "internal",
                "location_id": self.stock_location.id,
            }
        )

        grp_multi_loc = self.env.ref("stock.group_stock_multi_locations")
        self.env.user.group_ids = [Command.link(grp_multi_loc.id)]
        self.env["stock.putaway.rule"].create(
            {
                "product_id": self.productA.id,
                "location_in_id": self.stock_location.id,
                "location_out_id": shelf_location.id,
            }
        )
        receipt_form = Form(
            self.env["stock.picking"], view="stock.view_stock_picking_form"
        )
        receipt_form.partner_id = partner
        receipt_form.picking_type_id = self.picking_type_in
        receipt_form.location_dest_id = self.stock_location
        receipt = receipt_form.save()

        with receipt_form.move_ids.new() as move:
            move.product_id = self.productA
            move.quantity = 1.0

        receipt = receipt_form.save()
        self.assertEqual(receipt.location_dest_id.id, self.stock_location.id)
        self.assertEqual(receipt.move_line_ids.location_dest_id.id, shelf_location.id)

    def test_cancel_plan_transfer(self):
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 10,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_id": self.pack_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        self.assertEqual(
            picking.state, "confirmed", "Picking should be in a confirmed state."
        )

        picking.action_cancel()
        self.assertEqual(
            picking.state, "cancel", "Picking should be in a cancel state."
        )

    def test_immediate_transfer(self):
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "quantity": 10,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_id": self.pack_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )

        self.assertEqual(
            picking.state, "assigned", "Picking should not be in a draft state."
        )
        self.assertEqual(len(picking.move_ids), 1, "Picking should have stock move.")
        picking.action_cancel()
        self.assertEqual(
            picking.move_ids.state, "cancel", "Stock move should be in a cancel state."
        )
        self.assertEqual(
            picking.state, "cancel", "Picking should be in a cancel state."
        )

    def test_immediate_picking_with_lot(self):
        self.productA.tracking = "serial"
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                            "quantity": 1,
                            "lot_name": "12345",
                        }
                    )
                ],
            }
        )

        self.assertEqual(
            len(picking.move_line_ids), 1, "Picking should have a single move line"
        )
        picking.button_validate()
        self.assertEqual(
            len(picking.move_line_ids), 1, "Picking should have a single move line"
        )

    def test_picking_reservation_at_confirm(self):
        product = self.productA
        self.picking_type_out.reservation_method = "at_confirm"
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 10,
                            "product_uom_id": product.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        self.assertFalse(picking.move_line_ids)
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 5
        )
        self.env["stock.scheduler"].run()
        self.assertRecordValues(
            picking.move_line_ids, [{"state": "partially_available", "quantity": 5.0}]
        )
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 10
        )
        self.env["stock.scheduler"].run()
        self.assertRecordValues(
            picking.move_line_ids, [{"state": "assigned", "quantity": 10.0}]
        )

    def test_create_picked_move_line(self):
        product = self.productA
        self.picking_type_out.reservation_method = "at_confirm"
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 10,
                            "product_uom_id": product.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.move_ids.quantity = 5
        picking.move_ids.picked = True
        sml = self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product.id,
                "picking_id": picking.id,
                "quantity": 1.0,
            }
        )
        self.assertEqual(picking.move_ids.quantity, 6.0)
        self.assertTrue(sml.picked)

    def test_unreservation_on_qty_decrease(self):
        tracked_product = self.env["product.product"].create(
            {
                "name": "Lovely Product",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": self.env.ref("product.product_category_goods").id,
            }
        )
        closest_strategy = self.env["product.removal"].search(
            [("method", "=", "closest")]
        )
        tracked_product.categ_id.removal_strategy_id = closest_strategy
        lot_count = 5
        lots = self.env["stock.lot"].create(
            [
                {"product_id": tracked_product.id, "name": f"LOT00{1 + i}"}
                for i in range(lot_count)
            ]
        )
        locations = self.env["stock.location"].create(
            [
                {
                    "name": f"Shell {lot_count - i}",
                    "usage": "internal",
                    "location_id": self.stock_location.id,
                }
                for i in range(lot_count)
            ]
        )
        for i in range(lot_count):
            self.env["stock.quant"]._update_available_quantity(
                tracked_product, locations[i], 10.0, lot_id=lots[i]
            )
        delivery = self.env["stock.picking"].create(
            {
                "name": "Lovely Delivery",
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": tracked_product.id,
                            "product_uom_qty": 50,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "product_uom_id": tracked_product.uom_id.id,
                        }
                    )
                ],
            }
        )
        delivery.picking_type_id.reservation_method = "at_confirm"
        delivery.action_confirm()
        self.assertEqual(
            delivery.move_line_ids.mapped(
                lambda sml: (sml.location_id.name, sml.lot_id.name, sml.quantity)
            ),
            [
                ("Shell 1", "LOT005", 10.0),
                ("Shell 2", "LOT004", 10.0),
                ("Shell 3", "LOT003", 10.0),
                ("Shell 4", "LOT002", 10.0),
                ("Shell 5", "LOT001", 10.0),
            ],
        )
        with Form(delivery) as delivery_form:
            with delivery_form.move_ids.edit(0) as move:
                move.quantity = 45
        self.assertEqual(
            delivery.move_line_ids.mapped(
                lambda sml: (sml.location_id.name, sml.lot_id.name, sml.quantity)
            ),
            [
                ("Shell 1", "LOT005", 10.0),
                ("Shell 2", "LOT004", 10.0),
                ("Shell 3", "LOT003", 10.0),
                ("Shell 4", "LOT002", 10.0),
                ("Shell 5", "LOT001", 5.0),
            ],
        )
        with Form(delivery) as delivery_form:
            with delivery_form.move_ids.edit(0) as move:
                move.quantity = 25
        self.assertEqual(
            delivery.move_line_ids.mapped(
                lambda sml: (sml.location_id.name, sml.lot_id.name, sml.quantity)
            ),
            [
                ("Shell 1", "LOT005", 10.0),
                ("Shell 2", "LOT004", 10.0),
                ("Shell 3", "LOT003", 5.0),
            ],
        )
        with Form(delivery) as delivery_form:
            with delivery_form.move_ids.edit(0) as move:
                move.quantity = 12
        self.assertEqual(
            delivery.move_line_ids.mapped(
                lambda sml: (sml.location_id.name, sml.lot_id.name, sml.quantity)
            ),
            [
                ("Shell 1", "LOT005", 10.0),
                ("Shell 2", "LOT004", 2.0),
            ],
        )

    def test_unreservation_on_qty_decrease_2(self):
        packages = self.env["stock.package"].create(
            [
                {"name": "pack1"},
                {"name": "pack2"},
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 3, package_id=packages[0]
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 2, package_id=packages[1]
        )

        move = self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.assertEqual(move.quantity, 5)
        move.move_line_ids = move._prepare_quantity_done_vals(1)
        self.assertRecordValues(
            move.move_line_ids,
            [
                {
                    "quantity": 1,
                    "result_package_id": packages[0].id,
                }
            ],
        )

    def test_unreservation_on_qty_decrease_3(self):
        packages = self.env["stock.package"].create(
            [
                {"name": "pack1"},
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 3, package_id=packages[0]
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 2
        )

        move = self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.assertEqual(move.quantity, 5)
        move.move_line_ids = move._prepare_quantity_done_vals(1)
        self.assertRecordValues(
            move.move_line_ids,
            [
                {
                    "quantity": 1,
                    "result_package_id": packages[0].id,
                }
            ],
        )

    def test_onchange_picking_locations(self):
        new_location, new_destination = self.env["stock.location"].create(
            [
                {
                    "name": "Super location",
                    "usage": "internal",
                    "location_id": self.stock_location.id,
                },
                {
                    "name": "Super destination",
                    "usage": "internal",
                    "location_id": self.stock_location.id,
                },
            ]
        )
        with Form(
            self.env["stock.picking"].with_context(
                restricted_picking_type_code="internal"
            )
        ) as picking_form:
            with picking_form.move_ids.new() as new_move:
                new_move.product_id = self.product
                new_move.product_uom_qty = 3.0
            picking_form.location_id = new_location
            picking_form.location_dest_id = new_destination
        picking = picking_form.save()
        self.assertRecordValues(
            picking.move_ids,
            [{"location_id": new_location.id, "location_dest_id": new_destination.id}],
        )

    def test_validate_picking_twice(self):
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 50,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "product_uom_id": self.productA.uom_id.id,
                        }
                    ),
                ],
            }
        )
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertRecordValues(picking.move_ids, [{"quantity": 50.0, "state": "done"}])
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertRecordValues(picking.move_ids, [{"quantity": 50.0, "state": "done"}])


class TestStockUOM(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        dp = cls.env.ref("uom.decimal_product_uom")
        dp.digits = 7

    def test_pickings_transfer_with_different_uom_and_back_orders(self):
        T_LBS = self.env["uom.uom"].create(
            {
                "name": "T-LBS",
            }
        )
        T_GT = self.env["uom.uom"].create(
            {
                "name": "T-GT",
                "relative_factor": 2240.00,
                "relative_uom_id": T_LBS.id,
            }
        )
        T_TEST = self.env["product.product"].create(
            {
                "name": "T_TEST",
                "is_storable": True,
                "uom_id": T_LBS.id,
                "uom_ids": [Command.link(T_LBS.id)],
                "tracking": "lot",
            }
        )

        picking_in = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "state": "draft",
            }
        )
        move = self.env["stock.move"].create(
            {
                "product_id": T_TEST.id,
                "product_uom_qty": 60,
                "product_uom_id": T_GT.id,
                "picking_id": picking_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        picking_in.action_confirm()
        picking_in.do_unreserve()

        self.assertEqual(move.product_uom_qty, 60.00, "Wrong T_GT quantity")
        self.assertEqual(move.product_qty, 134400.00, "Wrong T_LBS quantity")

        lot = self.env["stock.lot"].create(
            {"name": "Lot TEST", "product_id": T_TEST.id}
        )
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": T_TEST.id,
                "product_uom_id": T_LBS.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "quantity": 42760.00,
                "lot_id": lot.id,
            }
        )
        picking_in.move_ids.picked = True
        picking_in._action_done()
        back_order_in = self.env["stock.picking"].search(
            [("backorder_id", "=", picking_in.id)]
        )

        self.assertEqual(
            len(back_order_in), 1.00, "There should be one back order created"
        )
        self.assertEqual(
            back_order_in.move_ids.product_qty,
            91640.000032,
            "There should be one back order created",
        )

    def test_move_product_with_different_uom(self):
        precision = self.env.ref("uom.decimal_product_uom")
        precision.digits = 3

        product_G = self.env["product.product"].create(
            {
                "name": "Product G",
                "is_storable": True,
                "uom_id": self.uom_gm.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            product_G, self.stock_location, 149.88
        )
        self.assertEqual(
            len(product_G.stock_quant_ids), 1, "One quant should exist for the product."
        )
        quant = product_G.stock_quant_ids

        picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
                "product_id": product_G.id,
                "product_uom_id": self.uom_kg.id,
                "product_uom_qty": 1,
            }
        )

        self.assertEqual(move.product_uom_id.id, self.uom_kg.id)
        self.assertEqual(move.product_uom_qty, 1.0)

        picking.action_confirm()
        picking.action_assign()

        self.assertEqual(
            len(picking.move_line_ids), 1, "One move line should exist for the picking."
        )
        move_line = picking.move_line_ids
        self.assertEqual(quant.quantity, 149.88)
        self.assertEqual(move_line.quantity_product_uom, quant.reserved_quantity)


class TestRoutes(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product1 = cls.env["product.product"].create(
            {
                "name": "product a",
                "is_storable": True,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Partner"})

    def _enable_pick_ship(self):
        self.warehouse_1.delivery_steps = "pick_ship"
        self.pick_ship_route = self.warehouse_1.route_ids.filtered(
            lambda r: "(pick + ship)" in r.name
        )

    def test_replenish_pick_ship_1(self):
        self.product_uom_qty = 42

        warehouse_1 = self.warehouse_1
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Small Warehouse", "code": "SWH"}
        )
        warehouse_1.resupply_wh_ids = [Command.set([warehouse_2.id])]
        resupply_route = self.env["stock.route"].search(
            [
                ("supplier_wh_id", "=", warehouse_2.id),
                ("supplied_wh_id", "=", warehouse_1.id),
            ]
        )
        self.assertTrue(resupply_route, "Ressuply route not found")
        self.product1.route_ids = [Command.set([resupply_route.id, self.route_mto.id])]

        replenish_wizard = (
            self.env["product.replenish"]
            .with_context(default_product_tmpl_id=self.product1.product_tmpl_id.id)
            .create(
                {
                    "product_id": self.product1.id,
                    "product_tmpl_id": self.product1.product_tmpl_id.id,
                    "product_uom_id": self.uom_unit.id,
                    "quantity": self.product_uom_qty,
                    "warehouse_id": self.warehouse_1.id,
                }
            )
        )

        genrated_picking = replenish_wizard.launch_replenishment()
        links = genrated_picking.get("params", {}).get("links")
        url = (links and links[0].get("url", "")) or ""
        picking_id, model_name = self.url_extract_rec_id_and_model(url)

        last_picking_id = False
        if picking_id and model_name:
            last_picking_id = self.env[model_name].browse(int(picking_id))
        self.assertTrue(last_picking_id, "Picking not found")
        move_line = last_picking_id.move_ids.search(
            [("product_id", "=", self.product1.id)]
        )
        self.assertTrue(move_line, "The product is not in the picking")
        self.assertEqual(
            move_line[0].product_uom_qty,
            self.product_uom_qty,
            "Quantities does not match",
        )
        self.assertEqual(
            move_line[1].product_uom_qty,
            self.product_uom_qty,
            "Quantities does not match",
        )

    def test_pick_ship_from_subloc(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        warehouse.delivery_steps = "pick_ship"
        subloc = self.env["stock.location"].create(
            {
                "name": "Fancy Spot",
                "location_id": warehouse.wh_output_stock_loc_id.id,
                "usage": "internal",
            }
        )

        pick_move = self.env["stock.move"].create(
            {
                "picking_type_id": warehouse.pick_type_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": self.product1.id,
                "product_uom_qty": 1,
            }
        )
        pick_move._action_confirm()
        self.assertEqual(pick_move.location_dest_id, warehouse.wh_output_stock_loc_id)

        pick_move.write({"quantity": 1, "picked": True})
        pick_move.picking_id.location_dest_id = subloc
        pick_move.picking_id._action_done()

        self.assertEqual(pick_move.location_dest_id, subloc)
        self.assertEqual(len(pick_move.move_dest_ids), 1)
        self.assertEqual(pick_move.move_dest_ids.location_id, subloc)

    def test_2_steps_delivery_reaches_customer_subloc(self):
        self._enable_pick_ship()

        subloc = self.env["stock.location"].create(
            {
                "name": "Fancy Spot",
                "location_id": self.customer_location.id,
                "usage": "internal",
            }
        )

        pick_move = self.env["stock.move"].create(
            {
                "picking_type_id": self.warehouse_1.pick_type_id.id,
                "location_id": self.warehouse_1.lot_stock_id.id,
                "product_id": self.product1.id,
                "product_uom_qty": 1,
                "location_final_id": subloc.id,
            }
        )
        pick_move._action_confirm()
        self.assertEqual(
            pick_move.location_dest_id, self.warehouse_1.wh_output_stock_loc_id
        )

        pick_move.write({"quantity": 1, "picked": True})
        pick_move.picking_id._action_done()

        self.assertEqual(len(pick_move.move_dest_ids), 1)
        self.assertEqual(pick_move.move_dest_ids.location_dest_id, subloc)

    def test_push_rule_on_move_1(self):
        self._enable_pick_ship()

        push_location = self.env["stock.location"].create(
            {
                "location_id": self.stock_location.location_id.id,
                "name": "push location",
            }
        )

        route = self.env["stock.route"].create(
            {
                "name": "new route",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "create a move to push location",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": push_location.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "manual",
                            "picking_type_id": self.picking_type_in.id,
                        }
                    )
                ],
            }
        )
        move1 = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1.0,
                "route_ids": [Command.link(route.id)],
            }
        )
        move1._action_confirm()
        move1.write({"quantity": 1, "picked": True})
        move1._action_done()

        pushed_move = move1.move_dest_ids
        self.assertEqual(pushed_move.location_dest_id.id, push_location.id)

    def test_location_dest_update(self):
        new_loc = self.env["stock.location"].create(
            {
                "name": "New_location",
                "usage": "internal",
            }
        )
        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "new_picking_type",
                "code": "internal",
                "sequence_code": "NPT",
                "default_location_src_id": self.stock_location.id,
                "default_location_dest_id": new_loc.id,
                "warehouse_id": self.warehouse_1.id,
            }
        )
        route = self.env["stock.route"].create(
            {
                "name": "new route",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "create a move to push location",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": new_loc.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "transparent",
                            "picking_type_id": picking_type.id,
                        }
                    )
                ],
            }
        )
        product = self.env["product.product"].create(
            {
                "name": "new_product",
                "is_storable": True,
                "route_ids": [Command.link(route.id)],
            }
        )
        move1 = self.env["stock.move"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "product_uom_id": self.uom_unit.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_id": self.uom_unit.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                            "quantity": 1.00,
                        }
                    )
                ],
            }
        )
        move1.picked = True
        move1._action_done()
        self.assertEqual(move1.location_dest_id, new_loc)
        positive_quant = product.stock_quant_ids.filtered(lambda q: q.quantity > 0)
        self.assertEqual(positive_quant.location_id, new_loc)

    def test_mtso_mto_adjust_01(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.user.id)], limit=1
        )
        final_location = self.partner.property_stock_customer
        product_A = self.env["product.product"].create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )
        product_B = self.env["product.product"].create(
            {
                "name": "Product B",
                "is_storable": True,
            }
        )

        rule = self.env["stock.rule"]._get_rule(
            product_A, final_location, {"warehouse_id": warehouse}
        )
        rule.procure_method = "mts_else_mto"

        self.env["stock.quant"]._update_available_quantity(
            product_A, warehouse.lot_stock_id, 5.0
        )
        self.env["stock.quant"]._update_available_quantity(
            product_B, warehouse.lot_stock_id, 3.0
        )

        move_tmpl = {
            "product_uom_id": self.uom_unit.id,
            "product_uom_qty": 4.0,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": self.partner.property_stock_customer.id,
            "warehouse_id": warehouse.id,
        }
        move_A_vals = dict(move_tmpl)
        move_A_vals.update(
            {
                "product_id": product_A.id,
            }
        )
        move_A = self.env["stock.move"].create(move_A_vals)
        move_B_vals = dict(move_tmpl)
        move_B_vals.update(
            {
                "product_id": product_B.id,
            }
        )
        move_B = self.env["stock.move"].create(move_B_vals)
        moves = move_A + move_B

        self.assertEqual(
            move_A.procure_method, "make_to_stock", 'Move A should be "make_to_stock"'
        )
        self.assertEqual(
            move_B.procure_method, "make_to_stock", 'Move B should be "make_to_stock"'
        )
        moves._adjust_procure_method()
        self.assertEqual(
            move_A.procure_method, "make_to_stock", 'Move A should be "make_to_stock"'
        )
        self.assertEqual(
            move_B.procure_method, "make_to_stock", 'Move B should be "make_to_stock"'
        )

    def test_location_final_id_in_push(self):
        warehouse = self.warehouse_1
        warehouse.delivery_steps = "pick_ship"
        final_location = self.env["stock.location"].create(
            {
                "name": "Partner Stock",
                "location_id": self.partner.property_stock_customer.id,
            }
        )
        pick = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                "picking_type_id": warehouse.pick_type_id.id,
                "move_ids": [
                    Command.create(
                        {
                            "location_id": warehouse.lot_stock_id.id,
                            "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                            "location_final_id": final_location.id,
                            "product_id": self.product.id,
                            "product_uom_id": self.product.uom_id.id,
                            "product_uom_qty": 1.0,
                        }
                    )
                ],
            }
        )
        pick.action_confirm()
        pick.button_validate()
        ship = pick.move_ids.move_dest_ids.picking_id
        self.assertEqual(ship.location_dest_id, final_location)
        self.assertEqual(ship.move_ids.location_dest_id, final_location)


class TestAutoAssign(TestStockCommon):
    def create_pick_ship(self):
        self.warehouse_1.delivery_route_id.rule_ids.action = "pull"
        picking_client = self.env["stock.picking"].create(
            {
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        dest = self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_client.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "state": "waiting",
                "procure_method": "make_to_order",
            }
        )

        picking_pick = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )

        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "move_dest_ids": [Command.link(dest.id)],
                "state": "confirmed",
            }
        )
        return picking_pick, picking_client

    def test_auto_assign_0(self):
        self.picking_type_out.reservation_method = "at_confirm"

        customer_picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        customer_move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.productA.id,
                "product_uom_id": self.productA.uom_id.id,
                "product_uom_qty": 10.0,
                "picking_id": customer_picking.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        customer_picking.action_confirm()
        customer_picking.action_assign()
        self.assertEqual(customer_move.state, "confirmed")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            0,
        )

        supplier_picking = self.env["stock.picking"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        supplier_move = self.env["stock.move"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": self.productA.id,
                "product_uom_id": self.productA.uom_id.id,
                "product_uom_qty": 10.0,
                "picking_id": supplier_picking.id,
            }
        )
        supplier_picking.action_confirm()
        supplier_picking.action_assign()
        supplier_move.picked = True
        supplier_picking._action_done()

        self.assertEqual(customer_move.state, "assigned")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            0,
        )

    def test_auto_assign_1(self):
        _picking_pick, picking_client = self.create_pick_ship()
        self.picking_type_out.reservation_method = "at_confirm"

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )

        picking_pick_2 = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_out.id,
                "state": "draft",
            }
        )
        self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_pick_2.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "state": "confirmed",
            }
        )
        picking_pick_2.action_assign()
        picking_pick_2.move_ids[0].move_line_ids[0].quantity = 10.0
        picking_pick_2.move_ids[0].picked = True
        picking_pick_2._action_done()

        self.assertEqual(
            picking_client.state,
            "waiting",
            "MTO moves can't be automatically assigned.",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.pack_location
            ),
            10.0,
        )

    def test_auto_assign_reservation_method(self):
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            0,
        )
        picking_type_out1 = self.picking_type_out.copy()
        picking_type_out2 = picking_type_out1.copy()
        picking_type_out3 = picking_type_out1.copy()
        picking_type_out4 = picking_type_out1.copy()
        picking_type_out1.reservation_method = "manual"
        picking_type_out2.reservation_method = "by_date"
        picking_type_out2.reservation_days_before = "1"
        picking_type_out3.reservation_method = "by_date"
        picking_type_out3.reservation_days_before = "10"
        picking_type_out4.reservation_method = "at_confirm"

        customer_picking1 = self.env["stock.picking"].create(
            {
                "name": "Delivery 1",
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": picking_type_out1.id,
                "state": "draft",
            }
        )

        customer_picking2 = customer_picking1.copy(
            {
                "name": "Delivery 2",
                "picking_type_id": picking_type_out2.id,
                "date_planned": customer_picking1.date_planned + timedelta(days=5),
            }
        )
        customer_picking3 = customer_picking2.copy(
            {"name": "Delivery 3", "picking_type_id": picking_type_out3.id}
        )
        customer_picking4 = customer_picking3.copy(
            {"name": "Delivery 4", "picking_type_id": picking_type_out3.id}
        )
        customer_picking5 = customer_picking1.copy(
            {"name": "Delivery 5", "picking_type_id": picking_type_out4.id}
        )

        customer_picking1 = Form(customer_picking1)
        with customer_picking1.move_ids.new() as move:
            move.product_id = self.productA
            move.product_uom_qty = 10
        customer_picking1 = customer_picking1.save()

        customer_picking2 = Form(customer_picking2)
        with customer_picking2.move_ids.new() as move:
            move.product_id = self.productA
            move.product_uom_qty = 10
        customer_picking2 = customer_picking2.save()

        customer_picking3 = Form(customer_picking3)
        with customer_picking3.move_ids.new() as move:
            move.product_id = self.productA
            move.product_uom_qty = 10
        customer_picking3 = customer_picking3.save()

        customer_picking4 = Form(customer_picking4)
        with customer_picking4.move_ids.new() as move:
            move.product_id = self.productA
            move.product_uom_qty = 10
        customer_picking4 = customer_picking4.save()

        customer_picking5 = Form(customer_picking5)
        with customer_picking5.move_ids.new() as move:
            move.product_id = self.productA
            move.product_uom_qty = 10
        customer_picking5 = customer_picking5.save()

        customer_picking1.action_assign()
        customer_picking2.action_assign()
        customer_picking3.action_assign()
        self.assertEqual(
            customer_picking1.move_ids.quantity,
            0,
            "There should be no products available to reserve yet.",
        )
        self.assertEqual(
            customer_picking2.move_ids.quantity,
            0,
            "There should be no products available to reserve yet.",
        )
        self.assertEqual(
            customer_picking3.move_ids.quantity,
            0,
            "There should be no products available to reserve yet.",
        )

        self.assertFalse(
            customer_picking1.move_ids.date_reservation,
            "Reservation Method: 'manual' shouldn't have a date_reservation",
        )
        self.assertEqual(
            customer_picking2.move_ids.date_reservation,
            (customer_picking2.date_planned - timedelta(days=1)).date(),
            "Reservation Method: 'by_date' should have a date_reservation = date_planned - reservation_days_before",
        )
        self.assertFalse(
            customer_picking5.move_ids.date_reservation,
            "Reservation Method: 'at_confirm' shouldn't have a date_reservation until confirmed",
        )

        supplier_picking = self.env["stock.picking"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        supplier_move = self.env["stock.move"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": self.productA.id,
                "product_uom_id": self.productA.uom_id.id,
                "product_uom_qty": 50.0,
                "picking_id": supplier_picking.id,
            }
        )
        supplier_move.quantity = 50
        supplier_move.picked = True
        supplier_picking._action_done()

        self.assertEqual(
            customer_picking1.move_ids.quantity,
            0,
            "Reservation Method: 'manual' shouldn't ever auto-assign",
        )
        self.assertEqual(
            customer_picking2.move_ids.quantity,
            0,
            "Reservation Method: 'by_date' shouldn't auto-assign when not within reservation date range",
        )
        self.assertEqual(
            customer_picking3.move_ids.quantity,
            10,
            "Reservation Method: 'by_date' should auto-assign when within reservation date range",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.productA, self.stock_location
            ),
            40,
        )

        customer_picking4.action_confirm()
        customer_picking5.action_confirm()
        self.assertEqual(
            customer_picking4.move_ids.quantity,
            10,
            "Reservation Method: 'by_date' should auto-assign when within reservation date range at confirmation",
        )
        self.assertEqual(
            customer_picking5.move_ids.quantity,
            10,
            "Reservation Method: 'at_confirm' should auto-assign at confirmation",
        )

    def test_serial_lot_ids(self):
        self.product_serial = self.env["product.product"].create(
            {
                "name": "PSerial",
                "is_storable": True,
                "tracking": "serial",
            }
        )

        move = self.env["stock.move"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": self.product_serial.id,
                "product_uom_id": self.uom_unit.id,
                "picking_type_id": self.picking_type_in.id,
            }
        )
        self.assertEqual(move.state, "draft")
        lot1 = self.env["stock.lot"].create(
            {
                "name": "serial1",
                "product_id": self.product_serial.id,
            }
        )
        lot2 = self.env["stock.lot"].create(
            {
                "name": "serial2",
                "product_id": self.product_serial.id,
            }
        )
        lot3 = self.env["stock.lot"].create(
            {
                "name": "serial3",
                "product_id": self.product_serial.id,
            }
        )
        move.lot_ids = [Command.link(lot1.id)]
        move.lot_ids = [Command.link(lot2.id)]
        move.lot_ids = [Command.link(lot3.id)]
        self.assertEqual(move.quantity, 3.0)
        move.lot_ids = [Command.unlink(lot2.id)]
        self.assertEqual(move.quantity, 2.0)

        move = self.env["stock.move"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": self.product_serial.id,
                "product_uom_id": self.uom_dozen.id,
                "picking_type_id": self.picking_type_in.id,
            }
        )
        move.lot_ids = [Command.link(lot1.id)]
        move.lot_ids = [Command.link(lot2.id)]
        move.lot_ids = [Command.link(lot3.id)]
        self.assertEqual(move.quantity, 3.0 / 12.0)

    def test_do_not_merge_deliveries_with_different_partner(self):
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse test",
                "code": "TEST",
                "delivery_steps": "pick_ship",
            }
        )
        partner_1, partner_2 = self.env["res.partner"].create(
            [
                {
                    "name": "Bob",
                },
                {"name": "Jean"},
            ]
        )
        pick_1 = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.pick_type_id.id,
                "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "partner_id": partner_1.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 2,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                            "location_id": warehouse.lot_stock_id.id,
                        }
                    ),
                    Command.create(
                        {
                            "product_id": self.productB.id,
                            "product_uom_qty": 3,
                            "product_uom_id": self.productB.uom_id.id,
                            "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                            "location_id": warehouse.lot_stock_id.id,
                        }
                    ),
                ],
            }
        )
        pick_1.action_confirm()
        for move in pick_1.move_ids:
            move.quantity = move.product_uom_qty
        pick_1.button_validate()
        delivery_order_1 = self.env["stock.picking"].search(
            [
                ("partner_id", "=", partner_1.id),
                ("picking_type_id", "=", warehouse.out_type_id.id),
            ],
            limit=1,
        )
        self.assertEqual(delivery_order_1.partner_id, partner_1)
        self.assertEqual(
            delivery_order_1.move_ids.mapped("product_id"),
            self.productA | self.productB,
        )
        self.assertEqual(
            delivery_order_1.move_ids.mapped("product_uom_qty"), [2.0, 3.0]
        )
        pick_2 = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.pick_type_id.id,
                "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "partner_id": partner_2.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 1,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                            "location_id": warehouse.lot_stock_id.id,
                        }
                    )
                ],
            }
        )
        pick_2.action_confirm()
        pick_2.move_ids.quantity = 1
        pick_2.button_validate()
        self.assertEqual(
            delivery_order_1,
            self.env["stock.picking"].search(
                [
                    ("partner_id", "=", partner_1.id),
                    ("picking_type_id", "=", warehouse.out_type_id.id),
                ],
                limit=1,
            ),
        )
        delivery_order_2 = self.env["stock.picking"].search(
            [
                ("partner_id", "=", partner_2.id),
                ("picking_type_id", "=", warehouse.out_type_id.id),
            ],
            limit=1,
        )
        self.assertEqual(delivery_order_2.partner_id, partner_2)
        self.assertEqual(delivery_order_2.move_ids.mapped("product_id"), self.productA)
        self.assertEqual(delivery_order_2.move_ids.product_uom_qty, 1.0)

    def test_description_picking_consistent_with_product_description(self):
        self.warehouse_1.reception_steps = "two_steps"

        self.productA.product_tmpl_id.description_picking = "transfer"
        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "quantity": 1,
                            "description_picking": "receipt",
                        }
                    )
                ],
            }
        )
        receipt.button_validate()

        next_picking = receipt._get_next_transfers()
        self.assertEqual(next_picking.move_ids.description_picking, "transfer")


class TestPickShipBackorder(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type_out = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        cls.picking_type_out.use_create_lots = True
        cls.picking_type_out.write({"sequence_code": "WH/OUT"})

        cls.product_lot = cls.env["product.product"].create(
            {
                "name": "Lot Product",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )

        cls.lot1 = cls.env["stock.lot"].create(
            {
                "name": "LOT001",
                "product_id": cls.product_lot.id,
            }
        )
        cls.lot2 = cls.env["stock.lot"].create(
            {
                "name": "LOT002",
                "product_id": cls.product_lot.id,
            }
        )

        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = (
            cls.warehouse.out_type_id.default_location_src_id
            or cls.warehouse.lot_stock_id
        )

        cls.env["stock.quant"]._update_available_quantity(
            cls.product_lot, cls.stock_location, 5.0, lot_id=cls.lot1
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product_lot, cls.stock_location, 5.0, lot_id=cls.lot2
        )

    def test_pick_assign_and_backorder(self):
        cust = self.env.ref("stock.stock_location_customers")
        ref = self.env["stock.reference"].create({"name": "sale order"})
        self.warehouse.delivery_steps = "pick_ship"
        self.env["stock.rule"].run(
            [
                self.env["stock.rule"].Procurement(
                    self.product_lot,
                    10.0,
                    self.product_lot.uom_id,
                    cust,
                    "sale_order",
                    ref.name,
                    self.warehouse.company_id,
                    {"warehouse_id": self.warehouse, "reference_ids": ref},
                )
            ]
        )
        picking = self.env["stock.picking"].search([("origin", "=", ref.name)], limit=1)

        picking.action_confirm()
        picking.action_assign()

        move_line_obj = picking.move_ids.move_line_ids

        pack = self.env["stock.package"].create({"name": "Test Package"})
        move_line_obj[0].write({"quantity": 2.0, "lot_id": self.lot1})
        move_line_obj[1].write({"quantity": 2.0, "lot_id": self.lot2})
        picking.move_ids.move_line_ids = [
            Command.create(
                {
                    "picking_id": picking.id,
                    "move_id": picking.move_ids[0].id,
                    "product_id": self.product_lot.id,
                    "lot_id": self.lot1.id,
                    "quantity": 3.0,
                    "result_package_id": pack.id,
                }
            )
        ]

        picking.picking_type_id.create_backorder = "always"
        picking.button_validate()

        backorder = self.env["stock.picking"].search(
            [("backorder_id", "=", picking.id)]
        )

        self.assertTrue(backorder, "Backorder should exist")

        backorder.action_assign()
        backorder.button_validate()
        self.assertEqual(backorder.state, "done")
