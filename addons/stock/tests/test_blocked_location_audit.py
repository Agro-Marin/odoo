from markupsafe import Markup

from odoo.exceptions import AccessError, UserError, ValidationError

from .blocked_location_common import BlockedLocationCase


class TestBlockMetadata(BlockedLocationCase):
    def test_write_records_metadata(self):
        location = self._make_location("Metadata Target")
        self._add_stock(location, 100.0)
        location.with_user(self.manager_user).write(
            {"block_type": "soft_out", "block_reason": "Test reason"},
        )
        self.assertEqual(location.block_type, "soft_out")
        self.assertEqual(location.block_reason, "Test reason")
        self.assertTrue(location.blocked_date)
        self.assertEqual(location.blocked_by_user_id, self.manager_user)
        self.assertEqual(location.reserved_qty_when_blocked, 0.0)

    def test_create_records_metadata(self):
        location = self.Location.with_user(self.manager_user).create(
            {
                "name": "Born Blocked",
                "location_id": self.stock_location.id,
                "block_type": "hard",
                "block_reason": "Imported under a legal hold",
            },
        )
        self.assertTrue(location.blocked_date)
        self.assertEqual(location.blocked_by_user_id, self.manager_user)
        self.assertTrue(self._messages(location, "Location Blocked"))

    def test_create_unblocked_posts_nothing(self):
        location = self.Location.create(
            {"name": "Born Free", "location_id": self.stock_location.id},
        )
        self.assertFalse(self._messages(location, "Location Blocked"))
        self.assertFalse(location.blocked_date)

    def test_unblocking_clears_metadata(self):
        self.soft_out_location.write({"block_type": "none"})
        self.assertEqual(self.soft_out_location.block_type, "none")
        self.assertFalse(self.soft_out_location.blocked_date)
        self.assertFalse(self.soft_out_location.blocked_by_user_id)
        self.assertFalse(self.soft_out_location.block_reason)
        self.assertEqual(self.soft_out_location.reserved_qty_when_blocked, 0.0)
        self.assertTrue(self._messages(self.soft_out_location, "Location Unblocked"))

    def test_reserved_quantity_is_recorded(self):
        location = self._make_location("Reserved At Blocking")
        self._add_stock(location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, location, quantity=0, reserved_quantity=50.0
        )
        location.write({"block_type": "hard"})
        self.assertEqual(location.reserved_qty_when_blocked, 50.0)

    def test_reserved_quantity_includes_children(self):
        zone = self._make_location("Zone With Children")
        shelf = self._make_location("Shelf", parent=zone)
        self._add_stock(shelf, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, shelf, quantity=0, reserved_quantity=40.0
        )
        zone.write({"block_type": "hard"})
        self.assertEqual(zone.reserved_qty_when_blocked, 40.0)

    def test_batch_write_records_each_location_own_quantity(self):
        loc_a = self._make_location("Batch A")
        loc_b = self._make_location("Batch B")
        self._add_stock(loc_a, 100.0)
        self._add_stock(loc_b, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, loc_a, quantity=0, reserved_quantity=10.0
        )
        self.Quant.sudo()._update_available_quantity(
            self.product, loc_b, quantity=0, reserved_quantity=20.0
        )
        (loc_a | loc_b).write({"block_type": "hard"})
        self.assertEqual(loc_a.reserved_qty_when_blocked, 10.0)
        self.assertEqual(loc_b.reserved_qty_when_blocked, 20.0)

    def test_reserved_quantities_are_aggregated_in_one_query(self):
        def aggregation_cost(count, tag):
            locations = self.Location.create(
                [
                    {
                        "name": f"Bulk {tag} {index}",
                        "location_id": self.stock_location.id,
                    }
                    for index in range(count)
                ],
            )
            self.env.flush_all()
            self.env.invalidate_all()
            locations.mapped("parent_path")
            before = self.env.cr.sql_log_count
            locations._total_reserved_quantities()
            return self.env.cr.sql_log_count - before

        self.assertEqual(
            aggregation_cost(2, "small"),
            aggregation_cost(50, "large"),
            "reserved-quantity aggregation must not scale with the record count",
        )


