from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestMoveReservation(TestStockCommon):
    """Branch-covering characterization of `stock.move._action_assign`.

    Each test pins the reservation outcome (move state + resulting move lines)
    of one distinct code path, so the method can be refactored with confidence:
    MTS full / partial / none, reservation-bypass receipts (plain and serial),
    lot-tracked partial, chained moves fed by a done origin, UoM conversion, and
    the ``force_qty`` path.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_loc = cls.env.ref("stock.stock_location_stock")
        cls.customer_loc = cls.env.ref("stock.stock_location_customers")
        cls.supplier_loc = cls.env.ref("stock.stock_location_suppliers")
        cls.out_type = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        cls.in_type = cls.env["stock.picking.type"].search(
            [("code", "=", "incoming")], limit=1
        )
        cls.internal_type = cls.env["stock.picking.type"].search(
            [("code", "=", "internal")], limit=1
        )

    # -- helpers --------------------------------------------------------------

    def _product(self, tracking="none"):
        return self.env["product.product"].create(
            {"name": "RESV_%s" % tracking, "is_storable": True, "tracking": tracking}
        )

    def _add_stock(self, product, location, qty, lot=None):
        self.env["stock.quant"]._update_available_quantity(
            product, location, qty, lot_id=lot
        )

    def _move(self, product, src, dst, qty, ptype, uom=None):
        vals = {
            "product_id": product.id,
            "product_uom_qty": qty,
            "location_id": src.id,
            "location_dest_id": dst.id,
            "picking_type_id": ptype.id,
        }
        if uom:
            vals["product_uom_id"] = uom.id
        move = self.env["stock.move"].create(vals)
        move._action_confirm()
        return move

    # -- MTS branch (no origin) ----------------------------------------------

    def test_mts_full_availability(self):
        p = self._product()
        self._add_stock(p, self.stock_loc, 10)
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.quantity, 5)

    def test_mts_partial_availability(self):
        p = self._product()
        self._add_stock(p, self.stock_loc, 3)
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        move._action_assign()
        self.assertEqual(move.state, "partially_available")
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.quantity, 3)

    def test_mts_no_stock(self):
        p = self._product()
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        move._action_assign()
        self.assertEqual(move.state, "confirmed")
        self.assertFalse(move.move_line_ids)

    # -- reservation-bypass branch (supplier source) --------------------------

    def test_receipt_bypasses_reservation(self):
        p = self._product()
        move = self._move(p, self.supplier_loc, self.stock_loc, 5, self.in_type)
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.quantity, 5)

    def test_serial_receipt_bypass_creates_one_line_per_unit(self):
        p = self._product(tracking="serial")
        self.in_type.use_create_lots = True
        move = self._move(p, self.supplier_loc, self.stock_loc, 3, self.in_type)
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        self.assertEqual(len(move.move_line_ids), 3)
        self.assertEqual(set(move.move_line_ids.mapped("quantity")), {1.0})

    # -- lot-tracked MTS ------------------------------------------------------

    def test_lot_mts_partial(self):
        p = self._product(tracking="lot")
        lot = self.env["stock.lot"].create({"name": "RESVLOT", "product_id": p.id})
        self._add_stock(p, self.stock_loc, 3, lot=lot)
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        move._action_assign()
        self.assertEqual(move.state, "partially_available")
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.lot_id, lot)
        self.assertEqual(move.move_line_ids.quantity, 3)

    # -- chained move fed by a done origin (MTS-with-orig branch) --------------

    def test_chain_reserves_from_done_origin(self):
        output = self.env["stock.location"].create(
            {
                "name": "RESV_OUT",
                "location_id": self.stock_loc.location_id.id,
                "usage": "internal",
            }
        )
        p = self._product()
        self._add_stock(p, self.stock_loc, 5)
        pick = self._move(p, self.stock_loc, output, 5, self.internal_type)
        out = self._move(p, output, self.customer_loc, 5, self.out_type)
        pick.move_dest_ids = [(4, out.id)]
        pick._action_assign()
        pick.move_line_ids.quantity = 5
        pick.picked = True
        pick._action_done()
        out._action_assign()
        self.assertEqual(out.state, "assigned")
        self.assertEqual(len(out.move_line_ids), 1)
        self.assertEqual(out.move_line_ids.location_id, output)
        self.assertEqual(out.move_line_ids.quantity, 5)

    # -- UoM conversion -------------------------------------------------------

    def test_uom_conversion_dozen_over_unit_stock(self):
        uom_dozen = self.env.ref("uom.product_uom_dozen")
        p = self._product()
        self._add_stock(p, self.stock_loc, 24)  # 2 dozen
        move = self._move(
            p, self.stock_loc, self.customer_loc, 1, self.out_type, uom=uom_dozen
        )
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.quantity, 1)
        self.assertEqual(move.move_line_ids.product_uom_id, uom_dozen)

    # -- force_qty path -------------------------------------------------------

    def test_force_qty_reserves_exact_quantity(self):
        p = self._product()
        self._add_stock(p, self.stock_loc, 10)
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        # Start from a clean, unreserved state so force_qty is the only reservation.
        move._do_unreserve()
        self.assertFalse(move.move_line_ids)
        move._action_assign(force_qty=3)
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.quantity, 3)

    def test_force_qty_without_stock_reserves_nothing(self):
        p = self._product()
        move = self._move(p, self.stock_loc, self.customer_loc, 5, self.out_type)
        move._action_assign(force_qty=3)
        self.assertEqual(move.state, "confirmed")
        self.assertFalse(move.move_line_ids)

    # -- write() reservation re-sync (regression) -----------------------------

    def _reserved(self, product, location):
        quants = self.env["stock.quant"].search(
            [("product_id", "=", product.id), ("location_id", "=", location.id)]
        )
        return sum(quants.mapped("reserved_quantity"))

    def test_write_moves_reservation_with_source_location(self):
        """Changing a reserved line's source location moves the reservation with it."""
        loc_a, loc_b = self.env["stock.location"].create(
            [
                {
                    "name": "RESV_A",
                    "usage": "internal",
                    "location_id": self.stock_loc.location_id.id,
                },
                {
                    "name": "RESV_B",
                    "usage": "internal",
                    "location_id": self.stock_loc.location_id.id,
                },
            ]
        )
        p = self._product()
        self._add_stock(p, loc_a, 10)
        self._add_stock(p, loc_b, 10)
        move = self._move(p, loc_a, self.customer_loc, 5, self.internal_type)
        move._action_assign()
        ml = move.move_line_ids
        self.assertEqual((self._reserved(p, loc_a), self._reserved(p, loc_b)), (5, 0))

        ml.write({"location_id": loc_b.id})
        self.assertEqual((self._reserved(p, loc_a), self._reserved(p, loc_b)), (0, 5))

    def test_write_source_location_and_result_package_together(self):
        """Regression: writing `location_id` and `result_package_id` in the same call
        must still re-sync the source reservation (it used to be silently skipped,
        stranding the reservation at the old location)."""
        loc_a, loc_b = self.env["stock.location"].create(
            [
                {
                    "name": "RESVP_A",
                    "usage": "internal",
                    "location_id": self.stock_loc.location_id.id,
                },
                {
                    "name": "RESVP_B",
                    "usage": "internal",
                    "location_id": self.stock_loc.location_id.id,
                },
            ]
        )
        p = self._product()
        self._add_stock(p, loc_a, 10)
        self._add_stock(p, loc_b, 10)
        move = self._move(p, loc_a, self.customer_loc, 5, self.internal_type)
        move._action_assign()
        ml = move.move_line_ids
        pkg = self.env["stock.package"].create({"name": "RESV_PKG"})

        ml.write({"location_id": loc_b.id, "result_package_id": pkg.id})

        # Reservation follows the line to B; nothing left stranded at A.
        self.assertEqual((self._reserved(p, loc_a), self._reserved(p, loc_b)), (0, 5))
        self.assertEqual(ml.result_package_id, pkg)
        # Unreserving is clean -- no orphaned reservation, full stock freed at both.
        move._do_unreserve()
        self.assertEqual((self._reserved(p, loc_a), self._reserved(p, loc_b)), (0, 0))


