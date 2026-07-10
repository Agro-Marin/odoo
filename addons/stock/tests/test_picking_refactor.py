from odoo.exceptions import UserError

from odoo.addons.stock.tests.common import TestStockCommon


class TestPickingRefactor(TestStockCommon):
    """Regression tests for the `stock.picking` refactor (marin fork).

    Each test pins a bug that was fixed while refactoring `stock_picking.py`, so a
    future change that reintroduces it fails loudly.
    """

    def _new_picking(self, picking_type):
        return self.PickingObj.create({"picking_type_id": picking_type.id})

    def test_write_picking_type_keeps_explicit_location(self):
        """Changing `picking_type_id` and passing an explicit `location_id` in the same
        `write` must keep the caller's location (it used to be silently overwritten by
        the new type's default source location).
        """
        picking = self._new_picking(self.picking_type_in)
        self.assertNotEqual(
            self.shelf_1,
            self.picking_type_out.default_location_src_id,
            "test precondition: explicit location must differ from the type default",
        )
        picking.write(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.shelf_1.id,
            },
        )
        self.assertEqual(picking.location_id, self.shelf_1)

    def test_write_picking_type_defaults_location_when_not_given(self):
        """When no explicit location is passed, changing the type still adopts the new
        type's default locations (the `setdefault` path).
        """
        picking = self._new_picking(self.picking_type_in)
        picking.write({"picking_type_id": self.picking_type_out.id})
        self.assertEqual(
            picking.location_id,
            self.picking_type_out.default_location_src_id,
        )
        self.assertEqual(
            picking.location_dest_id,
            self.picking_type_out.default_location_dest_id,
        )

    def test_shipping_volume_recomputes_on_quantity_change(self):
        """`shipping_volume` is a non-stored compute; without its `@api.depends` it
        served a stale cached value after the move quantity changed.
        """
        self.product_2.volume = 2.0
        picking = self._new_picking(self.picking_type_out)
        move = self.MoveObj.create(
            {
                "product_id": self.product_2.id,
                "product_uom_qty": 3,
                "product_uom": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move.quantity = 3
        self.assertEqual(picking.shipping_volume, 6.0)
        move.quantity = 5
        self.assertEqual(
            picking.shipping_volume,
            10.0,
            "shipping_volume must follow move.quantity (stale cache regression)",
        )

    def test_entire_pack_move_line_vals_use_company_not_picking_id(self):
        """`_prepare_entire_pack_move_line_vals` set `company_id` to the picking id
        instead of the company id.
        """
        product = self.ProductObj.create({"name": "Packed", "is_storable": True})
        package = self.env["stock.package"].create({})
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "quantity": 4,
                "package_id": package.id,
            },
        )
        picking = self._new_picking(self.picking_type_out)
        vals = picking._prepare_entire_pack_move_line_vals(package)
        self.assertTrue(vals, "the package quant should yield one move-line vals dict")
        self.assertEqual(vals[0]["company_id"], picking.company_id.id)
        self.assertNotEqual(vals[0]["company_id"], picking.id)

    def test_has_deadline_issue_reflects_dates(self):
        """`has_deadline_issue` is True only when a deadline precedes the scheduled date."""
        from datetime import datetime

        picking = self._new_picking(self.picking_type_out)
        move = self.MoveObj.create(
            {
                "product_id": self.product_2.id,
                "product_uom_qty": 1,
                "product_uom": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "date": datetime(2026, 2, 1),
                "date_deadline": datetime(2026, 1, 1),
            },
        )
        # deadline (Jan) is before the scheduled date (Feb) -> late
        self.assertTrue(picking.has_deadline_issue)
        move.date_deadline = datetime(2026, 3, 1)  # now after the scheduled date
        self.assertFalse(picking.has_deadline_issue)

    def test_show_allocation_batched_matches_per_picking(self):
        """The batched `_compute_show_allocation` must equal the per-picking
        `_get_show_allocation`, and be True exactly when allocatable demand exists.
        """
        self.env.user.group_ids = [
            (4, self.env.ref("stock.group_reception_report").id),
        ]
        product = self.ProductObj.create({"name": "RecvX", "is_storable": True})
        receipt = self.PickingObj.create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "product_uom": product.uom_id.id,
                "picking_id": receipt.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        receipt.action_confirm()

        # No demand in the warehouse yet -> nothing to allocate.
        receipt.invalidate_recordset(["show_allocation"])
        self.assertFalse(receipt.show_allocation)
        self.assertEqual(
            receipt.show_allocation,
            bool(receipt._get_show_allocation(receipt.picking_type_id)),
        )

        # Outgoing demand for the same product, sourced from stock -> allocatable.
        delivery = self.PickingObj.create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "product_uom": product.uom_id.id,
                "picking_id": delivery.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        delivery.action_confirm()

        receipt.invalidate_recordset(["show_allocation"])
        self.assertTrue(receipt.show_allocation)
        self.assertEqual(
            receipt.show_allocation,
            bool(receipt._get_show_allocation(receipt.picking_type_id)),
        )

    def test_action_split_transfer_requires_single_record(self):
        """`action_split_transfer` operates on one transfer; calling it on several must
        raise rather than silently mixing moves across pickings.
        """
        pickings = self._new_picking(self.picking_type_out) | self._new_picking(
            self.picking_type_out,
        )
        with self.assertRaises(ValueError):
            pickings.action_split_transfer()

    def test_bulk_weight_sums_move_line_quantities(self):
        """`_compute_bulk_weight` sums the quantities of the unpackaged move lines
        (refactored from a group-by-quantity + count read_group to `quantity:sum`).
        Distinct quantities for the same product must all be counted.
        """
        self.product_2.weight = 2.0
        picking = self._new_picking(self.picking_type_out)
        move = self.MoveObj.create(
            {
                "product_id": self.product_2.id,
                "product_uom_qty": 8,
                "product_uom": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        common = {
            "product_id": self.product_2.id,
            "product_uom_id": self.product_2.uom_id.id,
            "picking_id": picking.id,
            "move_id": move.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        }
        self.env["stock.move.line"].create(
            [{**common, "quantity": q} for q in (3.0, 2.0, 3.0)],
        )
        picking.invalidate_recordset(["weight_bulk"])
        # (3 + 2 + 3) units * 2.0 kg/unit
        self.assertEqual(picking.weight_bulk, 16.0)

    def test_get_report_lang_requires_single_record(self):
        """`_get_report_lang` renders one document at a time; it now asserts a single
        record, so a multi-record set must raise rather than silently pick the first.
        """
        p1 = self._new_picking(self.picking_type_out)
        p2 = self._new_picking(self.picking_type_out)
        self.assertEqual(p1._get_report_lang(), self.env.lang)
        with self.assertRaises(ValueError):
            (p1 | p2)._get_report_lang()

    def test_allocation_allowed_move_states_helper(self):
        """The shared allocation state helper is the single source of truth for the
        reception report and both show-allocation paths.
        """
        self.assertEqual(
            self.PickingObj._get_allocation_allowed_move_states(),
            ["confirmed", "partially_available", "waiting"],
        )
        self.assertEqual(
            self.PickingObj._get_allocation_allowed_move_states(include_assigned=True),
            ["confirmed", "partially_available", "waiting", "assigned"],
        )

    def test_allocation_source_location_ids_excludes_suppliers(self):
        """The shared source-location helper returns warehouse-internal locations and
        never supplier locations.
        """
        view_location = self.picking_type_in.warehouse_id.view_location_id
        ids = self.PickingObj._get_allocation_source_location_ids(view_location.ids)
        locations = self.env["stock.location"].browse(ids)
        self.assertIn(self.stock_location, locations)
        self.assertFalse(
            locations.filtered(lambda loc: loc.usage == "supplier"),
            "supplier locations must be excluded from allocation source locations",
        )

    def _two_types_sharing(self, **overrides):
        """Two picking types with independent sequences (so picking names don't clash)
        and the same field overrides applied to both. All auto-print flags are cleared
        first so a test can isolate exactly one report type.
        """
        Seq = self.env["ir.sequence"]
        auto_off = dict.fromkeys(
            (
                "auto_print_delivery_slip",
                "auto_print_return_slip",
                "auto_print_product_labels",
                "auto_print_lot_labels",
                "auto_print_reception_report",
                "auto_print_reception_report_labels",
                "auto_print_packages",
                "auto_print_package_label",
            ),
            False,
        )
        pt_a = self.picking_type_out.copy(
            {
                "name": "Share A",
                "sequence_id": Seq.create(
                    {"name": "SA", "prefix": "SA/", "padding": 5}
                ).id,
            },
        )
        pt_b = self.picking_type_out.copy(
            {
                "name": "Share B",
                "sequence_id": Seq.create(
                    {"name": "SB", "prefix": "SB/", "padding": 5}
                ).id,
            },
        )
        (pt_a | pt_b).write({**auto_off, **overrides})
        return pt_a, pt_b

    def test_autoprint_product_labels_multi_type_same_format(self):
        """Two picking types sharing a product-label format, validated together, must
        produce exactly one product-label action — no singleton crash from reading the
        format off a multi-type recordset, and no duplicate action from iterating types.
        """
        pt_a, pt_b = self._two_types_sharing(
            auto_print_product_labels=True,
            product_label_format="zpl",
        )
        product = self.ProductObj.create({"name": "Labeled", "is_storable": True})
        pickings = self.env["stock.picking"]
        for pt in (pt_a, pt_b):
            pickings |= self.PickingObj.create(
                {
                    "picking_type_id": pt.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": product.id,
                                "product_uom_qty": 1,
                                "product_uom": product.uom_id.id,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.customer_location.id,
                            },
                        ),
                    ],
                },
            )
        # Before the fix this raised "Expected singleton: stock.picking.type(...)".
        actions = pickings._get_autoprint_report_actions()
        self.assertEqual(
            len(actions),
            1,
            "one product-label action per distinct format (crash/duplicate regression)",
        )

    def test_autoprint_lot_labels_multi_type_same_format(self):
        """Two picking types sharing a lot-label format must emit a single lot-label
        action, not one per picking type (duplicate-action regression).
        """
        self.env.user.group_ids = [
            (4, self.env.ref("stock.group_production_lot").id),
        ]
        pt_a, pt_b = self._two_types_sharing(
            auto_print_lot_labels=True,
            lot_label_format="zpl_lots",
        )
        tracked = self.ProductObj.create(
            {"name": "TrackedLot", "is_storable": True, "tracking": "lot"},
        )
        lot = self.env["stock.lot"].create(
            {"name": "LOT-A", "product_id": tracked.id},
        )
        pickings = self.env["stock.picking"]
        for pt in (pt_a, pt_b):
            picking = self.PickingObj.create(
                {
                    "picking_type_id": pt.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": tracked.id,
                                "product_uom_qty": 1,
                                "product_uom": tracked.uom_id.id,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.customer_location.id,
                            },
                        ),
                    ],
                },
            )
            self.env["stock.move.line"].create(
                {
                    "picking_id": picking.id,
                    "move_id": picking.move_ids[0].id,
                    "product_id": tracked.id,
                    "lot_id": lot.id,
                    "quantity": 1,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                },
            )
            pickings |= picking
        actions = pickings._get_autoprint_report_actions()
        self.assertEqual(
            len(actions),
            1,
            "one lot-label action per distinct format (duplicate-action regression)",
        )

    def test_get_show_allocation_matches_per_picking_field(self):
        """`_get_show_allocation` (batch helper) must equal the OR of the per-picking
        `show_allocation` field over the same set — they share `_get_show_allocation_map`
        so a batch can never disagree with the pickings it contains.
        """
        self.env.user.group_ids = [
            (4, self.env.ref("stock.group_reception_report").id),
        ]
        product = self.ProductObj.create({"name": "RecvY", "is_storable": True})
        receipts = self.env["stock.picking"]
        for _i in range(2):
            receipt = self.PickingObj.create(
                {
                    "picking_type_id": self.picking_type_in.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                },
            )
            self.MoveObj.create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 5,
                    "product_uom": product.uom_id.id,
                    "picking_id": receipt.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": self.stock_location.id,
                },
            )
            receipt.action_confirm()
            receipts |= receipt
        receipts.invalidate_recordset(["show_allocation"])
        self.assertEqual(
            bool(receipts._get_show_allocation(self.picking_type_in)),
            any(receipts.mapped("show_allocation")),
        )

    def test_sanity_check_flags_zero_quantity_picking(self):
        """The `float_is_zero` -> `move.product_uom.is_zero` swap in `_sanity_check`
        must still detect a picking whose moves have no done quantity.
        """
        product = self.ProductObj.create({"name": "ZeroQty", "is_storable": True})
        picking = self._new_picking(self.picking_type_out)
        self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "product_uom": product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        picking.action_confirm()  # no stock -> stays confirmed, quantity 0
        with self.assertRaises(UserError):
            picking.button_validate()

    def test_split_backorder_pickings_partitions_by_type_and_context(self):
        """`_split_backorder_pickings` (extracted from `button_validate`) sends
        `create_backorder == "never"` types and `picking_ids_not_to_backorder` records
        to the no-backorder side, everything else to the backorder side.
        """
        Seq = self.env["ir.sequence"]
        pt_never = self.picking_type_out.copy(
            {
                "name": "No BO",
                "create_backorder": "never",
                "sequence_id": Seq.create(
                    {"name": "NB", "prefix": "NB/", "padding": 5}
                ).id,
            },
        )
        pt_ask = self.picking_type_out.copy(
            {
                "name": "Ask BO",
                "create_backorder": "ask",
                "sequence_id": Seq.create(
                    {"name": "AB", "prefix": "AB/", "padding": 5}
                ).id,
            },
        )
        never_pick = self._new_picking(pt_never)
        ask_pick = self._new_picking(pt_ask)
        pickings = never_pick | ask_pick

        to_bo, not_to_bo = pickings._split_backorder_pickings()
        self.assertEqual(not_to_bo, never_pick)
        self.assertEqual(to_bo, ask_pick)

        # The context override moves an otherwise-backorderable picking to the no-BO side.
        to_bo, not_to_bo = pickings.with_context(
            picking_ids_not_to_backorder=ask_pick.ids,
        )._split_backorder_pickings()
        self.assertEqual(not_to_bo, never_pick | ask_pick)
        self.assertFalse(to_bo)

    def _internal_move(self, picking, dest_location, demand=10):
        return self.MoveObj.create(
            {
                "product_id": self.product_2.id,
                "product_uom_qty": demand,
                "product_uom": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": dest_location.id,
            },
        )

    def test_pre_action_done_hook_autopicks_scrap_destination_move(self):
        """A picking whose move goes to a scrap (inventory) location must have that move
        auto-picked, so a scrap transfer can validate to ``done``. This pins the
        `_pre_action_done_hook` behavior that `test_move.test_scrap_10` depends on: a
        scrap move's quantity counts as demand and the move is auto-picked. Do NOT
        "fix" this into excluding inventory moves — it breaks scrap validation.
        """
        picking = self._new_picking(self.picking_type_int)
        scrap_move = self._internal_move(picking, self.scrap_location, demand=3)
        picking.action_confirm()
        scrap_move.quantity = 3
        scrap_move.picked = False

        picking.with_context(skip_backorder=True)._pre_action_done_hook()

        self.assertTrue(
            scrap_move.picked,
            "a scrap (inventory-destination) move must be auto-picked so the transfer "
            "can be validated",
        )

    def test_pre_action_done_hook_scrap_pick_does_not_suppress_real_moves(self):
        """The `has_pick` detection deliberately excludes inventory moves: an
        already-picked scrap move must NOT prevent auto-picking the real moves. Pins the
        intentional asymmetry (scrap counts for demand + gets picked, but doesn't count
        as "the user already picked something").
        """
        picking = self._new_picking(self.picking_type_int)
        real_move = self._internal_move(picking, self.stock_location)
        scrap_move = self._internal_move(picking, self.scrap_location, demand=3)
        picking.action_confirm()
        real_move.quantity = 5
        scrap_move.quantity = 3
        real_move.picked = False
        scrap_move.picked = True  # a scrap move already picked

        picking.with_context(skip_backorder=True)._pre_action_done_hook()

        self.assertTrue(
            real_move.picked,
            "a pre-picked scrap move must not suppress auto-picking the real moves",
        )

    def test_pre_action_done_hook_autopicks_real_moves(self):
        """Positive control: a real move carrying quantity with nothing picked yet is
        auto-picked by the hook (unchanged behavior).
        """
        picking = self._new_picking(self.picking_type_int)
        move = self._internal_move(picking, self.stock_location)
        picking.action_confirm()
        move.quantity = 5
        move.picked = False

        picking.with_context(skip_backorder=True)._pre_action_done_hook()

        self.assertTrue(move.picked, "real move with quantity must be auto-picked")

    def test_write_picking_type_batch_adopts_locations(self):
        """Changing `picking_type_id` on several pickings at once adopts each new type's
        default locations (the batched, grouped-by-resolved-pair write path).
        """
        p1 = self._new_picking(self.picking_type_in)
        p2 = self._new_picking(self.picking_type_in)
        (p1 | p2).write({"picking_type_id": self.picking_type_out.id})
        for picking in (p1, p2):
            self.assertEqual(
                picking.location_id,
                self.picking_type_out.default_location_src_id,
            )
            self.assertEqual(
                picking.location_dest_id,
                self.picking_type_out.default_location_dest_id,
            )

    def test_measure_total_by_picking_shared_helper(self):
        """`weight_bulk` and `shipping_volume` are driven by the same
        `_measure_total_by_picking` read-group helper, and both must recompute on a
        quantity change *via `@api.depends`* — no manual invalidation. This guards the
        decorator staying attached to each compute (a helper inserted between the
        decorator and `_compute_bulk_weight` would silently swallow it).
        """
        self.product_2.weight = 4.0
        self.product_2.volume = 2.0
        picking = self._new_picking(self.picking_type_out)
        move = self.MoveObj.create(
            {
                "product_id": self.product_2.id,
                "product_uom_qty": 3,
                "product_uom": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move_line = self.env["stock.move.line"].create(
            {
                "product_id": self.product_2.id,
                "product_uom_id": self.product_2.uom_id.id,
                "picking_id": picking.id,
                "move_id": move.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "quantity": 3.0,
            },
        )
        # Prime the caches, then mutate quantity and re-read: correct values must come
        # from `@api.depends` invalidation alone.
        self.assertEqual(picking.shipping_volume, 6.0, "3 units * 2.0 volume/unit")
        self.assertEqual(picking.weight_bulk, 12.0, "3 units * 4.0 kg/unit")
        move_line.quantity = 5.0
        self.assertEqual(
            picking.shipping_volume, 10.0, "shipping_volume must follow the quantity"
        )
        self.assertEqual(
            picking.weight_bulk, 20.0, "weight_bulk must follow the quantity"
        )

    def test_search_products_availability_state_matches_compute(self):
        """`products_availability_state` is False for incoming (and non-outgoing/
        internal) pickings — the compute only assigns a real state to outgoing/internal
        ones. The search must agree with the field: an assigned *incoming* picking, even
        with a fully reserved move, must NOT match available/expected/late and MUST
        match False. Regression for the search scanning every non-terminal picking
        without the picking-type restriction (which leaked receipts into "Available"
        and hid them from a "False" filter).
        """
        product = self.env["product.product"].create(
            {"name": "Availability probe", "is_storable": True},
        )
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.picking_type_out.default_location_src_id,
            100,
        )

        def make(picking_type):
            picking = self._new_picking(picking_type)
            self.MoveObj.create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 5,
                    "product_uom": product.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": picking_type.default_location_src_id.id,
                    "location_dest_id": picking_type.default_location_dest_id.id,
                },
            )
            picking.action_confirm()
            picking.action_assign()
            return picking

        incoming = make(self.picking_type_in)
        outgoing = make(self.picking_type_out)
        # Precondition: the field itself distinguishes them.
        self.assertFalse(incoming.products_availability_state)
        self.assertEqual(outgoing.products_availability_state, "available")

        scope = incoming | outgoing
        available = self.PickingObj.search(
            [
                ("id", "in", scope.ids),
                (
                    "products_availability_state",
                    "in",
                    ["available", "expected", "late"],
                ),
            ],
        )
        self.assertEqual(
            available,
            outgoing,
            "an incoming picking must not leak into the availability search",
        )
        as_false = self.PickingObj.search(
            [
                ("id", "in", scope.ids),
                ("products_availability_state", "in", [False]),
            ],
        )
        self.assertEqual(
            as_false,
            incoming,
            "an incoming picking must be found by the False availability search",
        )