class TestChatterRendering(BlockedLocationCase):
    def test_block_message_renders_as_html(self):
        location = self._make_location("Chatter Target")
        location.write({"block_type": "soft_out", "block_reason": "Quality hold"})
        body = self._messages(location, "Location Blocked")[:1].body
        self.assertIn("<b>", body, "the audit body must reach the reader as HTML")
        self.assertNotIn("&lt;b&gt;", body, "tags must not be shown as literal text")
        self.assertIn("Quality hold", body)

    def test_unblock_message_renders_as_html(self):
        self.soft_out_location.write({"block_type": "none"})
        body = self._messages(self.soft_out_location, "Location Unblocked")[:1].body
        self.assertIn("<b>", body)
        self.assertNotIn("&lt;b&gt;", body)

    def test_block_reason_is_escaped_not_injected(self):
        location = self._make_location("Injection Target")
        location.write(
            {
                "block_type": "soft_out",
                "block_reason": "<script>alert(1)</script>",
            },
        )
        body = self._messages(location, "Location Blocked")[:1].body
        self.assertIn("<b>", body)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_reason_falls_back_to_the_stored_one(self):
        location = self._make_location("Escalated")
        location.write({"block_type": "soft_out", "block_reason": "Batch #1 hold"})
        location.write({"block_type": "hard"})
        latest = self._messages(location, "Location Blocked")[:1].body
        self.assertIn("Hard Block", latest)
        self.assertIn("Batch #1 hold", latest)

    def test_hard_block_warns_about_reservations(self):
        location = self._make_location("Warn On Hard")
        self._add_stock(location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, location, quantity=0, reserved_quantity=25.0
        )
        location.write({"block_type": "hard"})
        body = self._messages(location, "Location Blocked")[:1].body
        self.assertIn("25.00", body)
        self.assertIn("⚠️", body)


