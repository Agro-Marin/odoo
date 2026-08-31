from odoo.exceptions import UserError

from .blocked_location_common import BlockedLocationCase
from odoo.addons.stock.const import (
    CONTEXT_BLOCK_IS_INVENTORY,
    INTERNAL_CONTEXT_FLAG,
)


class TestBlockDirections(BlockedLocationCase):
    def test_soft_in_blocks_incoming(self):
        with self.assertRaises(UserError) as caught:
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.soft_in_location, 100.0
            )
        self.assertIn("soft block incoming", str(caught.exception).lower())
        self.assertEqual(self._on_hand(self.soft_in_location), 0.0)

    def test_soft_in_allows_outgoing(self):
        self._add_stock(self.soft_in_location, 100.0)
        self.Quant.with_user(self.normal_user)._update_available_quantity(
            self.product, self.soft_in_location, -40.0
        )
        self.assertEqual(self._on_hand(self.soft_in_location), 60.0)

    def test_soft_out_blocks_outgoing(self):
        self._add_stock(self.soft_out_location, 100.0)
        with self.assertRaises(UserError) as caught:
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.soft_out_location, -50.0
            )
        self.assertIn("soft block outgoing", str(caught.exception).lower())
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_soft_out_allows_incoming(self):
        self.Quant.with_user(self.normal_user)._update_available_quantity(
            self.product, self.soft_out_location, 100.0
        )
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_soft_both_blocks_both_directions(self):
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.soft_both_location, 100.0
            )
        self._add_stock(self.soft_both_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.soft_both_location, -50.0
            )
        self.assertEqual(self._on_hand(self.soft_both_location), 100.0)

    def test_hard_blocks_everything(self):
        with self.assertRaises(UserError) as caught:
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.hard_block_location, 100.0
            )
        self.assertIn("hard block", str(caught.exception).lower())
        self._add_stock(self.hard_block_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, self.hard_block_location, -50.0
            )
        self.assertEqual(self._on_hand(self.hard_block_location), 100.0)

    def test_unblocked_location_allows_everything(self):
        self.Quant.with_user(self.normal_user)._update_available_quantity(
            self.product, self.normal_location, 100.0
        )
        self.Quant.with_user(self.normal_user)._update_available_quantity(
            self.product, self.normal_location, -50.0
        )
        self.assertEqual(self._on_hand(self.normal_location), 50.0)

    def test_direction_must_be_in_or_out(self):
        with self.assertRaises(ValueError):
            self.soft_out_location._is_operation_allowed("outgoing")

    def test_unreserving_is_always_allowed(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, self.soft_out_location, quantity=0, reserved_quantity=50.0
        )
        self.Quant.with_user(self.normal_user)._update_available_quantity(
            self.product, self.soft_out_location, quantity=0, reserved_quantity=-50.0
        )
        quant = self.Quant.sudo().search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.soft_out_location.id),
            ],
        )
        self.assertEqual(sum(quant.mapped("reserved_quantity")), 0.0)


