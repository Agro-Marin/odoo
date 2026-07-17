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

        # --- create path ---
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

        # --- write path ---
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
                    # no default_tracking
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
        # single non-float field
        key_fn = Move._merge_move_itemgetter(["product_id"])
        key = key_fn(move)
        self.assertIsInstance(key, tuple)
        self.assertEqual(key, (move.product_id,))

        # single non-float field mixed with a float field
        key_fn2 = Move._merge_move_itemgetter(["product_id", "price_unit"])
        key2 = key_fn2(move)
        self.assertIsInstance(key2, tuple)
        self.assertEqual(len(key2), 2)

        # float-only field list (non-float set empty)
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
        # An internal move is consuming; with 10 in stock the whole demand of 4
        # is forecast as available (the branch removal / prefetch change must
        # not degrade it to the 0.0 fallback).
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
        # Parent A first (its done line makes lot_2 the first reservation key),
        # parent B second.
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
        # Pre-existing partial reservation on lot_1: the assign below must
        # *increase* this line in place (update path) for the lot_1 key while
        # *creating* a line (create path) for the lot_2 key.
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
                # deliberately no default_company_id
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