class TestForcedOperationAudit(BlockedLocationCase):
    def test_soft_override_is_logged(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._make_delivery(self.force_out_user, self.soft_out_location, 50.0)
        picking.do_unreserve()
        picking.with_user(self.force_out_user).move_ids.quantity = 50.0
        picking.move_ids.picked = True
        picking.with_user(self.force_out_user).button_validate()
        logged = self._messages(picking, "Blocked location operation")
        self.assertTrue(logged)
        self.assertIn("Soft Block override", logged[0].body)
        self.assertIn("<b>", logged[0].body)
        self.assertNotIn("&lt;b&gt;", logged[0].body)

    def test_hard_override_is_logged(self):
        self._add_stock(self.hard_block_location, 100.0)
        picking = self._make_delivery(
            self.hard_override_user, self.hard_block_location, 50.0
        )
        picking.action_assign()
        self._fill_and_validate(picking, self.hard_override_user)
        logged = self._messages(picking, "Blocked location operation")
        self.assertTrue(logged)
        self.assertIn("Hard Block override", logged[0].body)

    def test_plain_completion_out_of_a_block_is_logged(self):
        location = self._make_location("Logged Completion")
        self._add_stock(location, 100.0)
        picking = self._make_delivery(self.normal_user, location, 50.0)
        picking.action_assign()
        location.write({"block_type": "soft_out"})
        self._fill_and_validate(picking, self.normal_user)
        logged = self._messages(picking, "Blocked location operation")
        self.assertTrue(logged)
        self.assertIn("completing a prior reservation", logged[0].body)

    def test_a_group_holder_is_always_recorded_as_an_override(self):
        location = self._make_location("Group Holder Completion")
        self._add_stock(location, 100.0)
        picking = self._make_delivery(self.force_out_user, location, 50.0)
        picking.action_assign()
        location.write({"block_type": "soft_out"})
        self._fill_and_validate(picking, self.force_out_user)
        logged = self._messages(picking, "Blocked location operation")
        self.assertTrue(logged)
        self.assertIn("Soft Block override", logged[0].body)
        self.assertIn(self.force_out_user.name, logged[0].body)

    def test_unblocked_operations_are_not_logged(self):
        self._add_stock(self.normal_location, 100.0)
        picking = self._make_delivery(self.normal_user, self.normal_location, 50.0)
        picking.action_assign()
        self._fill_and_validate(picking, self.normal_user)
        self.assertFalse(self._messages(picking, "Blocked location operation"))

    def test_pickingless_move_is_logged_on_the_location(self):
        self._add_stock(self.hard_block_location, 100.0)
        move = self.Move.with_user(self.hard_override_user).create(
            {
                "reference": "Pickingless",
                "product_id": self.product.id,
                "product_uom_qty": 5.0,
                "product_uom_id": self.product.uom_id.id,
                "location_id": self.hard_block_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move._action_confirm()
        move.quantity = 5.0
        move.picked = True
        move.with_user(self.hard_override_user)._action_done()
        self.assertEqual(move.state, "done")
        self.assertTrue(
            self._messages(self.hard_block_location, "Blocked location operation"),
        )

    def test_audit_body_is_markup(self):
        entries = []
        body = self.Move._blocked_audit_body(entries)
        self.assertIsInstance(body, Markup)


class TestGovernance(BlockedLocationCase):
    def test_hard_block_cannot_be_lifted_without_the_override_group(self):
        with self.assertRaises(UserError) as caught:
            self.hard_block_location.with_user(self.manager_user).write(
                {"block_type": "none"},
            )
        self.assertIn("hard block", str(caught.exception).lower())
        self.assertEqual(self.hard_block_location.block_type, "hard")

    def test_hard_block_cannot_be_weakened_without_the_override_group(self):
        with self.assertRaises(UserError):
            self.hard_block_location.with_user(self.manager_user).write(
                {"block_type": "soft_out"},
            )

    def test_hard_block_can_be_lifted_with_the_override_group(self):
        self.hard_block_location.with_user(self.hard_override_user).write(
            {"block_type": "none"},
        )
        self.assertEqual(self.hard_block_location.block_type, "none")

    def test_applying_a_hard_block_needs_no_special_group(self):
        location = self._make_location("Freezable")
        location.with_user(self.manager_user).write({"block_type": "hard"})
        self.assertEqual(location.block_type, "hard")

    def test_soft_blocks_stay_liftable_by_a_manager(self):
        self.soft_out_location.with_user(self.manager_user).write(
            {"block_type": "none"},
        )
        self.assertEqual(self.soft_out_location.block_type, "none")

    def test_system_flows_are_not_gated(self):
        self.hard_block_location.sudo().write({"block_type": "none"})
        self.assertEqual(self.hard_block_location.block_type, "none")

    def test_non_internal_locations_cannot_be_blocked(self):
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        with self.assertRaises(ValidationError) as caught:
            warehouse.view_location_id.write({"block_type": "hard"})
        self.assertIn("internal", str(caught.exception).lower())

    def test_customer_locations_cannot_be_blocked(self):
        with self.assertRaises(ValidationError):
            self.customer_location.write({"block_type": "soft_in"})

    def test_creating_a_blocked_non_internal_location_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Location.create(
                {
                    "name": "Blocked View",
                    "location_id": self.stock_location.id,
                    "usage": "view",
                    "block_type": "hard",
                },
            )


class TestUnreserveAction(BlockedLocationCase):
    def _reserved_lines(self, location):
        return self.MoveLine.sudo().search(
            [
                ("location_id", "child_of", location.id),
                ("state", "not in", ("done", "cancel", "draft")),
            ],
        )

    def test_unreserve_clears_reservations_and_logs(self):
        location = self._make_location("To Unreserve")
        self._add_stock(location, 100.0)
        picking = self._make_delivery(self.normal_user, location, 50.0)
        picking.action_assign()
        self.assertTrue(self._reserved_lines(location))

        location.write({"block_type": "hard"})
        location.action_unreserve_stock()

        self.assertFalse(self._reserved_lines(location))
        self.assertTrue(self._messages(location, "Hard Block Auto-Unreserve"))

    def test_unreserve_works_on_a_child_of_a_hard_blocked_parent(self):
        zone = self._make_location("Count Zone")
        shelf = self._make_location("Count Shelf", parent=zone)
        self._add_stock(shelf, 100.0)
        picking = self._make_delivery(self.normal_user, shelf, 50.0)
        picking.action_assign()
        self.assertTrue(self._reserved_lines(shelf))

        zone.write({"block_type": "hard"})
        result = shelf.action_unreserve_stock()

        self.assertEqual(result["params"]["type"], "success")
        self.assertFalse(self._reserved_lines(shelf))

    def test_unreserve_refuses_on_a_soft_block(self):
        result = self.soft_out_location.action_unreserve_stock()
        self.assertEqual(result["params"]["type"], "warning")

    def test_unreserve_message_counts_lines_not_summed_quantities(self):
        other = self._make_product("Other Unit Product")
        location = self._make_location("Mixed Unreserve")
        self._add_stock(location, 100.0)
        self._add_stock(location, 100.0, product=other)
        for product in (self.product, other):
            picking = self._make_delivery(
                self.normal_user, location, 10.0, product=product
            )
            picking.action_assign()

        location.write({"block_type": "hard"})
        location.action_unreserve_stock()

        body = self._messages(location, "Hard Block Auto-Unreserve")[:1].body
        self.assertIn("2 stock move line(s)", body)


class TestHardBlockGovernance(BlockedLocationCase):
    def test_reparenting_out_of_a_hard_block_needs_the_override(self):
        zone = self._make_location("Governed Zone")
        shelf = self._make_location("Governed Shelf", parent=zone)
        zone.write({"block_type": "hard"})
        self.assertEqual(shelf.effective_block_type, "hard")
        with self.assertRaises(UserError) as caught:
            shelf.with_user(self.manager_user).write(
                {"location_id": self.normal_location.id},
            )
        self.assertIn("hard", str(caught.exception).lower())
        self.assertEqual(shelf.effective_block_type, "hard")

    def test_reparenting_out_of_a_hard_block_works_with_the_override(self):
        zone = self._make_location("Freeable Zone")
        shelf = self._make_location("Freeable Shelf", parent=zone)
        zone.write({"block_type": "hard"})
        shelf.with_user(self.hard_override_user).write(
            {"location_id": self.normal_location.id},
        )
        self.assertEqual(shelf.effective_block_type, "none")

    def test_reparenting_between_hard_blocks_is_allowed(self):
        zone = self._make_location("Origin Zone", block_type="hard")
        shelf = self._make_location("Travelling Shelf", parent=zone)
        shelf.with_user(self.manager_user).write(
            {"location_id": self.hard_block_location.id},
        )
        self.assertEqual(shelf.effective_block_type, "hard")

    def test_reparenting_an_own_hard_block_is_allowed(self):
        shelf = self._make_location("Self Blocked", block_type="hard")
        shelf.with_user(self.manager_user).write(
            {"location_id": self.normal_location.id},
        )
        self.assertEqual(shelf.effective_block_type, "hard")

    def test_reparenting_a_soft_block_is_not_gated(self):
        zone = self._make_location("Soft Zone", block_type="soft_out")
        shelf = self._make_location("Soft Shelf", parent=zone)
        shelf.with_user(self.manager_user).write(
            {"location_id": self.normal_location.id},
        )
        self.assertEqual(shelf.effective_block_type, "none")

    def test_archiving_a_hard_blocked_location_needs_the_override(self):
        location = self._make_location("Archivable", block_type="hard")
        with self.assertRaises(UserError):
            location.with_user(self.manager_user).write({"active": False})
        self.assertTrue(location.active)
        location.with_user(self.hard_override_user).write({"active": False})
        self.assertFalse(location.active)

    def test_unrelated_writes_stay_ungated(self):
        self.hard_block_location.with_user(self.manager_user).write(
            {"block_reason": "still frozen"},
        )
        self.assertEqual(self.hard_block_location.block_reason, "still frozen")


class TestUnreservePermission(BlockedLocationCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.override_only_user = cls._make_user(
            "Override Only", cls.group_stock_user, cls.group_hard_override
        )

    def _blocked_with_reservation(self, name):
        location = self._make_location(name)
        self._add_stock(location, 100.0)
        picking = self._make_delivery(self.normal_user, location, 50.0)
        picking.action_assign()
        location.sudo().write({"block_type": "hard"})
        return location

    def _reserved_lines(self, location):
        return self.MoveLine.sudo().search(
            [
                ("location_id", "child_of", location.id),
                ("state", "not in", ("done", "cancel", "draft")),
            ],
        )

    def test_unreserve_needs_the_hard_override(self):
        location = self._blocked_with_reservation("Guarded Unreserve")
        with self.assertRaises(UserError) as caught:
            location.with_user(self.manager_user).action_unreserve_stock()
        self.assertIn("hard", str(caught.exception).lower())
        self.assertTrue(self._reserved_lines(location))

    def test_unreserve_works_without_write_access_on_the_location(self):
        location = self._blocked_with_reservation("Chatter Unreserve")
        location.with_user(self.override_only_user).action_unreserve_stock()
        self.assertFalse(self._reserved_lines(location))
        self.assertTrue(self._messages(location, "Hard Block Auto-Unreserve"))

    def test_blocking_posts_chatter_without_write_access_on_mail(self):
        location = self._make_location("Chatter Block")
        location.sudo().write({"block_type": "soft_out"})
        self.assertTrue(self._messages(location, "Location Blocked"))

    def test_the_override_group_does_not_replace_stock_rights(self):
        outsider = self._make_user(
            "Override Outsider",
            self.env.ref("base.group_user"),
            self.group_hard_override,
        )
        self.assertTrue(
            outsider.has_group("stock.group_override_hard_block"),
        )
        self.assertFalse(outsider.has_group("stock.group_stock_user"))
        location = self._blocked_with_reservation("Outsider Unreserve")

        self.assertTrue(
            location.with_user(outsider)._is_operation_allowed("out"),
            "the module's own gate should let the group holder through",
        )
        with self.assertRaises(
            AccessError,
            msg="core must still refuse a holder who has no inventory rights",
        ):
            location.with_user(outsider).action_unreserve_stock()
        self.assertTrue(self._reserved_lines(location))

    def test_the_reload_travels_inside_params(self):
        location = self._blocked_with_reservation("Reload Target")
        action = location.with_user(self.override_only_user).action_unreserve_stock()
        self.assertEqual(action["params"]["next"]["tag"], "soft_reload")
        self.assertNotIn("next", action)


class TestAuditAccuracy(BlockedLocationCase):
    def test_a_cancelled_line_is_not_audited(self):
        blocked = self._make_location("Never Shipped")
        self._add_stock(blocked, 100.0)
        self._add_stock(self.normal_location, 100.0)
        picking = self.Picking.with_user(self.normal_user).create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            },
        )
        shipped, dropped = self.Move.with_user(self.normal_user).create(
            [
                {
                    "reference": "shipped",
                    "product_id": self.product.id,
                    "product_uom_qty": 10.0,
                    "product_uom_id": self.product.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": self.normal_location.id,
                    "location_dest_id": self.customer_location.id,
                },
                {
                    "reference": "dropped",
                    "product_id": self.product.id,
                    "product_uom_qty": 10.0,
                    "product_uom_id": self.product.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": blocked.id,
                    "location_dest_id": self.customer_location.id,
                },
            ],
        )
        picking.action_confirm()
        picking.action_assign()
        blocked.sudo().write({"block_type": "soft_out"})

        for line in shipped.move_line_ids:
            line.quantity = line.quantity_product_uom
        shipped.picked = True
        picking.with_user(self.normal_user).with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()

        self.assertEqual(dropped.state, "cancel")
        self.assertEqual(self._on_hand(blocked), 100.0)
        self.assertFalse(
            self._messages(picking, "Blocked location operation"),
            "a cancelled line must not be recorded as having left a block",
        )

    def test_a_completed_line_is_still_audited(self):
        location = self._make_location("Really Shipped")
        self._add_stock(location, 100.0)
        picking = self._make_delivery(self.normal_user, location, 50.0)
        picking.action_assign()
        location.write({"block_type": "soft_out"})
        self._fill_and_validate(picking, self.normal_user)
        logged = self._messages(picking, "Blocked location operation")
        self.assertTrue(logged)
        self.assertIn("50 Units", logged[0].body)

    def test_a_mixed_batch_does_not_inherit_the_inventory_bypass(self):
        location = self._make_location("Mixed Batch", block_type="soft_out")
        allowed = (
            location.with_user(self.normal_user)
            .with_context(stock_blocked_is_inventory=True)
            ._is_operation_allowed("out")
        )
        self.assertFalse(allowed)


class TestReservedQuantityReporting(BlockedLocationCase):
    def test_the_chatter_splits_reserved_quantities_by_unit(self):
        kilogram = self.env.ref("uom.product_uom_kgm")
        heavy = (
            self.env["product.template"]
            .create(
                {
                    "name": "Heavy Thing",
                    "type": "consu",
                    "is_storable": True,
                    "uom_id": kilogram.id,
                },
            )
            .product_variant_ids[:1]
        )
        location = self._make_location("Mixed Units")
        self._add_stock(location, 100.0)
        self._add_stock(location, 100.0, product=heavy)
        self.Quant.sudo()._update_available_quantity(
            self.product, location, quantity=0, reserved_quantity=10.0
        )
        self.Quant.sudo()._update_available_quantity(
            heavy, location, quantity=0, reserved_quantity=5.0
        )

        location.write({"block_type": "hard"})

        body = self._messages(location, "Location Blocked")[:1].body
        self.assertIn("10.00 Units", body)
        self.assertIn(f"5.00 {kilogram.name}", body)
        self.assertNotIn("15.00 units are currently reserved", body)

    def test_a_single_unit_location_still_reports_one_figure(self):
        location = self._make_location("One Unit")
        self._add_stock(location, 100.0)
        self.Quant.sudo()._update_available_quantity(
            self.product, location, quantity=0, reserved_quantity=25.0
        )
        location.write({"block_type": "hard"})
        self.assertEqual(location.reserved_qty_when_blocked, 25.0)
        self.assertIn(
            "25.00 Units", self._messages(location, "Location Blocked")[0].body
        )