class TestBypasses(BlockedLocationCase):
    def test_sudo_bypasses_soft_and_hard(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, self.soft_out_location, -50.0
        )
        self._add_stock(self.hard_block_location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, self.hard_block_location, -50.0
        )
        self.assertEqual(self._on_hand(self.soft_out_location), 50.0)
        self.assertEqual(self._on_hand(self.hard_block_location), 50.0)

    def test_inventory_mode_bypasses_soft_block(self):
        self.Quant.with_user(self.normal_user).with_context(
            inventory_mode=True
        )._update_available_quantity(self.product, self.soft_out_location, 100.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_inventory_mode_does_not_bypass_hard_block(self):
        allowed = (
            self.hard_block_location.with_user(self.normal_user)
            .with_context(inventory_mode=True)
            ._is_operation_allowed("out")
        )
        self.assertFalse(allowed)

    def test_inventory_mode_bypass_requires_the_stock_group(self):
        allowed = (
            self.soft_out_location.with_user(self.vendor_user)
            .with_context(inventory_mode=True)
            ._is_operation_allowed("out")
        )
        self.assertFalse(allowed)

    def test_inventory_mode_bypass_works_for_the_stock_group(self):
        allowed = (
            self.soft_out_location.with_user(self.normal_user)
            .with_context(inventory_mode=True)
            ._is_operation_allowed("out")
        )
        self.assertTrue(allowed)

    def test_is_inventory_flag_bypasses_soft_block(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.Quant.with_user(self.normal_user).with_context(
            **{CONTEXT_BLOCK_IS_INVENTORY: INTERNAL_CONTEXT_FLAG}
        )._update_available_quantity(self.product, self.soft_out_location, -50.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 50.0)

    def test_is_inventory_flag_bypass_requires_the_stock_group(self):
        allowed = (
            self.soft_out_location.with_user(self.vendor_user)
            .with_context(**{CONTEXT_BLOCK_IS_INVENTORY: INTERNAL_CONTEXT_FLAG})
            ._is_operation_allowed("out")
        )
        self.assertFalse(allowed)

    def test_is_inventory_flag_bypass_works_for_the_stock_group(self):
        allowed = (
            self.soft_out_location.with_user(self.normal_user)
            .with_context(**{CONTEXT_BLOCK_IS_INVENTORY: INTERNAL_CONTEXT_FLAG})
            ._is_operation_allowed("out")
        )
        self.assertTrue(allowed)


class TestOverrideGroups(BlockedLocationCase):
    def test_force_in_allows_incoming(self):
        self.Quant.with_user(self.force_in_user)._update_available_quantity(
            self.product, self.soft_in_location, 100.0
        )
        self.assertEqual(self._on_hand(self.soft_in_location), 100.0)

    def test_force_out_allows_outgoing(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.Quant.with_user(self.force_out_user)._update_available_quantity(
            self.product, self.soft_out_location, -50.0
        )
        self.assertEqual(self._on_hand(self.soft_out_location), 50.0)

    def test_force_groups_cover_soft_both(self):
        self.Quant.with_user(self.force_in_user)._update_available_quantity(
            self.product, self.soft_both_location, 100.0
        )
        self.Quant.with_user(self.force_out_user)._update_available_quantity(
            self.product, self.soft_both_location, -50.0
        )
        self.assertEqual(self._on_hand(self.soft_both_location), 50.0)

    def test_hard_override_allows_hard_block(self):
        self.Quant.with_user(self.hard_override_user)._update_available_quantity(
            self.product, self.hard_block_location, 100.0
        )
        self.Quant.with_user(self.hard_override_user)._update_available_quantity(
            self.product, self.hard_block_location, -50.0
        )
        self.assertEqual(self._on_hand(self.hard_block_location), 50.0)

    def test_soft_groups_do_not_override_hard(self):
        with self.assertRaises(UserError):
            self.Quant.with_user(self.force_in_user)._update_available_quantity(
                self.product, self.hard_block_location, 100.0
            )
        self._add_stock(self.hard_block_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.force_out_user)._update_available_quantity(
                self.product, self.hard_block_location, -50.0
            )
        self.assertEqual(self._on_hand(self.hard_block_location), 100.0)


class TestHierarchy(BlockedLocationCase):
    def test_child_inherits_parent_block(self):
        child = self._create_location("Child", parent=self.soft_out_location)
        self.assertEqual(child.effective_block_type, "soft_out")
        self._add_stock(child, 100.0)
        with self.assertRaises(UserError) as caught:
            self.Quant.with_user(self.normal_user)._update_available_quantity(
                self.product, child, -50.0
            )
        self.assertIn("soft block outgoing", str(caught.exception).lower())

    def test_directions_merge_into_soft_both(self):
        parent = self._create_location("Parent In", block_type="soft_in")
        child = self._create_location("Child Out", block_type="soft_out", parent=parent)
        self.assertEqual(parent.effective_block_type, "soft_in")
        self.assertEqual(child.effective_block_type, "soft_both")

    def test_hard_wins_over_any_soft(self):
        parent = self._create_location("Parent Soft", block_type="soft_in")
        child = self._create_location("Child Hard", block_type="hard", parent=parent)
        grandchild = self._create_location("Grandchild", parent=child)
        self.assertEqual(child.effective_block_type, "hard")
        self.assertEqual(grandchild.effective_block_type, "hard")

    def test_effective_type_follows_a_parent_change(self):
        child = self._create_location("Mobile Child")
        self.assertEqual(child.effective_block_type, "none")
        child.location_id = self.hard_block_location
        self.assertEqual(child.effective_block_type, "hard")
        child.location_id = self.normal_location
        self.assertEqual(child.effective_block_type, "none")

    def test_effective_type_follows_an_ancestor_block(self):
        zone = self._create_location("Zone")
        shelf = self._create_location("Shelf", parent=zone)
        bin_ = self._create_location("Bin", parent=shelf)
        self.assertEqual(bin_.effective_block_type, "none")
        zone.write({"block_type": "hard"})
        self.assertEqual(shelf.effective_block_type, "hard")
        self.assertEqual(bin_.effective_block_type, "hard")
        zone.with_user(self.hard_override_user).write({"block_type": "none"})
        self.assertEqual(bin_.effective_block_type, "none")

    def test_effective_type_is_searchable(self):
        child = self._create_location(
            "Searchable Child", parent=self.hard_block_location
        )
        found = self.Location.search([("effective_block_type", "=", "hard")])
        self.assertIn(child, found)
        self.assertIn(self.hard_block_location, found)
        self.assertNotIn(self.normal_location, found)


class TestGathering(BlockedLocationCase):
    def test_gather_excludes_outgoing_blocked(self):
        for location in (
            self.soft_out_location,
            self.soft_both_location,
            self.hard_block_location,
        ):
            with self.subTest(block_type=location.block_type):
                self._add_stock(location, 100.0)
                quants = self.Quant.with_user(self.normal_user)._gather(
                    self.product, self.stock_location
                )
                self.assertNotIn(location, quants.location_id)
                self._add_stock(location, -100.0)

    def test_gather_includes_incoming_blocked(self):
        self._add_stock(self.soft_in_location, 100.0)
        quants = self.Quant.with_user(self.normal_user)._gather(
            self.product, self.stock_location
        )
        self.assertTrue(
            quants.filtered(lambda q: q.location_id == self.soft_in_location),
        )

    def test_gather_excludes_children_of_a_blocked_ancestor(self):
        child = self._create_location("Blocked Child", parent=self.soft_out_location)
        self._add_stock(child, 100.0)
        quants = self.Quant.with_user(self.normal_user)._gather(
            self.product, self.stock_location
        )
        self.assertFalse(quants.filtered(lambda q: q.location_id == child))

    def test_force_out_gathers_from_soft_but_not_hard(self):
        self._add_stock(self.soft_out_location, 100.0)
        self._add_stock(self.hard_block_location, 100.0)
        quants = self.Quant.with_user(self.force_out_user)._gather(
            self.product, self.stock_location
        )
        self.assertTrue(
            quants.filtered(lambda q: q.location_id == self.soft_out_location),
        )
        self.assertFalse(
            quants.filtered(lambda q: q.location_id == self.hard_block_location),
        )

    def test_hard_override_gathers_from_hard(self):
        self._add_stock(self.hard_block_location, 100.0)
        quants = self.Quant.with_user(self.hard_override_user)._gather(
            self.product, self.stock_location
        )
        self.assertTrue(
            quants.filtered(lambda q: q.location_id == self.hard_block_location),
        )

    def test_available_quantity_excludes_blocked_stock(self):
        self._add_stock(self.soft_out_location, 100.0)
        self._add_stock(self.normal_location, 50.0)
        self.assertEqual(
            self.Quant.with_user(self.normal_user)._get_available_quantity(
                self.product, self.stock_location
            ),
            50.0,
        )
        self.assertEqual(
            self.Quant.with_user(self.force_out_user)._get_available_quantity(
                self.product, self.stock_location
            ),
            150.0,
        )

    def test_new_reservation_from_soft_out_is_prevented(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._create_delivery(self.normal_user, self.soft_out_location, 50.0)
        picking.action_assign()
        self.assertNotEqual(picking.state, "assigned")
        self.assertFalse(picking.move_line_ids)

    def test_reservation_falls_back_to_unblocked_stock(self):
        blocked_child = self._create_location("Blocked", parent=self.stock_location)
        blocked_child.write({"block_type": "soft_out"})
        self._add_stock(blocked_child, 100.0)
        self._add_stock(self.normal_location, 3.0)
        picking = self._create_delivery(self.normal_user, self.stock_location, 10.0)
        picking.action_assign()
        self.assertEqual(sum(picking.move_line_ids.mapped("quantity_product_uom")), 3.0)
        self.assertFalse(
            picking.move_line_ids.filtered(
                lambda line: line.location_id == blocked_child
            ),
        )

    def test_gather_cost_does_not_grow_with_the_number_of_blocked_locations(self):
        self._add_stock(self.normal_location, 100.0)
        quant_user = self.Quant.with_user(self.normal_user)

        def gather_queries():
            self.env.invalidate_all()
            quant_user._gather(self.product, self.stock_location)
            before = self.env.cr.sql_log_count
            for _ in range(5):
                quant_user._gather(self.product, self.stock_location)
            return self.env.cr.sql_log_count - before

        self.Location.create(
            [
                {
                    "name": f"Blocked zone {index}",
                    "location_id": self.stock_location.id,
                    "block_type": "soft_out",
                }
                for index in range(2)
            ],
        )
        small = gather_queries()
        self.Location.create(
            [
                {
                    "name": f"Blocked zone bulk {index}",
                    "location_id": self.stock_location.id,
                    "block_type": "soft_out",
                }
                for index in range(200)
            ],
        )
        large = gather_queries()
        self.assertEqual(
            small,
            large,
            "gathering must cost the same with 2 and 202 blocked locations",
        )


class TestAutomatedReservation(BlockedLocationCase):
    def _pending_delivery(self, source, quantity=10.0):
        picking = self.Picking.with_user(self.normal_user).create(
            {
                "location_id": source.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            },
        )
        self.Move.with_user(self.normal_user).create(
            {
                "reference": f"auto {source.name}",
                "product_id": self.product.id,
                "product_uom_qty": quantity,
                "product_uom_id": self.product.uom_id.id,
                "picking_id": picking.id,
                "location_id": source.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        picking.action_confirm()
        return picking

    def _lines_from(self, picking, location):
        return picking.move_line_ids.filtered(
            lambda line: line.location_id == location,
        )

    def _run_scheduler(self):
        self.env["stock.scheduler"]._reserve_due_moves()

    def test_an_automated_assign_reserves_nothing_from_a_block(self):
        for location in (
            self.soft_out_location,
            self.soft_both_location,
            self.hard_block_location,
        ):
            with self.subTest(block_type=location.block_type):
                self._add_stock(location, 100.0)
                picking = self._pending_delivery(location)
                picking.move_ids.sudo()._action_assign()
                self.assertFalse(self._lines_from(picking, location))
                self.assertEqual(picking.state, "confirmed")
                self._add_stock(location, -100.0)

    def test_an_automated_assign_still_reserves_unblocked_stock(self):
        self._add_stock(self.normal_location, 100.0)
        picking = self._pending_delivery(self.normal_location)
        picking.move_ids.sudo()._action_assign()
        self.assertEqual(
            sum(self._lines_from(picking, self.normal_location).mapped("quantity")),
            10.0,
        )

    def test_the_scheduler_does_not_reserve_blocked_stock(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._pending_delivery(self.soft_out_location)
        self._run_scheduler()
        self.env.flush_all()
        self.assertFalse(self._lines_from(picking, self.soft_out_location))

    def test_the_scheduler_does_not_undo_an_unreserve(self):
        location = self._create_location("Counted Zone")
        self._add_stock(location, 100.0)
        picking = self._pending_delivery(location, 50.0)
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")

        location.sudo().write({"block_type": "hard"})
        location.sudo().action_unreserve_stock()
        self.env.flush_all()
        self.assertFalse(self._lines_from(picking, location))

        self._run_scheduler()
        self.env.flush_all()
        self.assertFalse(
            self._lines_from(picking, location),
            "the scheduler must not re-reserve a zone cleared for a count",
        )

    def test_an_operator_with_the_group_still_reserves_interactively(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._pending_delivery(self.soft_out_location)
        picking.with_user(self.force_out_user).action_assign()
        self.assertEqual(
            sum(
                self._lines_from(picking, self.soft_out_location).mapped(
                    "quantity_product_uom",
                ),
            ),
            10.0,
            "the fix must not take the override groups away from people",
        )
