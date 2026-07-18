"""Regression tests for the review-driven correctness fixes.

Each test here was written to FAIL against the pre-fix code (verified on a
disposable DB) and pass after the fix, so they double as mutation guards for the
specific defects they cover. Grouped in one file for greppability.
"""

import datetime

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestReviewCompoundingFixes(TestStockCommon):
    def test_reserved_release_not_dropped_in_multirow_group(self):
        """stock_quant: releasing more than the strategy-first row's own reserved
        quantity must not be clamped away, or a phantom reservation is stranded on
        the sibling row (H1)."""
        Quant = self.env["stock.quant"]
        loc = self.env["stock.location"].create(
            {"name": "H1_loc", "usage": "internal", "location_id": self.stock_location.id}
        )
        prod = self.env["product.product"].create(
            {"name": "H1_prod", "type": "consu", "is_storable": True}
        )
        t = datetime.datetime(2026, 1, 1)
        # The exact post-create-branch-fallback state: the stock-holding row is
        # unreserved (gathered first), a reservation-only sibling holds the 5.
        q1 = Quant.create(
            {"product_id": prod.id, "location_id": loc.id, "quantity": 5.0,
             "reserved_quantity": 0.0, "in_date": t}
        )
        q2 = Quant.create(
            {"product_id": prod.id, "location_id": loc.id, "quantity": 0.0,
             "reserved_quantity": 5.0, "in_date": t}
        )
        self.assertEqual(q1.reserved_quantity + q2.reserved_quantity, 5.0)

        Quant._update_reserved_quantity(prod, loc, -5.0)
        self.env.flush_all()

        total = sum(
            Quant.search([("product_id", "=", prod.id), ("location_id", "=", loc.id)])
            .mapped("reserved_quantity")
        )
        self.assertEqual(total, 0.0, "the release of 5 must bring group reserved to 0")

    def test_deadline_date_counts_two_step_receipt(self):
        """stock_orderpoint: a receipt routed through a 2-step reception (dest=Input,
        final=Stock) must be visible to the deadline walk, exactly like a 1-step
        receipt straight to Stock (H2)."""
        company = self.env.company
        company.horizon_days = 60
        wh = self.warehouse_1
        wh.reception_steps = "two_steps"
        self.env.flush_all()
        stock_loc = wh.lot_stock_id
        input_loc = wh.wh_input_stock_loc_id
        today = fields.Date.today()

        def deadline_for(in_dest, in_final):
            prod = self.env["product.product"].create(
                {"name": "H2_prod", "type": "consu", "is_storable": True}
            )
            self.env["stock.quant"].create(
                {"product_id": prod.id, "location_id": stock_loc.id, "quantity": 10.0}
            )
            op = self.env["stock.warehouse.orderpoint"].create(
                {"product_id": prod.id, "location_id": stock_loc.id,
                 "warehouse_id": wh.id, "product_min_qty": 10.0, "product_max_qty": 50.0}
            )
            base = datetime.datetime.combine(today, datetime.time(12))
            m_in = self.env["stock.move"].create(
                {"product_id": prod.id, "product_uom_qty": 20.0,
                 "product_uom_id": prod.uom_id.id, "location_id": self.supplier_location.id,
                 "location_dest_id": in_dest.id, "location_final_id": in_final.id,
                 "picking_type_id": wh.in_type_id.id,
                 "date": base + datetime.timedelta(days=10)}
            )
            m_out = self.env["stock.move"].create(
                {"product_id": prod.id, "product_uom_qty": 20.0,
                 "product_uom_id": prod.uom_id.id, "location_id": stock_loc.id,
                 "location_dest_id": self.customer_location.id,
                 "location_final_id": self.customer_location.id,
                 "picking_type_id": wh.out_type_id.id,
                 "date": base + datetime.timedelta(days=20)}
            )
            (m_in | m_out)._action_confirm()
            self.env.flush_all()
            op.invalidate_recordset(["deadline_date"])
            return op.deadline_date

        control = deadline_for(stock_loc, stock_loc)   # 1-step
        two_step = deadline_for(input_loc, stock_loc)  # 2-step
        self.assertFalse(control, "1-step receipt should cover the shortage")
        self.assertEqual(
            two_step, control,
            "2-step receipt covers identically; deadline must match the 1-step case",
        )

    def test_button_validate_skips_cancelled_picking(self):
        """stock_picking: validating a batch that includes a cancelled picking must
        not misclassify it as a zero-quantity transfer (M2)."""
        prod = self.env["product.product"].create(
            {"name": "M2_prod", "type": "consu", "is_storable": True}
        )
        pick = self.env["stock.picking"].create(
            {"picking_type_id": self.warehouse_1.out_type_id.id,
             "location_id": self.stock_location.id,
             "location_dest_id": self.customer_location.id}
        )
        self.env["stock.move"].create(
            {"product_id": prod.id, "product_uom_qty": 5.0, "product_uom_id": prod.uom_id.id,
             "picking_id": pick.id, "location_id": pick.location_id.id,
             "location_dest_id": pick.location_dest_id.id}
        )
        pick.action_confirm()
        pick.action_cancel()
        self.assertEqual(pick.state, "cancel")
        # Must not raise the zero-quantity error; a no-op is fine.
        pick.button_validate()

    def test_traceability_get_lines_rejects_foreign_model(self):
        """stock_traceability: the JSON-RPC entry must not dereference an arbitrary
        client-supplied model (M4)."""
        report = self.env["stock.traceability.report"]
        partner = self.env.ref("base.partner_admin")
        # Pre-fix this raised AttributeError from res.partner.move_id; post-fix it is
        # refused cleanly.
        res = report.get_lines(line_id=1, model_name="res.partner", model_id=partner.id)
        self.assertEqual(res, [])
        self.assertIn("stock.move.line", report._get_line_allowed_models())
        self.assertNotIn("res.partner", report._get_line_allowed_models())

    def test_qty_available_not_aliased_across_search_locations(self):
        """product_product: qty_available must not alias across two search_location
        scopes read in one transaction (M6)."""
        Loc = self.env["stock.location"]
        la = Loc.create({"name": "M6_A", "usage": "internal", "location_id": self.stock_location.id})
        lb = Loc.create({"name": "M6_B", "usage": "internal", "location_id": self.stock_location.id})
        prod = self.env["product.product"].create(
            {"name": "M6_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"].create(
            [{"product_id": prod.id, "location_id": la.id, "quantity": 3.0},
             {"product_id": prod.id, "location_id": lb.id, "quantity": 7.0}]
        )
        self.env.flush_all()
        qa = prod.with_context(search_location=la.id).qty_available
        qb = prod.with_context(search_location=lb.id).qty_available
        self.assertEqual(qa, 3.0)
        self.assertEqual(qb, 7.0, "second read must reflect location B, not A's cache")

    def test_scrap_cannot_be_validated_twice(self):
        """stock_scrap: re-validating a done scrap must be refused, not silently
        duplicate the inventory loss (M7)."""
        prod = self.env["product.product"].create(
            {"name": "M7_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, self.stock_location, 10.0
        )
        scrap = self.env["stock.scrap"].create(
            {"product_id": prod.id, "product_uom_id": prod.uom_id.id, "scrap_qty": 3.0,
             "location_id": self.stock_location.id}
        )
        scrap.do_scrap()
        self.assertEqual(scrap.state, "done")
        first_name = scrap.name
        with self.assertRaises(UserError):
            scrap.do_scrap()
        # The reference must not have been regenerated by the refused second pass.
        self.assertEqual(scrap.name, first_name)

    def test_lot_batch_relocate_each_single_location(self):
        """stock_lot: batch-writing location_id on several lots, each in its own single
        location, must not raise the single-location error (M9)."""
        prod = self.env["product.product"].create(
            {"name": "M9_prod", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        loc_a, loc_b, loc_c = self.env["stock.location"].create(
            [{"name": f"M9_{n}", "usage": "internal", "location_id": self.stock_location.id}
             for n in ("A", "B", "C")]
        )
        lot1, lot2 = self.env["stock.lot"].create(
            [{"name": "M9-L1", "product_id": prod.id},
             {"name": "M9-L2", "product_id": prod.id}]
        )
        # lot1 sits only in A, lot2 sits only in B (each single-location).
        self.env["stock.quant"]._update_available_quantity(prod, loc_a, 5.0, lot_id=lot1)
        self.env["stock.quant"]._update_available_quantity(prod, loc_b, 5.0, lot_id=lot2)
        self.env.flush_all()
        # Batch write to a common destination: must relocate both, not raise.
        (lot1 | lot2).location_id = loc_c
        self.env.flush_all()
        self.assertEqual(lot1.location_id, loc_c)
        self.assertEqual(lot2.location_id, loc_c)

    def test_serial_prefix_does_not_hijack_foreign_sequence(self):
        """product_template: a serial prefix matching a foreign document sequence must
        not repoint lot generation at that sequence (M10)."""
        foreign = self.env["ir.sequence"].create(
            {"name": "Foreign", "code": "sale.order", "prefix": "ZZHIJACK/", "padding": 5}
        )
        tmpl = self.env["product.template"].create(
            {"name": "M10_prod", "is_storable": True, "tracking": "serial"}
        )
        tmpl.serial_prefix_format = "ZZHIJACK/"
        self.assertNotEqual(
            tmpl.lot_sequence_id, foreign, "must not hijack the sale.order sequence"
        )
        self.assertEqual(tmpl.lot_sequence_id.code, "stock.lot.serial")

    def test_contained_quant_search_negative_operator(self):
        """stock_package: a package that DOES contain a quant must not match a
        'not in [that quant]' search (M11)."""
        prod = self.env["product.product"].create(
            {"name": "M11_prod", "type": "consu", "is_storable": True}
        )
        pkg = self.env["stock.package"].create({"name": "M11-PKG"})
        self.env["stock.quant"]._update_available_quantity(
            prod, self.stock_location, 4.0, package_id=pkg
        )
        self.env.flush_all()
        quant = pkg.quant_ids
        self.assertTrue(quant)
        # Positive: the package contains the quant.
        self.assertIn(
            pkg, self.env["stock.package"].search([("contained_quant_ids", "in", quant.ids)])
        )
        # Negative: it must therefore NOT match "not in [that quant]".
        self.assertNotIn(
            pkg,
            self.env["stock.package"].search([("contained_quant_ids", "not in", quant.ids)]),
        )

    def test_reception_assign_rejects_done_out(self):
        """report_stock_reception: action_assign must refuse a non-assignable (done)
        out move instead of mutating it (M3)."""
        report = self.env["report.stock.report_reception"]
        prod = self.env["product.product"].create(
            {"name": "M3_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(prod, self.stock_location, 10.0)
        # A validated (done) delivery: not an assignable candidate.
        out_pick = self.env["stock.picking"].create(
            {"picking_type_id": self.warehouse_1.out_type_id.id,
             "location_id": self.stock_location.id,
             "location_dest_id": self.customer_location.id}
        )
        out_move = self.env["stock.move"].create(
            {"product_id": prod.id, "product_uom_qty": 5.0, "product_uom_id": prod.uom_id.id,
             "picking_id": out_pick.id, "location_id": self.stock_location.id,
             "location_dest_id": self.customer_location.id}
        )
        out_pick.action_confirm()
        out_move.quantity = 5.0
        out_move.picked = True
        out_pick.button_validate()
        self.assertEqual(out_move.state, "done")
        in_move = self.env["stock.move"].create(
            {"product_id": prod.id, "product_uom_qty": 5.0, "product_uom_id": prod.uom_id.id,
             "location_id": self.supplier_location.id,
             "location_dest_id": self.stock_location.id,
             "picking_type_id": self.warehouse_1.in_type_id.id}
        )
        in_move._action_confirm()
        with self.assertRaises(UserError):
            report.action_assign([out_move.id], [5.0], [[in_move.id]])

    def test_date_done_does_not_redate_scrap_moves(self):
        """stock_picking.write: setting date_done must not re-date a done scrap
        (inventory-dest) move on the picking (L9)."""
        prod = self.env["product.product"].create(
            {"name": "L9_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(prod, self.stock_location, 10.0)
        pick = self.env["stock.picking"].create(
            {"picking_type_id": self.warehouse_1.out_type_id.id,
             "location_id": self.stock_location.id,
             "location_dest_id": self.customer_location.id}
        )
        normal_move = self.env["stock.move"].create(
            {"product_id": prod.id, "product_uom_qty": 5.0, "product_uom_id": prod.uom_id.id,
             "picking_id": pick.id, "location_id": self.stock_location.id,
             "location_dest_id": self.customer_location.id}
        )
        pick.action_confirm()
        normal_move.quantity = 5.0
        normal_move.picked = True
        pick.button_validate()
        self.assertEqual(pick.state, "done")
        # A scrap-like done move on the same picking, dated in the past.
        old_date = datetime.datetime(2026, 1, 1, 8, 0, 0)
        scrap_move = self.env["stock.move"].create(
            {"product_id": prod.id, "product_uom_qty": 1.0, "product_uom_id": prod.uom_id.id,
             "picking_id": pick.id, "location_id": self.stock_location.id,
             "location_dest_id": self.scrap_location.id, "state": "done", "date": old_date}
        )
        self.assertEqual(scrap_move.location_dest_usage, "inventory")
        pick.write({"date_done": datetime.datetime(2026, 5, 5, 12, 0, 0)})
        self.assertEqual(
            scrap_move.date, old_date, "the done scrap move must keep its own date"
        )

    def test_lot_filtered_quant_cache_not_authoritative_for_unseeded_lot(self):
        """stock_quant._QuantsCache: a lot-filtered cache must not claim coverage for a
        lot it never scanned; the gather must fall back to search and find real stock
        (D7)."""
        Quant = self.env["stock.quant"]
        prod = self.env["product.product"].create(
            {"name": "D7_prod", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        lot_a, lot_b = self.env["stock.lot"].create(
            [{"name": "D7-A", "product_id": prod.id},
             {"name": "D7-B", "product_id": prod.id}]
        )
        Quant._update_available_quantity(prod, self.stock_location, 5.0, lot_id=lot_a)
        Quant._update_available_quantity(prod, self.stock_location, 7.0, lot_id=lot_b)
        self.env.flush_all()
        # Cache seeded for lot A only (as _action_done seeds its consumed lots).
        cache = Quant._get_quants_by_products_locations(
            prod, self.stock_location, lot_scope=lot_a
        )
        self.assertTrue(cache.covers(prod, self.stock_location, lot_a))
        self.assertFalse(
            cache.covers(prod, self.stock_location, lot_b),
            "an unseeded lot must not be reported as covered",
        )
        # A gather for lot B through the cache must search and find the real 7.0.
        res = Quant.with_context(quants_cache=cache)._gather(
            prod, self.stock_location, lot_id=lot_b, strict=True
        )
        self.assertEqual(sum(res.mapped("quantity")), 7.0)
