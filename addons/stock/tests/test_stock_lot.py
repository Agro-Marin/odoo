from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import Form

from odoo.addons.stock.tests.common import TestStockCommon


class TestLotSerial(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.locationA = cls.env["stock.location"].create(
            {
                "name": "Location A",
                "usage": "internal",
            }
        )
        cls.locationB = cls.env["stock.location"].create(
            {
                "name": "Location B",
                "usage": "internal",
            }
        )
        cls.locationC = cls.env["stock.location"].create(
            {
                "name": "Location C",
                "usage": "internal",
            }
        )
        cls.productA.tracking = "lot"
        cls.lot_p_a = cls.LotObj.create(
            {
                "name": "lot_product_a",
                "product_id": cls.productA.id,
            }
        )
        cls.StockQuantObj.create(
            {
                "product_id": cls.productA.id,
                "location_id": cls.locationA.id,
                "quantity": 10.0,
                "lot_id": cls.lot_p_a.id,
            }
        )

        cls.productB.tracking = "serial"
        cls.lot_p_b = cls.LotObj.create(
            {
                "name": "lot_product_b",
                "product_id": cls.productB.id,
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.productB,
            cls.locationA,
            1.0,
            lot_id=cls.lot_p_b,
        )

    def test_single_location(self):
        self.assertEqual(self.lot_p_a.location_id, self.locationA)
        self.assertEqual(self.lot_p_b.location_id, self.locationA)

        lot_b_form = Form(self.lot_p_b)
        lot_b_form.location_id = self.locationB
        lot_b_form.save()
        self.assertEqual(
            self.lot_p_b.quant_ids.filtered(lambda q: q.quantity > 0).location_id,
            self.locationB,
        )

        self.lot_p_b.quant_ids.move_quants(
            location_dest_id=self.locationC, message="test_quant_move"
        )
        self.assertEqual(self.lot_p_b.location_id, self.locationC)

        self.StockQuantObj.create(
            {
                "product_id": self.productA.id,
                "location_id": self.locationC.id,
                "quantity": 10.0,
                "lot_id": self.lot_p_a.id,
            }
        )
        self.assertEqual(self.lot_p_a.location_id.id, False)

        self.lot_p_a.quant_ids.filtered(
            lambda q: q.location_id == self.locationA
        ).move_quants(location_dest_id=self.locationC)
        self.StockQuantObj.invalidate_model()
        self.StockQuantObj._unlink_zero_quants()
        self.assertEqual(self.lot_p_a.location_id, self.locationC)

    def test_import_lots(self):
        vals = self.MoveObj.action_generate_lot_line_vals(
            {
                "default_tracking": "lot",
                "default_product_id": self.productA.id,
                "default_location_dest_id": self.locationC.id,
            },
            "import",
            "",
            0,
            "aze;2\nqsd;4\nwxc",
        )

        self.assertEqual(len(vals), 3)
        self.assertEqual(vals[0]["lot_name"], "aze")
        self.assertEqual(vals[0]["quantity"], 2)
        self.assertEqual(vals[1]["lot_name"], "qsd")
        self.assertEqual(vals[1]["quantity"], 4)
        self.assertEqual(vals[2]["lot_name"], "wxc")
        self.assertEqual(vals[2]["quantity"], 1, "default lot qty")

    def test_lot_no_company(self):
        picking1 = self.env["stock.picking"].create(
            {
                "name": "Picking 1",
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "move_ids": [
                    Command.create(
                        {
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                            "product_id": self.productB.id,
                            "product_uom_qty": 1.0,
                        }
                    )
                ],
            }
        )
        picking1.action_confirm()
        move = picking1.move_ids
        move.move_line_ids.lot_name = "sn_test"
        move.picked = True
        picking1._action_done()
        self.assertEqual(move.state, "done")
        self.assertTrue(move.move_line_ids.lot_id)
        self.assertFalse(move.move_line_ids.lot_id.company_id)

    def test_lot_uniqueness(self):
        lot_1 = self.env["stock.lot"].create(
            {
                "name": "unique",
                "product_id": self.productB.id,
                "company_id": False,
            }
        )
        self.assertTrue(lot_1)
        with self.assertRaises(ValidationError):
            self.env["stock.lot"].create(
                {
                    "name": "unique",
                    "product_id": self.productB.id,
                    "company_id": False,
                }
            )
        with self.assertRaises(ValidationError):
            self.env["stock.lot"].create(
                {
                    "name": "unique",
                    "product_id": self.productB.id,
                    "company_id": self.env.company.id,
                }
            )

        lot_2 = self.env["stock.lot"].create(
            {
                "name": "also_unique",
                "product_id": self.productB.id,
                "company_id": self.env.company.id,
            }
        )
        self.assertTrue(lot_2)
        with self.assertRaises(ValidationError):
            self.env["stock.lot"].create(
                {
                    "name": "also_unique",
                    "product_id": self.productB.id,
                    "company_id": False,
                }
            )
        with self.assertRaises(ValidationError):
            self.env["stock.lot"].create(
                {
                    "name": "also_unique",
                    "product_id": self.productB.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_bypass_reservation(self):
        customer = self.PartnerObj.create({"name": "bob"})
        delivery_picking = self.env["stock.picking"].create(
            {
                "partner_id": customer.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productC.id,
                            "product_uom_qty": 5,
                            "quantity": 5,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        additional_product = self.productA
        lot = self.lot_p_a
        lot.location_id = self.stock_location
        quant = additional_product.stock_quant_ids.filtered(
            lambda q: q.location_id == self.stock_location
        )
        self.assertRecordValues(quant, [{"quantity": 10.0, "reserved_quantity": 0.0}])
        delivery_picking.button_validate()
        delivery_picking.is_locked = False
        self.env["stock.move.line"].create(
            {
                "product_id": additional_product.id,
                "product_uom_id": additional_product.uom_id.id,
                "picking_id": delivery_picking.id,
                "quantity": 3,
                "lot_id": lot.id,
                "quant_id": quant.id,
            }
        )
        self.assertRecordValues(
            delivery_picking.move_ids,
            [
                {"state": "done", "quantity": 5.0, "picked": True},
                {"state": "done", "quantity": 3.0, "picked": True},
            ],
        )
        self.assertRecordValues(quant, [{"quantity": 7.0, "reserved_quantity": 0.0}])

    def test_location_lot_id_update_quant_qty(self):
        self.assertEqual(self.lot_p_b.location_id, self.locationA)
        starting_quant = self.lot_p_b.quant_ids
        self.assertEqual(starting_quant.quantity, 1)
        move = self.env["stock.move"].create(
            {
                "location_id": self.locationA.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.productB.id,
                "product_uom_qty": 1.0,
            }
        )
        move._action_confirm()
        self.assertEqual(move.state, "confirmed")
        move._action_assign()
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, "done")
        self.assertEqual(starting_quant.quantity, 0)
        self.assertEqual(self.lot_p_b.location_id.id, self.customer_location.id)
        move = self.env["stock.move"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.locationA.id,
                "product_id": self.productB.id,
                "lot_ids": self.lot_p_b,
                "product_uom_qty": 1.0,
            }
        )
        move._action_confirm()
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, "done")
        self.assertEqual(starting_quant.quantity, 1)
        self.assertEqual(self.lot_p_b.location_id, self.locationA)

    def test_lot_id_with_branch_company(self):
        branch_a = self.env["res.company"].create(
            {
                "name": "Branch X",
                "country_id": self.env.company.country_id.id,
                "parent_id": self.env.company.id,
            }
        )
        self.assertEqual(self.productB.tracking, "serial")
        self.productB.company_id = self.env.company
        branch_a_warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", branch_a.id)]
        )
        branch_receipt_type = self.env["stock.picking.type"].search(
            [("company_id", "=", branch_a.id), ("code", "=", "incoming")], limit=1
        )
        picking1 = self.env["stock.picking"].create(
            {
                "name": "Picking 1",
                "location_id": self.supplier_location.id,
                "location_dest_id": branch_a_warehouse.lot_stock_id.id,
                "picking_type_id": branch_receipt_type.id,
            }
        )
        move = (
            self.env["stock.move"]
            .with_company(branch_a)
            .create(
                {
                    "location_id": self.supplier_location.id,
                    "location_dest_id": branch_a_warehouse.lot_stock_id.id,
                    "product_id": self.productB.id,
                    "product_uom_qty": 1.0,
                    "picking_id": picking1.id,
                }
            )
        )
        picking1.with_company(branch_a).action_confirm()
        move.move_line_ids.lot_name = "sn_test"
        move.picked = True
        picking1.with_company(branch_a)._action_done()
        self.assertTrue(move.move_line_ids.lot_id)
        self.assertEqual(move.state, "done")
        sn_form = Form(self.env["stock.lot"].with_company(branch_a))
        sn_form.name = "sn_test_2"
        sn_form.product_id = self.productB
        sn = sn_form.save()
        self.assertEqual(sn.company_id, branch_a)

    def test_lot_search_partner_ids(self):
        lot_location = self.env["stock.location"].create(
            {
                "name": "Test Lots Only",
                "usage": "internal",
            }
        )
        product_lot_a, product_lot_b = self.env["product.product"].create(
            [
                {"name": "product_lot_a", "is_storable": True, "tracking": "lot"},
                {"name": "product_lot_b", "is_storable": True, "tracking": "serial"},
            ]
        )
        lot_a, lot_b = self.env["stock.lot"].create(
            [
                {"name": "test_lot_product_a", "product_id": product_lot_a.id},
                {"name": "test_lot_product_b", "product_id": product_lot_b.id},
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            product_lot_a,
            lot_location,
            1.0,
            lot_id=lot_a,
        )
        self.env["stock.quant"]._update_available_quantity(
            product_lot_b,
            lot_location,
            1.0,
            lot_id=lot_b,
        )

        customer = self.PartnerObj.create(
            {"name": "bob uniquename person to avoid conflicts with demo data"}
        )
        picking1 = self.env["stock.picking"].create(
            {
                "name": "Picking 1",
                "partner_id": customer.id,
                "location_id": lot_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "move_ids": [
                    Command.create(
                        {
                            "location_id": lot_location.id,
                            "location_dest_id": self.customer_location.id,
                            "product_id": product_lot_a.id,
                            "product_uom_qty": 1.0,
                            "quantity": 1.0,
                        }
                    )
                ],
            }
        )
        picking1.move_ids.move_line_ids.lot_id = lot_a
        picking1.action_confirm()
        picking1.button_validate()
        lot_id = self.env["stock.lot"].search(
            [
                ("partner_ids", "!=", False),
                ("product_id", "in", (product_lot_a | product_lot_b).ids),
            ]
        )
        self.assertEqual(len(lot_id), 1)
        self.assertEqual(lot_id, lot_a)
        lot_id = self.env["stock.lot"].search(
            [("partner_ids", "=", False), ("location_id", "=", lot_location.id)]
        )
        self.assertEqual(len(lot_id), 1)
        self.assertEqual(lot_id, lot_b)
        lot_id = self.env["stock.lot"].search(
            [("partner_ids.name", "ilike", "bob uniquename person to avoid conflicts")]
        )
        self.assertEqual(len(lot_id), 1)
        self.assertEqual(lot_id, lot_a)

    def test_product_qty_search_matches_compute(self):
        transit = self.env["stock.location"].create(
            {"name": "Transit X", "usage": "transit", "company_id": self.env.company.id}
        )
        product = self.env["product.product"].create(
            {"name": "qty parity", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qty-parity-lot", "product_id": product.id}
        )

        self.env["stock.quant"]._update_available_quantity(
            product, transit, 7.0, lot_id=lot
        )
        self.env["stock.quant"].invalidate_model()
        self.assertEqual(lot.product_qty, 0.0)
        self.assertNotIn(lot, self.env["stock.lot"].search([("product_qty", ">", 0)]))
        self.assertIn(
            lot,
            self.env["stock.lot"].search(
                [("id", "=", lot.id), ("product_qty", "=", 0)]
            ),
        )

        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 3.0, lot_id=lot
        )
        self.env["stock.quant"].invalidate_model()
        lot.invalidate_recordset()
        self.assertEqual(lot.product_qty, 3.0)
        self.assertIn(lot, self.env["stock.lot"].search([("product_qty", ">", 0)]))

        empty_loc = self.env["stock.location"].create(
            {
                "name": "Empty Loc",
                "usage": "internal",
                "location_id": self.stock_location.location_id.id,
            }
        )
        self.assertEqual(lot.with_context(location=empty_loc.id).product_qty, 0.0)
        self.assertNotIn(
            lot,
            self.env["stock.lot"]
            .with_context(location=empty_loc.id)
            .search([("id", "=", lot.id), ("product_qty", ">", 0)]),
        )

    def test_delivery_ids_traceability_graph(self):
        out_type = self.picking_type_out

        def mk_lot(name):
            product = self.env["product.product"].create(
                {"name": name, "is_storable": True, "tracking": "lot"}
            )
            return self.env["stock.lot"].create(
                {"name": f"lot-{name}", "product_id": product.id}
            )

        def mk_done_line(lot, picking=None, children=None):
            move = self.env["stock.move"].create(
                {
                    "product_id": lot.product_id.id,
                    "product_uom_qty": 1,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "picking_id": picking.id if picking else False,
                }
            )
            line = self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": lot.product_id.id,
                    "lot_id": lot.id,
                    "quantity": 1,
                    "picking_id": picking.id if picking else False,
                }
            )
            move.write({"state": "done"})
            if children:
                child_ids = [mk_done_line(child).id for child in children]
                line.produce_line_ids = [Command.set(child_ids)]
            return line

        L0, L1, L2, L3 = (mk_lot(n) for n in ("L0", "L1", "L2", "L3"))
        mk_done_line(L3, children=[L1, L2])
        mk_done_line(L1, children=[L0])
        mk_done_line(L2, children=[L0])
        pk0, pk3 = (
            self.env["stock.picking"].create(
                {
                    "picking_type_id": out_type.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                }
            )
            for _i in range(2)
        )
        mk_done_line(L0, picking=pk0)
        mk_done_line(L3, picking=pk3)
        self.env["stock.move.line"].invalidate_model()

        by_lot = (L0 + L1 + L2 + L3)._find_delivery_ids_by_lot()
        self.assertEqual(set(by_lot[L3.id]), {pk0.id, pk3.id})
        self.assertEqual(set(by_lot[L1.id]), {pk0.id})
        self.assertEqual(set(by_lot[L2.id]), {pk0.id})
        self.assertEqual(set(by_lot[L0.id]), {pk0.id})

        self.assertEqual(set(L3._find_delivery_ids_by_lot()[L3.id]), {pk0.id, pk3.id})
        self.assertEqual(L3.delivery_ids, pk0 | pk3)

    def test_default_lot_sequence(self):
        product_a = self.env["product.product"].create(
            {
                "name": "Test Product A",
                "is_storable": True,
                "tracking": "lot",
                "serial_prefix_format": False,
            }
        )
        default_lot_sequence = self.env.ref("stock.sequence_production_lots")
        product_a.invalidate_recordset()
        self.assertEqual(product_a.lot_sequence_id, default_lot_sequence)


class TestLotNameFormat(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Formatted lot product",
                "is_storable": True,
                "tracking": "lot",
                "lot_name_format": "%(y)s%(month)s%(day)s - %(ref)s",
            }
        )

    def test_name_is_composed_when_left_empty(self):
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.product.id,
                "ref": "AYE4B1501C",
            }
        )
        expected = fields.Datetime.context_timestamp(
            lot, fields.Datetime.now()
        ).strftime("%y%m%d")
        self.assertEqual(lot.name, f"{expected} - AYE4B1501C")

    def test_ref_slot_falls_back_to_the_sequence(self):
        first, second = self.env["stock.lot"].create(
            [
                {"product_id": self.product.id},
                {"product_id": self.product.id},
            ]
        )
        self.assertTrue(first.name)
        self.assertNotEqual(first.name, second.name)

    def test_an_explicit_name_is_never_overwritten(self):
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.product.id,
                "name": "TYPED-BY-HAND",
            }
        )
        self.assertEqual(lot.name, "TYPED-BY-HAND")

    def test_products_without_a_format_are_untouched(self):
        plain = self.env["product.product"].create(
            {
                "name": "Plain lot product",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        lot = self.env["stock.lot"].create({"product_id": plain.id})
        self.assertTrue(lot.name)
        self.assertNotIn(" - ", lot.name)

    def test_a_composed_name_parses_back(self):
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.product.id,
                "ref": "AYE4B1501C",
            }
        )
        parsed = lot._parse_name()
        self.assertIsNotNone(parsed, f"{lot.name!r} does not match its own format")
        self.assertEqual(parsed["ref"], "AYE4B1501C")
        self.assertEqual(
            parsed["y"],
            fields.Datetime.context_timestamp(lot, fields.Datetime.now()).strftime(
                "%y"
            ),
        )

    def test_a_legacy_name_parses_to_nothing(self):
        lot = self.env["stock.lot"].create(
            {
                "product_id": self.product.id,
                "name": "OLD-STYLE-NAME",
            }
        )
        self.assertIsNone(lot._parse_name())
