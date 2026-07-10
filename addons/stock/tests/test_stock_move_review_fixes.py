from odoo import Command
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
            storable, self.stock_location, 10,
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
        # An internal move is consuming; it must produce a numeric forecast
        # without raising (the branch removal / prefetch change must be safe).
        self.assertIsInstance(move.forecast_availability, float)