@tagged("post_install", "-at_install")
class TestMoveLineFallbackMoveCreation(TestStockCommon):
    """Move lines created directly on a picking get a stock.move; the creation is
    batched. Same-product lines share one new move, distinct products each get one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal_type = cls.env["stock.picking.type"].search(
            [("code", "=", "internal")], limit=1
        )

    def _picking(self):
        pt = self.internal_type
        return self.env["stock.picking"].create(
            {
                "picking_type_id": pt.id,
                "location_id": pt.default_location_src_id.id,
                "location_dest_id": pt.default_location_dest_id.id,
            }
        )

    def _line_vals(self, picking, product):
        return {
            "picking_id": picking.id,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "quantity": 1.0,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
        }

    def test_same_product_lines_share_one_new_move(self):
        picking = self._picking()
        p = self.env["product.product"].create(
            {"name": "FALLBACK_SAME", "is_storable": True}
        )
        lines = self.env["stock.move.line"].create(
            [self._line_vals(picking, p) for _ in range(5)]
        )
        self.assertEqual(len(lines.move_id), 1, "same-product lines share one move")
        self.assertEqual(len(picking.move_ids), 1)

    def test_distinct_product_lines_get_one_move_each_batched(self):
        picking = self._picking()
        products = self.env["product.product"].create(
            [{"name": "FALLBACK_%d" % i, "is_storable": True} for i in range(5)]
        )
        vals = [self._line_vals(picking, p) for p in products]
        orig_create = type(self.env["stock.move"]).create
        calls = []

        def counting(self, vals_list):
            calls.append(len(vals_list) if isinstance(vals_list, list) else 1)
            return orig_create(self, vals_list)

        self.patch(type(self.env["stock.move"]), "create", counting)
        lines = self.env["stock.move.line"].create(vals)

        self.assertEqual(
            len(lines.move_id), 5, "each distinct product gets its own move"
        )
        self.assertEqual(
            calls, [5], "the 5 fallback moves are created in a single batched call"
        )
