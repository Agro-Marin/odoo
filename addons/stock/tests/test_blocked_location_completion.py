from odoo.exceptions import UserError

from .blocked_location_common import BlockedLocationCase


class TestCompletion(BlockedLocationCase):
    def _unreserved_delivery(self, location, quantity=10.0):
        picking = self._create_delivery(self.normal_user, location, quantity)
        picking.do_unreserve()
        return picking

    def test_reserved_completion_passes_a_soft_block(self):
        location = self._create_location("Blocked After Reserving")
        self._add_stock(location, 100.0)
        picking = self._create_delivery(self.normal_user, location, 50.0)
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")

        location.write({"block_type": "soft_out"})

        self._update_quantities_and_validate(picking, self.normal_user)
        self.assertEqual(picking.state, "done")
        self.assertEqual(self._on_hand(location), 50.0)

    def test_unreserved_quantity_cannot_leave_a_soft_block(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._unreserved_delivery(self.soft_out_location)
        with self.assertRaises(UserError) as caught:
            picking.with_user(self.normal_user).move_ids.quantity = 10.0
        self.assertIn("soft block outgoing", str(caught.exception).lower())
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_unreserved_quantity_cannot_leave_a_soft_both_block(self):
        self._add_stock(self.soft_both_location, 100.0)
        picking = self._unreserved_delivery(self.soft_both_location)
        with self.assertRaises(UserError):
            picking.with_user(self.normal_user).move_ids.quantity = 10.0
        self.assertEqual(self._on_hand(self.soft_both_location), 100.0)

    def test_unreserved_quantity_cannot_leave_a_blocked_child(self):
        child = self._create_location("Blocked Child", parent=self.soft_out_location)
        self._add_stock(child, 100.0)
        picking = self._unreserved_delivery(child)
        with self.assertRaises(UserError):
            picking.with_user(self.normal_user).move_ids.quantity = 10.0

    def test_unreserved_quantity_leaves_an_unblocked_location(self):
        self._add_stock(self.normal_location, 100.0)
        picking = self._unreserved_delivery(self.normal_location)
        picking.with_user(self.normal_user).move_ids.quantity = 10.0
        picking.move_ids.picked = True
        picking.with_user(self.normal_user).button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(self._on_hand(self.normal_location), 90.0)

    def test_override_group_still_forces_an_unreserved_pick(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._create_delivery(
            self.force_out_user, self.soft_out_location, 10.0
        )
        picking.do_unreserve()
        picking.with_user(self.force_out_user).move_ids.quantity = 10.0
        picking.move_ids.picked = True
        picking.with_user(self.force_out_user).button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(self._on_hand(self.soft_out_location), 90.0)

    def test_system_flows_still_move_stock_out(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._unreserved_delivery(self.soft_out_location)
        picking.sudo().move_ids.quantity = 10.0
        picking.sudo().move_ids.picked = True
        picking.sudo().button_validate()
        self.assertEqual(self._on_hand(self.soft_out_location), 90.0)

    def test_hard_block_stops_even_a_reserved_completion(self):
        location = self._create_location("Hard After Reserving")
        self._add_stock(location, 100.0)
        picking = self._create_delivery(self.normal_user, location, 50.0)
        picking.action_assign()

        location.write({"block_type": "hard"})

        for line in picking.move_line_ids:
            line.quantity = line.quantity_product_uom
        picking.move_ids.picked = True
        with self.assertRaises(UserError) as caught:
            picking.with_user(self.normal_user).button_validate()
        self.assertIn("hard block", str(caught.exception).lower())
        self.assertEqual(self._on_hand(location), 100.0)

    def test_a_new_line_added_after_the_block_is_refused(self):
        location = self._create_location("Extra Line")
        self._add_stock(location, 100.0)
        picking = self._create_delivery(self.normal_user, location, 10.0)
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")

        location.write({"block_type": "soft_out"})

        with self.assertRaises(UserError):
            self.MoveLine.with_user(self.normal_user).create(
                {
                    "move_id": picking.move_ids[0].id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "location_id": location.id,
                    "location_dest_id": self.customer_location.id,
                    "quantity": 5.0,
                },
            )

    def test_raising_the_quantity_on_an_existing_line_is_refused(self):
        location = self._create_location("Grown Line")
        self._add_stock(location, 100.0)
        picking = self._create_delivery(self.normal_user, location, 10.0)
        picking.action_assign()

        location.write({"block_type": "soft_out"})

        line = picking.move_line_ids.with_user(self.normal_user)
        with self.assertRaises(UserError):
            line.quantity = 50.0

    def test_lowering_the_quantity_on_an_existing_line_is_allowed(self):
        location = self._create_location("Shrunk Line")
        self._add_stock(location, 100.0)
        picking = self._create_delivery(self.normal_user, location, 10.0)
        picking.action_assign()

        location.write({"block_type": "soft_out"})

        line = picking.move_line_ids.with_user(self.normal_user)
        line.quantity = 4.0
        self.assertEqual(line.quantity, 4.0)

    def test_moving_a_line_onto_a_blocked_source_is_refused(self):
        self._add_stock(self.normal_location, 100.0)
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._create_delivery(self.normal_user, self.stock_location, 10.0)
        picking.action_assign()
        line = picking.move_line_ids.with_user(self.normal_user)
        self.assertTrue(line)
        with self.assertRaises(UserError):
            line.location_id = self.soft_out_location

    def test_scrap_passes_a_soft_block(self):
        self._add_stock(self.soft_out_location, 100.0)
        scrap = (
            self.env["stock.scrap"]
            .with_user(self.normal_user)
            .create(
                {
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "scrap_qty": 5.0,
                    "location_id": self.soft_out_location.id,
                },
            )
        )
        scrap.action_validate()
        self.assertEqual(scrap.state, "done")
        self.assertEqual(self._on_hand(self.soft_out_location), 95.0)

    def test_scrap_is_still_stopped_by_a_hard_block(self):
        self._add_stock(self.hard_block_location, 100.0)
        scrap = (
            self.env["stock.scrap"]
            .with_user(self.normal_user)
            .create(
                {
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "scrap_qty": 5.0,
                    "location_id": self.hard_block_location.id,
                },
            )
        )
        with self.assertRaises(UserError) as caught:
            scrap.action_validate()
        self.assertIn("hard block", str(caught.exception).lower())
        self.assertEqual(self._on_hand(self.hard_block_location), 100.0)

    def test_inventory_loss_passes_a_soft_block(self):
        location = self._create_location("Counted Down", block_type="soft_out")
        self._add_stock(location, 100.0)
        self.env.flush_all()
        counted = (
            self.Quant.with_user(self.normal_user)
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product.id,
                    "location_id": location.id,
                    "inventory_quantity": 80.0,
                },
            )
        )
        counted.with_user(self.normal_user).with_context(
            inventory_mode=True
        ).action_apply_inventory()
        self.env.flush_all()
        self.assertEqual(self._on_hand(location), 80.0)

    def test_inventory_loss_is_still_stopped_by_a_hard_block(self):
        location = self._create_location("Frozen Count", block_type="hard")
        self._add_stock(location, 100.0)
        self.env.flush_all()
        counted = (
            self.Quant.with_user(self.normal_user)
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product.id,
                    "location_id": location.id,
                    "inventory_quantity": 80.0,
                },
            )
        )
        with self.assertRaises(UserError):
            counted.with_user(self.normal_user).with_context(
                inventory_mode=True
            ).action_apply_inventory()
        self.assertEqual(self._on_hand(location), 100.0)

    def test_a_transit_destination_is_still_a_pick(self):
        transit = self.Location.sudo().create(
            {
                "name": "Inter-warehouse transit",
                "location_id": self.stock_location.location_id.id,
                "usage": "transit",
            },
        )
        self._add_stock(self.soft_out_location, 100.0)
        move = self.Move.with_user(self.normal_user).create(
            {
                "reference": "To transit",
                "product_id": self.product.id,
                "product_uom_qty": 5.0,
                "product_uom_id": self.product.uom_id.id,
                "location_id": self.soft_out_location.id,
                "location_dest_id": transit.id,
            },
        )
        move._action_confirm()
        with self.assertRaises(UserError):
            move.with_user(self.normal_user).quantity = 5.0

    def test_incoming_side_is_unaffected_by_the_outgoing_gate(self):
        picking = self.Picking.with_user(self.normal_user).create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.soft_in_location.id,
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
            },
        )
        self.Move.with_user(self.normal_user).create(
            {
                "reference": "Receipt into soft_in",
                "product_id": self.product.id,
                "product_uom_qty": 10.0,
                "product_uom_id": self.product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.soft_in_location.id,
            },
        )
        picking.action_confirm()
        picking.action_assign()
        with self.assertRaises(UserError) as caught:
            self._update_quantities_and_validate(picking, self.normal_user)
        self.assertIn("soft block incoming", str(caught.exception).lower())
