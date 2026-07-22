"""Regression tests for the 2026-07 stock audit fixes on the picking / picking
type / package / lot / scrap models (findings #1, #13-#23 and the
picking/lot/package low-severity group)."""

import json
from datetime import timedelta

from psycopg.errors import CheckViolation

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestAuditFixesPicking(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.storable_1, cls.storable_2 = cls.env["product.product"].create(
            [
                {"name": "Audit storable 1", "is_storable": True},
                {"name": "Audit storable 2", "is_storable": True},
            ]
        )

    def _create_confirmed_delivery(self, product, qty, picking_type=None, **vals):
        picking_type = picking_type or self.picking_type_out
        picking = self.PickingObj.create(
            {
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": self.customer_location.id,
                **vals,
            }
        )
        self.MoveObj.create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        picking.action_confirm()
        return picking

    # ------------------------------------------------------------
    # #1 stock.package.type sequence handling on write
    # ------------------------------------------------------------

    def test_package_type_company_only_write_without_sequence(self):
        """A company-only write on a package type without a sequence must not
        try to create a nameless sequence (NotNullViolation), and must move the
        existing sequences of the other types to the new company."""
        no_seq_type = self.env["stock.package.type"].create({"name": "No Seq"})
        seq_type = self.env["stock.package.type"].create(
            {"name": "With Seq", "sequence_code": "PTAUD"}
        )
        self.assertFalse(no_seq_type.sequence_id)
        self.assertTrue(seq_type.sequence_id)

        company = self.env.company
        (no_seq_type | seq_type).write({"company_id": company.id})
        self.assertFalse(
            no_seq_type.sequence_id,
            "A company-only write must not create a sequence for a type "
            "without a sequence code",
        )
        self.assertEqual(seq_type.sequence_id.company_id, company)

        # Providing a code afterwards creates the sequence, on the type company.
        no_seq_type.write({"sequence_code": "PTAUD2"})
        self.assertTrue(no_seq_type.sequence_id)
        self.assertEqual(no_seq_type.sequence_id.prefix, "PTAUD2")
        self.assertEqual(no_seq_type.sequence_id.company_id, company)

    # ------------------------------------------------------------
    # #14 action_split_transfer partition
    # ------------------------------------------------------------

    def test_split_transfer_excludes_cancelled_moves(self):
        picking = self._create_confirmed_delivery(self.product_2, 5)
        move_cancelled = self.MoveObj.create(
            {
                "product_id": self.product_3.id,
                "product_uom_qty": 4,
                "product_uom_id": self.product_3.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        picking.action_confirm()
        move_cancelled._action_cancel()
        self.assertEqual(move_cancelled.state, "cancel")

        move = picking.move_ids - move_cancelled
        move.quantity = 2
        picking.action_split_transfer()

        self.assertEqual(
            move_cancelled.picking_id,
            picking,
            "A cancelled move must not be dragged into the split-off transfer",
        )
        backorder = self.PickingObj.search([("backorder_id", "=", picking.id)])
        self.assertTrue(backorder)
        self.assertNotIn(move_cancelled, backorder.move_ids)
        self.assertEqual(move.picking_id, picking)
        self.assertEqual(move.product_uom_qty, 2)
        self.assertEqual(sum(backorder.move_ids.mapped("product_uom_qty")), 3)

    # ------------------------------------------------------------
    # #15 lot company-change guard
    # ------------------------------------------------------------

    def test_lot_company_change_guard_multi_location(self):
        """The guard must fire even when the lot spans several locations (where
        the computed `location_id` reads False)."""
        product = self.ProductObj.create(
            {"name": "Lot audit product", "is_storable": True, "tracking": "lot"}
        )
        lot = self.LotObj.create(
            {
                "name": "LOT-AUDIT-15",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        self.StockQuantObj._update_available_quantity(
            product, self.shelf_1, 3, lot_id=lot
        )
        self.StockQuantObj._update_available_quantity(
            product, self.shelf_2, 4, lot_id=lot
        )
        self.assertFalse(
            lot.location_id, "Sanity: the computed location is empty on a spread lot"
        )
        company_b = self.env["res.company"].create({"name": "Audit Co B"})
        with self.assertRaises(UserError):
            lot.write({"company_id": company_b.id})

    # ------------------------------------------------------------
    # #16 picking type sequence company
    # ------------------------------------------------------------

    def test_picking_type_sequence_company_on_code_rename(self):
        company_b = self.env["res.company"].create({"name": "Audit Co Seq"})
        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", company_b.id)], limit=1
        )
        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Audit no-WH type",
                "code": "incoming",
                "sequence_code": "AUD16",
                "company_id": company_b.id,
                "warehouse_id": False,
                "default_location_dest_id": warehouse_b.lot_stock_id.id,
            }
        )
        self.assertEqual(picking_type.sequence_id.company_id, company_b)
        # Renaming the code while logged into company A must keep the sequence
        # on the picking type's own company.
        picking_type.write({"sequence_code": "AUD16B"})
        self.assertEqual(picking_type.sequence_id.company_id, company_b)
        self.assertEqual(picking_type.sequence_id.prefix, "AUD16B")

    # ------------------------------------------------------------
    # #17 default locations follow the warehouse
    # ------------------------------------------------------------

    def test_picking_type_default_locations_follow_warehouse(self):
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Audit WH2", "code": "AWH2"}
        )
        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Audit internal",
                "code": "internal",
                "sequence_code": "AUD17",
                "warehouse_id": self.warehouse_1.id,
            }
        )
        self.assertEqual(
            picking_type.default_location_src_id, self.warehouse_1.lot_stock_id
        )
        picking_type.write({"warehouse_id": warehouse_2.id})
        self.assertEqual(
            picking_type.default_location_src_id,
            warehouse_2.lot_stock_id,
            "Reassigning the warehouse must move the stored default source",
        )
        self.assertEqual(
            picking_type.default_location_dest_id, warehouse_2.lot_stock_id
        )
        # An explicitly passed location wins over the re-defaulting.
        picking_type.write(
            {
                "warehouse_id": self.warehouse_1.id,
                "default_location_dest_id": self.shelf_1.id,
            }
        )
        self.assertEqual(picking_type.default_location_src_id, self.stock_location)
        self.assertEqual(picking_type.default_location_dest_id, self.shelf_1)

    def test_picking_type_multistep_locations_survive_step_change(self):
        """Warehouse-managed step locations (e.g. the pack type's source =
        packing zone) must never be clobbered back to `lot_stock_id` by the
        generic default-location logic when the warehouse switches steps —
        regression for the sale_stock MTO-multistep return failure."""
        self.warehouse_1.delivery_steps = "pick_pack_ship"
        pack_type = self.warehouse_1.pack_type_id
        self.assertEqual(
            pack_type.default_location_src_id,
            self.warehouse_1.wh_pack_stock_loc_id,
            "The pack type must pull from the packing zone, not the stock location",
        )
        self.assertEqual(
            self.warehouse_1.pick_type_id.default_location_dest_id,
            self.warehouse_1.wh_pack_stock_loc_id,
        )
        # Flip back and forth: the pack source must survive both writes.
        self.warehouse_1.delivery_steps = "ship_only"
        self.warehouse_1.delivery_steps = "pick_pack_ship"
        self.assertEqual(
            pack_type.default_location_src_id,
            self.warehouse_1.wh_pack_stock_loc_id,
        )

    def test_picking_type_incoming_source_without_warehouse(self):
        """The missing-warehouse redirect must not fire for the branch that
        does not read the warehouse (incoming source = supplier location)."""
        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Audit incoming no WH",
                "code": "incoming",
                "sequence_code": "AUD17B",
                "warehouse_id": False,
                "default_location_dest_id": self.stock_location.id,
            }
        )
        self.assertEqual(
            picking_type.default_location_src_id,
            self.env.ref("stock.stock_location_suppliers"),
        )

    # ------------------------------------------------------------
    # #18 deterministic scrap source location
    # ------------------------------------------------------------

    def test_scrap_default_source_location_deterministic(self):
        company = self.env.company
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)]
        )
        self.assertGreater(
            len(warehouses), 1, "Sanity: needs a multi-warehouse company"
        )
        scrap = self.env["stock.scrap"].create({"product_id": self.product_2.id})
        self.assertEqual(
            scrap.location_id,
            warehouses[0].lot_stock_id,
            "The default scrap source must be the first warehouse in the "
            "model order (sequence, id), not an arbitrary aggregate pick",
        )

    def test_scrap_location_xmlid_designation(self):
        company = self.env.company
        baseline = self.env["stock.scrap"].create({"product_id": self.product_2.id})
        default_loss = self.StockLocationObj.search(
            [("company_id", "=", company.id), ("usage", "=", "inventory")],
            order="id",
            limit=1,
        )
        self.assertEqual(baseline.scrap_location_id, default_loss)

        dedicated = self.StockLocationObj.create(
            {"name": "Audit Casse", "usage": "inventory", "company_id": company.id}
        )
        self.env["ir.model.data"].create(
            {
                "module": "stock",
                "name": f"stock_location_scrap_company_{company.id}",
                "model": "stock.location",
                "res_id": dedicated.id,
            }
        )
        designated = self.env["stock.scrap"].create({"product_id": self.product_2.id})
        self.assertEqual(
            designated.scrap_location_id,
            dedicated,
            "The company-scoped external id must designate the scrap location",
        )

    # ------------------------------------------------------------
    # #23 return pickings keep their locations on type change
    # ------------------------------------------------------------

    def test_return_picking_type_change_keeps_locations(self):
        original = self._create_confirmed_delivery(self.product_2, 1)
        return_picking = self.PickingObj.create(
            {
                "picking_type_id": self.picking_type_in.id,
                "return_id": original.id,
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        other_in_type = self.picking_type_in.copy({"sequence_code": "AUD23"})
        return_picking.write({"picking_type_id": other_in_type.id})
        self.assertEqual(
            return_picking.location_id,
            self.customer_location,
            "A return picking must keep its source on type change",
        )
        self.assertEqual(return_picking.location_dest_id, self.stock_location)

        # Control: a regular picking is still re-defaulted.
        regular = self.PickingObj.create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        regular.write({"picking_type_id": other_in_type.id})
        self.assertEqual(regular.location_id, other_in_type.default_location_src_id)

    # ------------------------------------------------------------
    # #21 _compute_state serves NewId records from the cache
    # ------------------------------------------------------------

    def test_state_of_new_record_follows_cache(self):
        picking = self._create_confirmed_delivery(self.storable_1, 1)
        self.assertEqual(picking.state, "confirmed")
        new_picking = self.PickingObj.new(origin=picking)
        self.assertEqual(new_picking.state, "confirmed")
        # Unsaved edits must be reflected instead of re-reading the committed
        # moves from the database.
        new_picking.move_ids = False
        self.assertEqual(
            new_picking.state,
            "draft",
            "The form state must follow the pending (cache) moves",
        )
        # The database record itself is untouched.
        self.assertEqual(picking.state, "confirmed")

    # ------------------------------------------------------------
    # #22 dashboard graph bucketing
    # ------------------------------------------------------------

    def test_dashboard_graph_sql_bucketing(self):
        picking_type = self.picking_type_out
        now = fields.Datetime.now()
        offsets = [-5, -1, 0, 0, 1, 2, 10]
        for days in offsets:
            picking = self._create_confirmed_delivery(self.product_2, 1)
            picking.date_planned = now + timedelta(days=days)
        open_pickings = self.PickingObj.search(
            [
                ("picking_type_id", "=", picking_type.id),
                ("state", "in", ["assigned", "waiting", "confirmed"]),
                ("date_planned", "!=", False),
            ]
        )
        expected = {
            "before": 0,
            "yesterday": 0,
            "today": 0,
            "day_1": 0,
            "day_2": 0,
            "after": 0,
        }
        for picking in open_pickings:
            expected[self.PickingObj.calculate_date_category(picking.date_planned)] += 1

        picking_type.invalidate_recordset(["kanban_dashboard_graph"])
        [graph_data] = json.loads(picking_type.kanban_dashboard_graph)
        totals = {value["category"]: value["value"] for value in graph_data["values"]}
        self.assertEqual(totals, expected)

    # ------------------------------------------------------------
    # #20 batched shipping weight
    # ------------------------------------------------------------

    def test_shipping_weight_batched_per_picking(self):
        product = self.ProductObj.create(
            {"name": "Heavy audit product", "is_storable": True, "weight": 2.0}
        )
        self.StockQuantObj._update_available_quantity(product, self.stock_location, 20)
        pickings = self.PickingObj
        expected = {}
        for qty in (3, 5):
            picking = self._create_confirmed_delivery(product, qty)
            picking.action_assign()
            package = self.env["stock.package"].create({"name": f"AUDPACK{qty}"})
            picking.move_line_ids.result_package_id = package
            pickings |= picking
            expected[picking.id] = qty * 2.0
        pickings.invalidate_recordset(["shipping_weight"])
        for picking in pickings:
            self.assertAlmostEqual(picking.shipping_weight, expected[picking.id])

    # ------------------------------------------------------------
    # #13 reception report probes per warehouse
    # ------------------------------------------------------------

    def test_reception_report_not_shown_for_other_warehouse_demand(self):
        """Multi-warehouse batch validation: the demand probe must pair each
        warehouse's locations with that warehouse's own received products, not
        cross every warehouse's locations with every picking's products."""
        self.env.user.group_ids += self.env.ref("stock.group_reception_report")
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Audit WH RR", "code": "AWHR"}
        )
        product_wh1, product_wh2 = self.ProductObj.create(
            [
                {"name": "Audit RR product WH1", "is_storable": True},
                {"name": "Audit RR product WH2", "is_storable": True},
            ]
        )
        # Open demand for the WH1-received product... but in warehouse 2.
        self._create_confirmed_delivery(
            product_wh1, 3, picking_type=warehouse_2.out_type_id
        )

        self.picking_type_in.auto_show_reception_report = True
        warehouse_2.in_type_id.auto_show_reception_report = True
        receipts = self.PickingObj
        for picking_type, product in (
            (self.picking_type_in, product_wh1),
            (warehouse_2.in_type_id, product_wh2),
        ):
            receipt = self.PickingObj.create(
                {
                    "picking_type_id": picking_type.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": picking_type.default_location_dest_id.id,
                }
            )
            self.MoveObj.create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 3,
                    "product_uom_id": product.uom_id.id,
                    "picking_id": receipt.id,
                    "location_id": receipt.location_id.id,
                    "location_dest_id": receipt.location_dest_id.id,
                }
            )
            receipts |= receipt
        receipts.action_confirm()
        receipts.move_ids.quantity = 3
        res = receipts.button_validate()
        self.assertIs(
            res,
            True,
            "No warehouse received a product with demand in that same "
            "warehouse, so the reception report must not open (the demand for "
            "the WH1 product lives in WH2, which only received another product)",
        )

    # ------------------------------------------------------------
    # date_done write (low)
    # ------------------------------------------------------------

    def test_date_done_only_redates_done_moves(self):
        picking = self._create_confirmed_delivery(self.product_2, 2)
        cancelled_move = self.MoveObj.create(
            {
                "product_id": self.product_3.id,
                "product_uom_qty": 1,
                "product_uom_id": self.product_3.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        picking.action_confirm()
        cancelled_move._action_cancel()
        done_move = picking.move_ids - cancelled_move
        done_move.quantity = 2
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, "done")

        cancelled_date = cancelled_move.date
        new_date = fields.Datetime.now() - timedelta(days=7)
        picking.write({"date_done": new_date})
        self.assertEqual(done_move.date, new_date)
        self.assertEqual(
            cancelled_move.date,
            cancelled_date,
            "A cancelled move must not be re-dated by a date_done write",
        )

    # ------------------------------------------------------------
    # stock.lot lows
    # ------------------------------------------------------------

    def test_lot_name_default_without_product_sequence(self):
        product = self.ProductObj.create(
            {"name": "Audit lot product", "is_storable": True, "tracking": "lot"}
        )
        # The fork provisions a per-product sequence on tracked products; drop
        # it to simulate legacy/imported products without one.
        product.lot_sequence_id = False
        lot = self.LotObj.create({"product_id": product.id})
        self.assertTrue(
            lot.name,
            "Without a product sequence the name must fall back to the "
            "global lot/serial sequence instead of failing the NOT NULL",
        )

    def test_action_lot_open_quants_requires_single_record(self):
        product = self.ProductObj.create(
            {"name": "Audit lot product 2", "is_storable": True, "tracking": "lot"}
        )
        lots = self.LotObj.create(
            [{"product_id": product.id, "name": name} for name in ("A15", "B15")]
        )
        with self.assertRaises(ValueError):
            lots.action_lot_open_quants()

    # ------------------------------------------------------------
    # stock.package lows
    # ------------------------------------------------------------

    def test_package_owner_includes_children(self):
        owner = self.PartnerObj.create({"name": "Audit Owner"})
        parent = self.env["stock.package"].create({"name": "AUD-PARENT"})
        child = self.env["stock.package"].create(
            {"name": "AUD-CHILD", "parent_package_id": parent.id}
        )
        self.StockQuantObj._update_available_quantity(
            self.storable_1, self.shelf_1, 5, package_id=child, owner_id=owner
        )
        self.assertEqual(child.owner_id, owner)
        self.assertEqual(
            parent.owner_id,
            owner,
            "A container whose goods all belong to one owner through its "
            "children must expose that owner",
        )

    def test_package_info_ambiguous_location(self):
        package = self.env["stock.package"].create({"name": "AUD-AMBIG"})
        self.StockQuantObj._update_available_quantity(
            self.storable_1, self.shelf_1, 5, package_id=package
        )
        self.assertEqual(package.location_id, self.shelf_1)
        self.StockQuantObj._update_available_quantity(
            self.storable_2, self.shelf_2, 5, package_id=package
        )
        self.assertFalse(
            package.location_id,
            "A package whose positive quants span several locations has no "
            "single truthful location",
        )

    def test_package_relocation_moves_negative_quants(self):
        package = self.env["stock.package"].create({"name": "AUD-NEG"})
        self.StockQuantObj._update_available_quantity(
            self.storable_1, self.shelf_1, 10, package_id=package
        )
        self.StockQuantObj._update_available_quantity(
            self.storable_2, self.shelf_1, -3, package_id=package
        )
        package.write({"location_id": self.shelf_2.id})
        self.assertEqual(
            self.StockQuantObj._get_available_quantity(
                self.storable_2, self.shelf_1, package_id=package, allow_negative=True
            ),
            0,
            "The negative quant must not stay behind at the old location",
        )
        self.assertEqual(
            self.StockQuantObj._get_available_quantity(
                self.storable_2, self.shelf_2, package_id=package, allow_negative=True
            ),
            -3,
        )
        self.assertEqual(
            self.StockQuantObj._get_available_quantity(
                self.storable_1, self.shelf_2, package_id=package
            ),
            10,
        )

    def test_search_move_line_ids_accepts_generator(self):
        self.StockQuantObj._update_available_quantity(
            self.storable_1, self.stock_location, 5
        )
        picking = self._create_confirmed_delivery(self.storable_1, 1)
        picking.action_assign()
        package = self.env["stock.package"].create({"name": "AUD-GEN"})
        picking.move_line_ids.result_package_id = package
        line_ids = picking.move_line_ids.ids
        domain = self.env["stock.package"]._search_move_line_ids("in", iter(line_ids))
        matched_ids = domain[0][2]
        self.assertIn(package.id, matched_ids)

    # ------------------------------------------------------------
    # storage category capacity constraint (low)
    # ------------------------------------------------------------

    @mute_logger("odoo.db.cursor")
    def test_storage_capacity_requires_exactly_one_target(self):
        category = self.env["stock.storage.category"].create({"name": "Audit Cat"})
        package_type = self.env["stock.package.type"].create({"name": "Audit PT"})
        Capacity = self.env["stock.storage.category.capacity"]
        # Valid: exactly one of product / package type.
        Capacity.create(
            {
                "storage_category_id": category.id,
                "package_type_id": package_type.id,
                "quantity": 1,
            }
        )
        with (
            self.assertRaises(CheckViolation),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            Capacity.create({"storage_category_id": category.id, "quantity": 1})
            self.env.flush_all()
        with (
            self.assertRaises(CheckViolation),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            Capacity.create(
                {
                    "storage_category_id": category.id,
                    "product_id": self.product_2.id,
                    "package_type_id": package_type.id,
                    "quantity": 1,
                }
            )
            self.env.flush_all()

    # ------------------------------------------------------------
    # putaway rule default qty map (low)
    # ------------------------------------------------------------

    def test_putaway_location_without_qty_map(self):
        rule = self.env["stock.putaway.rule"].create(
            {
                "product_id": self.product_2.id,
                "location_in_id": self.stock_location.id,
                "location_out_id": self.shelf_1.id,
            }
        )
        location = rule._get_putaway_location(self.product_2, quantity=1)
        self.assertEqual(location, self.shelf_1)


@tagged("post_install", "-at_install")
class TestAuditAvailabilitySearch(TestStockCommon):
    """The products_availability_state search must classify a picking exactly
    like `_compute_products_availability` (a short move makes the whole picking
    'late', regardless of its other moves)."""

    def test_availability_search_matches_display_state(self):
        in_stock = self.env["product.product"].create(
            {"name": "Avail In Stock", "is_storable": True},
        )
        shortage = self.env["product.product"].create(
            {"name": "Avail Short", "is_storable": True},
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        self.env["stock.quant"]._update_available_quantity(
            in_stock,
            warehouse.lot_stock_id,
            quantity=10,
        )
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.out_type_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": customers.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_id": product.uom_id.id,
                            "product_uom_qty": 5,
                            "location_id": warehouse.lot_stock_id.id,
                            "location_dest_id": customers.id,
                        },
                    )
                    for product in (in_stock, shortage)
                ],
            },
        )
        picking.action_confirm()
        self.assertEqual(picking.products_availability_state, "late")

        Picking = self.env["stock.picking"]
        late = Picking.search([("products_availability_state", "=", "late")])
        self.assertIn(picking, late, "a shortage picking must be searchable as late")
        available = Picking.search(
            [("products_availability_state", "=", "available")],
        )
        self.assertNotIn(
            picking,
            available,
            "the clean sibling move must not leak the picking into 'available'",
        )
        # in/not-in operators mirror the same single-state classification
        self.assertIn(
            picking,
            Picking.search(
                [("products_availability_state", "in", ["late", "expected"])],
            ),
        )
        self.assertNotIn(
            picking,
            Picking.search(
                [("products_availability_state", "not in", ["late"])],
            ),
        )
