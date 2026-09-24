import json
from datetime import datetime, timedelta

from psycopg.errors import CheckViolation

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestOperationsEdgeCases(TestStockCommon):
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

    def test_package_type_company_only_write_without_sequence(self):
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

        no_seq_type.write({"sequence_code": "PTAUD2"})
        self.assertTrue(no_seq_type.sequence_id)
        self.assertEqual(no_seq_type.sequence_id.prefix, "PTAUD2")
        self.assertEqual(no_seq_type.sequence_id.company_id, company)

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

    def test_lot_company_change_guard_multi_location(self):
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
        picking_type.write({"sequence_code": "AUD16B"})
        self.assertEqual(picking_type.sequence_id.company_id, company_b)
        self.assertEqual(picking_type.sequence_id.prefix, "AUD16B")

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
        picking_type.write(
            {
                "warehouse_id": self.warehouse_1.id,
                "default_location_dest_id": self.shelf_1.id,
            }
        )
        self.assertEqual(picking_type.default_location_src_id, self.stock_location)
        self.assertEqual(picking_type.default_location_dest_id, self.shelf_1)

    def test_picking_type_multistep_locations_survive_step_change(self):
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
        self.warehouse_1.delivery_steps = "ship_only"
        self.warehouse_1.delivery_steps = "pick_pack_ship"
        self.assertEqual(
            pack_type.default_location_src_id,
            self.warehouse_1.wh_pack_stock_loc_id,
        )

    def test_picking_type_incoming_source_without_warehouse(self):
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
        self.assertEqual(baseline.scrap_location_id, company._get_scrap_location())
        self.assertNotEqual(
            baseline.scrap_location_id,
            default_loss,
            "scrapped goods stay apart from inventory adjustments",
        )

        dedicated = self.StockLocationObj.create(
            {"name": "Audit Casse", "usage": "inventory", "company_id": company.id}
        )
        self.env["ir.model.data"].search(
            [
                ("module", "=", "stock"),
                ("name", "=", f"stock_location_scrap_company_{company.id}"),
            ]
        ).res_id = dedicated.id
        designated = self.env["stock.scrap"].create({"product_id": self.product_2.id})
        self.assertEqual(
            designated.scrap_location_id,
            dedicated,
            "The company-scoped external id must designate the scrap location",
        )

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

        regular = self.PickingObj.create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        regular.write({"picking_type_id": other_in_type.id})
        self.assertEqual(regular.location_id, other_in_type.default_location_src_id)

    def test_state_of_new_record_follows_cache(self):
        picking = self._create_confirmed_delivery(self.storable_1, 1)
        self.assertEqual(picking.state, "confirmed")
        new_picking = self.PickingObj.new(origin=picking)
        self.assertEqual(new_picking.state, "confirmed")
        new_picking.move_ids = False
        self.assertEqual(
            new_picking.state,
            "draft",
            "The form state must follow the pending (cache) moves",
        )
        self.assertEqual(picking.state, "confirmed")

    def test_a_recomputed_schedule_does_not_flatten_the_other_moves(self):
        picking = self._create_confirmed_delivery(self.storable_1, 1)
        sibling = self.MoveObj.create(
            {
                "product_id": self.storable_2.id,
                "product_uom_qty": 1,
                "product_uom_id": self.storable_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        picking.action_confirm()
        today = fields.Datetime.now()
        yesterday = today - timedelta(days=1)
        picking.move_ids.write({"date": today})
        self.env.flush_all()

        moved = picking.move_ids[0]
        moved.date = yesterday
        picking.write({"date_planned": picking.date_planned})
        self.env.flush_all()

        self.assertEqual(picking.date_planned, yesterday)
        self.assertEqual(moved.date, yesterday)
        self.assertEqual(
            sibling.date,
            today,
            "a sibling move keeps the date it was given",
        )

    def test_setting_the_schedule_by_hand_still_moves_every_open_move(self):
        picking = self._create_confirmed_delivery(self.storable_1, 1)
        self.MoveObj.create(
            {
                "product_id": self.storable_2.id,
                "product_uom_qty": 1,
                "product_uom_id": self.storable_2.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        picking.action_confirm()
        picking.move_ids.write({"date": fields.Datetime.now()})
        self.env.flush_all()

        wanted = fields.Datetime.now() + timedelta(days=9)
        picking.date_planned = wanted
        self.env.flush_all()
        self.assertEqual(picking.move_ids.mapped("date"), [wanted, wanted])

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
            expected[self.PickingObj.get_date_category(picking.date_planned)] += 1

        picking_type.invalidate_recordset(["kanban_dashboard_graph"])
        [graph_data] = json.loads(picking_type.kanban_dashboard_graph)
        totals = {value["category"]: value["value"] for value in graph_data["values"]}
        self.assertEqual(totals, expected)

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

    def test_reception_report_not_shown_for_other_warehouse_demand(self):
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
        picking.button_validate(skip_backorder=True)
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

    def test_lot_name_default_without_product_sequence(self):
        product = self.ProductObj.create(
            {"name": "Audit lot product", "is_storable": True, "tracking": "lot"}
        )
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

    @mute_logger("odoo.db.cursor")
    def test_storage_capacity_requires_exactly_one_target(self):
        category = self.env["stock.storage.category"].create({"name": "Audit Cat"})
        package_type = self.env["stock.package.type"].create({"name": "Audit PT"})
        Capacity = self.env["stock.storage.category.capacity"]
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
class TestPickingEdgeCases(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids = [
            (4, cls.env.ref("stock.group_production_lot").id),
            (4, cls.env.ref("stock.group_warning_stock").id),
        ]

    def _storable(self, **vals):
        return self.env["product.product"].create(
            {"name": "Picking audit product", "is_storable": True, **vals},
        )

    def _picking(self, product, qty=5, picking_type=None, assign=True):
        picking_type = picking_type or self.picking_type_out
        picking = self.env["stock.picking"].create(
            {"picking_type_id": picking_type.id},
        )
        self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            },
        )
        picking.action_confirm()
        if assign:
            picking.action_assign()
        return picking

    def test_shipping_weight_follows_the_move_quantity(self):
        product = self._storable(weight=2.0)
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 10.0)

        picking.move_ids.quantity = 3
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.shipping_weight, 6.0)

    def test_shipping_weight_follows_the_product_weight(self):
        product = self._storable(weight=2.0)
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 10.0)

        product.weight = 10.0
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.weight_bulk, 50.0)
        self.assertEqual(picking.shipping_weight, 50.0)

    def test_weight_and_volume_of_an_unsaved_picking(self):
        product = self._storable(weight=3.0, volume=2.0)
        picking = self.env["stock.picking"].new(
            {"picking_type_id": self.picking_type_out.id},
        )
        picking.move_line_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "quantity": 4,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                },
            ),
        ]
        picking.move_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "product_uom_qty": 4,
                    "quantity": 4,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                },
            ),
        ]
        self.assertEqual(picking.weight_bulk, 12.0)
        self.assertEqual(picking.shipping_volume, 8.0)

    def test_cancelled_moveless_picking_survives_a_write(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        picking.action_cancel()
        self.env.flush_all()
        self.assertEqual(picking.state, "cancel")

        picking.write({"location_id": picking.location_id.id})
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "cancel")

    def test_cancelled_moveless_picking_survives_an_unflushed_write(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        self.env.flush_all()

        picking.action_cancel()
        picking.write({"location_id": self.env.ref("stock.stock_location_stock").id})
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(
            picking.state,
            "cancel",
            "the cancel must survive an edit made before it reached the row",
        )

    def test_a_cancelled_transfer_stays_cancelled_when_its_moves_are_deleted(self):
        product = self._storable()
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [(0, 0, {"product_id": product.id, "product_uom_qty": 1})],
            },
        )
        picking.action_confirm()
        picking.action_cancel()
        self.env.flush_all()
        self.assertEqual(picking.state, "cancel")

        picking.move_ids.unlink()
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(
            picking.state,
            "cancel",
            "deleting the cancelled moves must not put the transfer back to draft",
        )

    def test_a_done_transfer_records_no_cancel(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            10,
        )
        picking = self._picking(product, qty=1)
        picking.move_ids.write({"quantity": 1, "picked": True})
        picking.button_validate(skip_backorder=True)
        self.env.flush_all()
        self.assertEqual(picking.state, "done")

        with self.assertRaises(UserError):
            picking.action_cancel()
        self.assertFalse(
            picking.is_cancelled,
            "a cancel that cannot take must not be recorded as one",
        )

    def test_moveless_picking_without_a_cancel_is_still_draft(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "draft")

    def test_delay_alert_search_answers_what_the_field_shows(self):
        early_product = self._storable()
        late_product = self._storable()
        upstream = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.int_type_id.id,
                "move_ids": [
                    (0, 0, {"product_id": early_product.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": late_product.id, "product_uom_qty": 1}),
                ],
            },
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    (0, 0, {"product_id": early_product.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": late_product.id, "product_uom_qty": 1}),
                ],
            },
        )
        upstream.action_confirm()
        picking.action_confirm()
        for product, date in (
            (early_product, datetime(2031, 1, 1)),
            (late_product, datetime(2031, 12, 1)),
        ):
            source = upstream.move_ids.filtered_domain(
                [("product_id", "=", product.id)]
            )
            picking.move_ids.filtered_domain(
                [("product_id", "=", product.id)]
            ).move_orig_ids = [(6, 0, source.ids)]
            source.date = date
        picking.move_ids.date = datetime(2030, 1, 1)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(picking.date_delay_alert, datetime(2031, 12, 1))
        Picking = self.env["stock.picking"]
        for operator, value, expected in (
            ("<", datetime(2031, 6, 1), False),
            ("=", datetime(2031, 1, 1), False),
            ("=", datetime(2031, 12, 1), True),
            (">", datetime(2031, 6, 1), True),
        ):
            with self.subTest(operator=operator, value=value):
                self.assertEqual(
                    bool(
                        Picking.search(
                            [
                                ("id", "=", picking.id),
                                ("date_delay_alert", operator, value),
                            ],
                        )
                    ),
                    expected,
                    "the search must classify by the same rule the field shows",
                )

    def test_delay_alert_of_an_unsaved_transfer_mixing_alerting_moves(self):
        early_product = self._storable()
        late_product = self._storable()
        upstream = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.int_type_id.id,
                "move_ids": [
                    (0, 0, {"product_id": early_product.id, "product_uom_qty": 1}),
                ],
            },
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    (0, 0, {"product_id": early_product.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": late_product.id, "product_uom_qty": 1}),
                ],
            },
        )
        upstream.action_confirm()
        picking.action_confirm()
        alerting = picking.move_ids.filtered(
            lambda move: move.product_id == early_product,
        )
        alerting.move_orig_ids = [(6, 0, upstream.move_ids.ids)]
        upstream.move_ids.date = datetime(2031, 12, 1)
        alerting.date = datetime(2030, 1, 1)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(
            sorted(picking.move_ids.mapped("date_delay_alert"), key=bool),
            [False, datetime(2031, 12, 1)],
            "the fixture needs one alerting move beside one that does not",
        )

        unsaved = self.env["stock.picking"].new(origin=picking)
        self.assertEqual(
            unsaved.date_delay_alert,
            datetime(2031, 12, 1),
            "an unsaved transfer must not compare a missing alert against a date",
        )

    def test_a_return_can_be_created_without_naming_its_locations(self):
        source = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id, "return_id": source.id},
        )
        self.env.flush_all()
        self.assertTrue(picking.location_id)
        self.assertTrue(picking.location_dest_id)

    def test_a_return_keeps_the_locations_it_was_given(self):
        source = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        shelf = self.env["stock.location"].create(
            {"name": "Return shelf", "location_id": self.stock_location.id},
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "return_id": source.id,
                "location_id": shelf.id,
            },
        )
        self.env.flush_all()
        self.assertEqual(picking.location_id, shelf)

        picking.partner_id = self.env["res.partner"].create({"name": "Return partner"})
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(
            picking.location_id,
            shelf,
            "a return must keep the source it was given across a partner change",
        )

    def test_the_owner_reaches_only_the_moves_being_finished(self):
        owner = self.env["res.partner"].create({"name": "Transfer owner"})
        kept = self._storable()
        dropped = self._storable()
        for product in (kept, dropped):
            self.env["stock.quant"]._update_available_quantity(
                product,
                self.stock_location,
                10,
            )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "owner_id": owner.id,
                "move_ids": [
                    (0, 0, {"product_id": kept.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": dropped.id, "product_uom_qty": 1}),
                ],
            },
        )
        picking.action_confirm()
        cancelled = picking.move_ids.filtered(lambda m: m.product_id == dropped)
        cancelled._action_cancel()
        picking.move_ids.filtered(lambda m: m.state != "cancel").write(
            {"quantity": 1, "picked": True},
        )
        picking.button_validate(skip_backorder=True)
        self.env.flush_all()
        self.assertEqual(picking.state, "done")
        self.assertFalse(
            cancelled.restrict_partner_id,
            "a cancelled move is not part of what the transfer just moved",
        )

    def test_an_action_context_the_framework_accepts_does_not_raise(self):
        action = self.env.ref("stock.action_picking_tree_incoming").sudo()
        action.context = (
            "{'restricted_picking_type_code': 'incoming',"
            " 'default_company_id': allowed_company_ids[0]}"
        )
        self.env.flush_all()
        Picking = self.env["stock.picking"].with_context(
            allowed_company_ids=[self.env.company.id],
        )
        self.assertIn(
            "No receipt yet",
            Picking.action_view_pickings_incoming()["help"],
        )

    def test_a_stored_action_help_is_not_discarded(self):
        action = self.env.ref("stock.stock_picking_action_picking_type").sudo()
        action.help = "<p>Our own help</p>"
        self.env.flush_all()
        self.assertIn(
            "Our own help",
            self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
                "stock.stock_picking_action_picking_type",
            )["help"],
        )

    def test_lot_check_covers_lines_that_will_be_autopicked(self):
        self.picking_type_in.write(
            {"use_create_lots": True, "use_existing_lots": False},
        )
        tracked = self._storable(tracking="lot")
        picking = self._picking(
            tracked,
            qty=4,
            picking_type=self.picking_type_in,
            assign=False,
        )
        picking.move_ids.quantity = 4
        self.env.flush_all()
        self.assertFalse(picking.move_ids.picked)
        self.assertTrue(picking._get_lot_move_lines_to_check())

    def test_multi_picking_lot_error_names_the_transfers(self):
        vals = {"use_create_lots": True, "use_existing_lots": False}
        if "auto_batch" in self.picking_type_in._fields:
            vals["auto_batch"] = False
        self.picking_type_in.write(vals)
        pickings = self.env["stock.picking"]
        for _index in range(2):
            picking = self._picking(
                self._storable(tracking="lot"),
                qty=2,
                picking_type=self.picking_type_in,
                assign=False,
            )
            picking.move_ids.quantity = 2
            pickings |= picking
        self.env.flush_all()
        with self.assertRaises(UserError) as caught:
            pickings.button_validate()
        message = str(caught.exception)
        for name in pickings.mapped("name"):
            self.assertIn(name, message)

    def test_autopick_still_ignores_a_pre_picked_scrap_move(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertIn(picking, picking._get_pickings_to_autopick())

    def test_unchanged_picking_type_write_on_a_done_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.button_validate(skip_backorder=True)
        self.env.flush_all()
        self.assertEqual(picking.state, "done")

        picking.write({"picking_type_id": picking.picking_type_id.id})
        self.assertEqual(picking.picking_type_id, self.picking_type_out)

    def test_changing_the_picking_type_of_a_done_picking_is_still_refused(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.button_validate(skip_backorder=True)
        self.env.flush_all()
        with self.assertRaises(UserError):
            picking.write({"picking_type_id": self.picking_type_in.id})

    def test_backorders_are_created_for_every_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            1000,
        )
        pickings = self.env["stock.picking"]
        for _index in range(3):
            pickings |= self._picking(product, qty=6)
        pickings.move_ids.quantity = 2
        pickings.move_ids.picked = True
        self.env.flush_all()

        backorders = pickings._create_backorder()
        self.assertEqual(len(backorders), 3)
        self.assertEqual(backorders.mapped("backorder_id"), pickings)
        self.assertFalse(
            [name for name in backorders.mapped("name") if not name or name == "/"],
            "each backorder takes its own sequence number",
        )
        self.assertFalse(backorders.user_id)
        for picking, backorder in zip(pickings, backorders, strict=True):
            self.assertEqual(backorder.picking_type_id, picking.picking_type_id)
            self.assertEqual(backorder.location_id, picking.location_id)

    def test_post_create_backorder_hook_runs_once_per_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            1000,
        )
        pickings = self.env["stock.picking"]
        for _index in range(2):
            pickings |= self._picking(product, qty=6)
        pickings.move_ids.quantity = 2
        pickings.move_ids.picked = True
        self.env.flush_all()

        seen = []
        original = type(pickings)._post_create_backorder

        def _record(self, backorder):
            seen.append((self.id, backorder.id))
            return original(self, backorder)

        self.patch(type(pickings), "_post_create_backorder", _record)
        backorders = pickings._create_backorder()
        self.assertEqual(
            seen,
            list(zip(pickings.ids, backorders.ids, strict=True)),
        )

    def test_log_activity_get_documents_tolerates_no_changes(self):
        self.assertEqual(
            self.env["stock.picking"]._get_log_activity_documents(
                {},
                "move_dest_ids",
                "UP",
            ),
            {},
        )

    def test_picking_warning_text_follows_the_partner_message(self):
        partner = self.env["res.partner"].create({"name": "Audit partner"})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "partner_id": partner.id,
            },
        )
        self.assertEqual(picking.picking_warning_text, "")
        partner.picking_warn_msg = "Ring the bell"
        self.assertEqual(picking.picking_warning_text, "Ring the bell\n")

    def test_has_tracking_follows_the_moves(self):
        picking = self._picking(self._storable(), qty=1, assign=False)
        self.assertFalse(picking.has_tracking)
        self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self._storable(tracking="lot").id,
                "product_uom_qty": 1,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            },
        )
        self.assertTrue(picking.has_tracking)

    def test_is_date_editable_follows_the_lock(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.button_validate(skip_backorder=True)
        self.env.flush_all()
        self.assertFalse(picking.is_date_editable)
        picking.action_toggle_is_locked()
        self.assertTrue(picking.is_date_editable)
