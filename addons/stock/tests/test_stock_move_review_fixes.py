from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestStockMoveReviewFixes(TestStockCommon):
    """Regression tests for the stock.move review fixes.

    Each test pins a bug that was confirmed against a live database before the
    fix, so a re-introduction fails here loudly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type_out.write(
            {"use_existing_lots": True, "use_create_lots": True},
        )
        cls.lot_product = cls.env["product.product"].create(
            {
                "name": "Review Lot Product",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            },
        )

    def _out_picking(self):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )

    def test_create_keeps_lot_ids_like_write(self):
        """`quantity` + `lot_ids` in the same payload must behave identically on
        create and on write. Previously create silently dropped `lot_ids`
        (observable when the lot has no stock to re-derive it from), while write
        kept them.
        """
        lot = self.env["stock.lot"].create(
            {"name": "REVIEW-NOSTOCK", "product_id": self.lot_product.id},
        )  # deliberately no quant

        picking_c = self._out_picking()
        move_c = self.env["stock.move"].create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 3,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking_c.id,
                "quantity": 3.0,
                "lot_ids": [Command.set(lot.ids)],
            },
        )

        picking_w = self._out_picking()
        move_w = self.env["stock.move"].create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 3,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking_w.id,
            },
        )
        picking_w.action_confirm()
        move_w.write({"quantity": 3.0, "lot_ids": [Command.set(lot.ids)]})

        self.assertEqual(
            move_c.lot_ids,
            lot,
            "create dropped lot_ids when quantity was also supplied",
        )
        self.assertEqual(move_w.lot_ids, lot)
        self.assertEqual(
            move_c.lot_ids,
            move_w.lot_ids,
            "create and write disagree on quantity+lot_ids handling",
        )

    def test_create_drops_lot_ids_when_explicit_move_lines(self):
        """Explicit `move_line_ids` still win over the derived `lot_ids`."""
        lot = self.env["stock.lot"].create(
            {"name": "REVIEW-EXPLICIT", "product_id": self.lot_product.id},
        )
        picking = self._out_picking()
        move = self.env["stock.move"].create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": self.lot_product.id,
                            "product_uom_id": self.lot_product.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "quantity": 1,
                        },
                    ),
                ],
                "lot_ids": [Command.set(lot.ids)],
            },
        )
        self.assertFalse(
            move.lot_ids,
            "explicit move_line_ids should take precedence over lot_ids on create",
        )

    def test_generate_lot_line_vals_missing_tracking_raises_usererror(self):
        """Missing `default_tracking` must raise a clean UserError, not a raw
        KeyError -> Fault 500, on this RPC-reachable method.
        """
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                {
                    "default_product_id": self.lot_product.id,
                    "default_location_dest_id": self.customer_location.id,
                },
                "generate",
                "SN001",
                2,
                "",
            )

    def test_generate_lot_line_vals_invalid_mode_raises_usererror(self):
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                {
                    "default_product_id": self.lot_product.id,
                    "default_tracking": "serial",
                    "default_location_dest_id": self.customer_location.id,
                },
                "not-a-mode",
                "SN001",
                2,
                "",
            )

    def test_merge_move_itemgetter_single_non_float_field(self):
        """`_merge_move_itemgetter` must return a tuple-producing key even when
        only one non-float distinct field remains (itemgetter(*names) would
        return a scalar and break the float-tuple concatenation).
        """
        Move = self.env["stock.move"]
        picking = self._out_picking()
        move = Move.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
            },
        )
        key_fn = Move._merge_move_itemgetter(["product_id"])
        key = key_fn(move)
        self.assertIsInstance(key, tuple)
        self.assertEqual(key, (move.product_id,))

        key_fn2 = Move._merge_move_itemgetter(["product_id", "price_unit"])
        key2 = key_fn2(move)
        self.assertIsInstance(key2, tuple)
        self.assertEqual(len(key2), 2)

        key_fn3 = Move._merge_move_itemgetter(["price_unit"])
        self.assertIsInstance(key_fn3(move), tuple)

    def test_internal_move_forecast_still_computed(self):
        """The removed dead `code == "internal"` forecast branch must not have
        broken internal-move forecasting (internal moves are `_is_consuming()`).
        """
        storable = self.env["product.product"].create(
            {"name": "Review Storable", "type": "consu", "is_storable": True},
        )
        self.env["stock.quant"]._update_available_quantity(
            storable,
            self.stock_location,
            10,
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_int.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.shelf_1.id,
            },
        )
        move = self.env["stock.move"].create(
            {
                "product_id": storable.id,
                "product_uom_qty": 4,
                "product_uom_id": storable.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.shelf_1.id,
                "picking_id": picking.id,
            },
        )
        picking.action_confirm()
        move.invalidate_recordset(["forecast_availability"])
        self.assertAlmostEqual(move.forecast_availability, 4.0)

    def _done_receipt(self, product, qty, lot=None):
        """Create and validate a bare receipt move of `qty` (optionally lotted)."""
        move = self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        move._action_confirm()
        ml_vals = {
            "move_id": move.id,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "location_id": self.supplier_location.id,
            "location_dest_id": self.stock_location.id,
            "quantity": qty,
            "picked": True,
        }
        if lot:
            ml_vals["lot_id"] = lot.id
        self.env["stock.move.line"].create(ml_vals)
        move._action_done()
        self.assertEqual(move.state, "done")
        return move

    def test_unlink_confirmed_receipt_refreshes_orderpoint(self):
        """Deleting a confirmed receipt move must refresh the orderpoint's
        `qty_to_order`: the incoming forecast it provided is gone. Previously
        `unlink` skipped the orderpoint recompute entirely (upstream
        9e89558b176) and the stale cached value survived.
        """
        product = self.env["product.product"].create(
            {
                "name": "Review Orderpoint Product",
                "type": "consu",
                "is_storable": True,
            },
        )
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "product_min_qty": 10,
                "product_max_qty": 10,
                "trigger": "manual",
            },
        )
        self.assertAlmostEqual(orderpoint.qty_to_order, 10)

        move = self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 10,
                "product_uom_id": product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        move._action_confirm()
        self.assertAlmostEqual(
            orderpoint.qty_to_order,
            0,
            msg="the confirmed receipt should cover the orderpoint",
        )

        move.unlink()
        self.assertAlmostEqual(
            orderpoint.qty_to_order,
            10,
            msg="deleting the receipt must invalidate the orderpoint forecast",
        )

    def test_chained_assign_update_take_marks_move_assigned(self):
        """A chained move fully reserved through a mix of a new move line and an
        in-place increase of an existing one must end up `assigned`. Previously
        the update-path take never entered the reservation ledger, so the final
        bulk state write demoted the move to `partially_available`.
        """
        lot_1, lot_2 = self.LotObj.create(
            [
                {"name": "REVIEW-CHAIN-1", "product_id": self.lot_product.id},
                {"name": "REVIEW-CHAIN-2", "product_id": self.lot_product.id},
            ],
        )
        parent_a = self._done_receipt(self.lot_product, 3, lot=lot_2)
        parent_b = self._done_receipt(self.lot_product, 7, lot=lot_1)

        move = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 10,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move._action_confirm()
        move.move_orig_ids = [Command.set((parent_a | parent_b).ids)]
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.lot_product.id,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "lot_id": lot_1.id,
                "quantity": 4,
            },
        )

        move._action_assign()

        self.assertAlmostEqual(move.quantity, 10)
        self.assertEqual(
            move.state,
            "assigned",
            "a fully reserved chained move must not be written back as"
            " partially available",
        )

    def test_generate_lot_line_vals_without_company(self):
        """A client context without `default_company_id` must not crash the
        existing-lots branch with a raw KeyError -> Fault 500.
        """
        vals_list = self.env["stock.move"].action_generate_lot_line_vals(
            {
                "default_product_id": self.lot_product.id,
                "default_tracking": "lot",
                "default_location_dest_id": self.customer_location.id,
                "default_quantity": 4,
                "default_picking_type_id": self.picking_type_out.id,
            },
            "generate",
            "REVIEW-NOCOMPANY-01",
            2,
            "",
        )
        self.assertEqual(len(vals_list), 2)
        self.assertTrue(all(vals.get("lot_id") for vals in vals_list))

    def test_inventory_reference_follows_quantity(self):
        """The stored inventory-move reference switches on `quantity`; it must
        be recomputed when the quantity changes (missing dependency).
        """
        product = self.env["product.product"].create(
            {
                "name": "Review Inventory Product",
                "type": "consu",
                "is_storable": True,
            },
        )
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            5,
        )
        move = self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 0,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": product.property_stock_inventory.id,
                "is_inventory": True,
            },
        )
        self.assertIn("Confirmed", move.reference)
        move.quantity = 5
        self.assertIn(
            "Updated",
            move.reference,
            "the inventory reference must follow the quantity",
        )

    def test_key_assign_picking_includes_company(self):
        """Moves of different companies must never share a picking-assignation
        group: `_get_new_picking_values` reads `company_id.id` on the group.
        """
        picking = self._out_picking()
        move = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
            },
        )
        self.assertIn(move.company_id, move._key_assign_picking())

    def test_compute_dependencies_locked(self):
        """Lock the dependency fixes: `quantity_packaging_uom` converts from
        `product_uom_id` (which sale/purchase overrides do not track) and
        `package_ids` switches on `state`/`package_history_id`.
        """
        registry = self.env.registry
        Move = self.env["stock.move"]
        packaging_deps = registry.field_depends[Move._fields["quantity_packaging_uom"]]
        self.assertIn("product_uom_id", packaging_deps)
        package_ids_deps = registry.field_depends[Move._fields["package_ids"]]
        self.assertIn("state", package_ids_deps)
        self.assertIn("move_line_ids.package_history_id", package_ids_deps)

    def test_date_deadline_propagates_through_chain(self):
        """Writing `date_deadline` still propagates through the move chain after
        the explicit-`visited` refactor of `_set_date_deadline`.
        """
        parent = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 2,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        child = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 2,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_orig_ids": [Command.set(parent.ids)],
            },
        )
        (parent | child)._action_confirm()
        deadline = fields.Datetime.now() + timedelta(days=2)
        child.date_deadline = deadline
        self.assertEqual(parent.date_deadline, deadline)

    def test_trigger_assign_reserves_waiting_moves(self):
        """`_trigger_assign` still reserves matching confirmed moves after the
        grouped-domain rewrite (upstream 0ebb89ba47f).
        """
        self.picking_type_out.reservation_method = "at_confirm"
        product = self.env["product.product"].create(
            {
                "name": "Review Trigger Product",
                "type": "consu",
                "is_storable": True,
            },
        )
        picking = self._out_picking()
        out_move = self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
            },
        )
        picking.action_confirm()
        self.assertEqual(out_move.state, "confirmed")

        receipt = self._done_receipt(product, 10)
        receipt._trigger_assign()
        self.assertEqual(out_move.state, "assigned")

    def test_date_deadline_cleared_through_chain(self):
        """Clearing `date_deadline` on a chained move propagates the clear
        instead of raising.

        `fields.Datetime.to_datetime(False)` is None, so the delta arithmetic in
        `_propagate_date_deadline` used to raise
        `TypeError: unsupported operand type(s) for -: 'datetime.datetime' and
        'NoneType'` for any move that both carried a deadline and had a linked
        move to propagate to.
        """
        parent = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 2,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        child = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 2,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_orig_ids": [Command.set(parent.ids)],
            },
        )
        (parent | child)._action_confirm()
        deadline = fields.Datetime.now() + timedelta(days=2)
        child.date_deadline = deadline
        self.assertEqual(parent.date_deadline, deadline)

        child.write({"date_deadline": False})
        self.assertFalse(child.date_deadline)
        self.assertFalse(parent.date_deadline)

    def test_location_dest_follows_location_final(self):
        """Setting Final Location on a move re-derives `location_dest_id`.

        `_compute_location_dest_id` exists to apply "the final location wins when
        it is a child of the destination", but `location_final_id` was missing
        from its dependencies. Reproduced through the picking form, where Final
        Location is an optional column of the embedded move list: the move kept
        `location_dest_id` at the parent location, saved that way, did not
        self-correct at confirm, and passed the wrong destination on to its move
        lines -- while the identical value supplied at create time (precompute)
        produced the correct result.
        """
        registry = self.env.registry
        deps = registry.field_depends[
            self.env["stock.move"]._fields["location_dest_id"]
        ]
        self.assertIn("location_final_id", deps)

        sub = self.env["stock.location"].create(
            {
                "name": "Review Final Sub",
                "location_id": self.stock_location.id,
                "usage": "internal",
            },
        )
        move = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 5,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            },
        )
        self.assertEqual(move.location_dest_id, self.stock_location)

        move.location_final_id = sub
        self.assertEqual(
            move.location_dest_id,
            sub,
            "writing location_final_id must re-derive location_dest_id",
        )

        # The create path must reach the same destination when it likewise has
        # to derive one. An explicit `location_dest_id` is deliberately absent
        # from these values: explicit values beat a compute at create time, which
        # is ORM behaviour rather than anything this rule decides.
        created = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 5,
                "product_uom_id": self.lot_product.uom_id.id,
                "picking_type_id": self.picking_type_in.id,
                "location_final_id": sub.id,
            },
        )
        self.assertEqual(created.picking_type_id, self.picking_type_in)
        self.assertEqual(created.location_dest_id, sub)

    def test_force_qty_honoured_on_chained_move(self):
        """`_action_assign(force_qty=N)` reserves N on a chained move too.

        Only the no-origin (MTS) branch of `_update_reserved_with_stock` read
        `missing_reserved_quantity`; the chained branch recomputed the need from
        `product_qty` and so reserved the move's whole remaining demand whatever
        N was. Four modules call this method with `force_qty`.
        """
        product = self.env["product.product"].create(
            {"name": "Force Qty Product", "type": "consu", "is_storable": True},
        )
        inbound = self._done_receipt(product, 10)
        chained = self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": 10,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_orig_ids": [Command.set(inbound.ids)],
            },
        )
        chained._action_confirm()
        chained.move_line_ids.unlink()
        self.assertTrue(chained.move_orig_ids, "the move must be chained")

        chained._action_assign(force_qty=3)
        self.assertEqual(
            chained.quantity,
            3,
            "force_qty must bound the reservation on the chained branch too",
        )

    def test_write_skips_orderpoint_refresh_when_scope_unchanged(self):
        """Writing a product/location that does not change refreshes the
        orderpoints once, not twice.

        The pre-write refresh exists to catch the orderpoints the move is
        *leaving*; guarding it on key presence alone made an unchanged value pay
        for a second `stock.warehouse.orderpoint` search returning exactly what
        the post-write one finds.
        """
        move = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        self.env.flush_all()

        calls = []
        Move = type(self.env["stock.move"])
        original = Move._get_orderpoints_to_update

        def counting(records):
            calls.append(len(records))
            return original(records)

        self.patch(Move, "_get_orderpoints_to_update", counting)

        move.write({"location_id": self.stock_location.id})
        self.env.flush_all()
        unchanged_calls = len(calls)

        calls.clear()
        move.write({"location_id": self.customer_location.id})
        self.env.flush_all()
        changed_calls = len(calls)

        self.assertEqual(
            unchanged_calls,
            1,
            "an unchanged source location must not search orderpoints twice",
        )
        self.assertEqual(
            changed_calls,
            2,
            "a real location change must refresh both the old and the new scope",
        )

    def test_generated_lot_split_rejects_non_numeric_quantity(self):
        """`_prepare_lot_generation_split` is fed from an RPC client context, so
        a non-numeric quantity must raise UserError, not TypeError -> Fault 500.
        """
        with self.assertRaises(UserError):
            self.env["stock.move"]._prepare_lot_generation_split("not-a-number", 2)
        with self.assertRaises(UserError):
            self.env["stock.move"]._prepare_lot_generation_split(10, None)

    def test_boolean_computes_assign_booleans(self):
        """The Boolean computes assign real booleans, not recordsets.

        `is_quantity_done_editable = move.product_id` and friends relied on the
        ORM coercing a recordset; the field's own value should be its own type.
        """
        move = self.MoveObj.create(
            {
                "product_id": self.lot_product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.lot_product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        for fname in (
            "is_quantity_done_editable",
            "show_lot_actions",
            "has_lines_without_result_package",
        ):
            self.assertIsInstance(
                move[fname],
                bool,
                f"{fname} should hold a bool, not {type(move[fname]).__name__}",
            )

    def test_required_location_fields_stay_precomputed(self):
        """`location_id` / `location_dest_id` are `required=True` *and*
        `precompute=True`: the row cannot be inserted unless they are computed
        before the INSERT.

        The ORM does not enforce that pairing -- adding a dependency on a stored
        compute that is not itself `precompute=True` makes `Field.resolve_depends`
        silently set `precompute = False` behind a `UserWarning`, and the next
        create dies with `NotNullViolation` far from the edit that caused it.
        This pins the invariant so that downgrade fails here instead.
        """
        Move = self.env["stock.move"]
        for fname in ("location_id", "location_dest_id"):
            field = Move._fields[fname]
            self.assertTrue(field.required, f"{fname} is expected to be required")
            self.assertTrue(
                field.precompute,
                f"{fname} lost precompute=True; a required field that is not "
                f"precomputed cannot be inserted. Check whether a dependency was "
                f"added that is a stored compute without precompute=True.",
            )
