from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tests import Form, TransactionCase

from odoo.addons.stock.tests.common import DoneMoveCase, TestStockCommon


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
        self.StockQuantObj._remove_zero_quants()
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

        by_lot = (L0 + L1 + L2 + L3)._get_delivery_ids_by_lot()
        self.assertEqual(set(by_lot[L3.id]), {pk0.id, pk3.id})
        self.assertEqual(set(by_lot[L1.id]), {pk0.id})
        self.assertEqual(set(by_lot[L2.id]), {pk0.id})
        self.assertEqual(set(by_lot[L0.id]), {pk0.id})

        self.assertEqual(set(L3._get_delivery_ids_by_lot()[L3.id]), {pk0.id, pk3.id})
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


class TestLotNameFormatEverywhere(DoneMoveCase):
    def _formatted(self, lot_format):
        return self.Product.create(
            {
                "name": f"Formatted {lot_format}",
                "is_storable": True,
                "tracking": "lot",
                "lot_name_format": lot_format,
            }
        )

    def test_the_next_lot_vals_follow_the_format(self):
        product = self._formatted("LF-%(ref)s")
        vals = self.Lot._prepare_next_lot_vals(self.env.company, product)
        self.assertTrue(vals["name"].startswith("LF-"), vals["name"])
        self.assertEqual(
            self.Lot.create({"product_id": product.id}).name[:3],
            "LF-",
        )

    def test_a_format_without_ref_cannot_keep_names_apart(self):
        with self.assertRaises(ValidationError):
            self._formatted("M-%(year)s%(month)s")
        product = self._formatted("M-%(ref)s")
        with self.assertRaises(ValidationError):
            product.lot_name_format = "M-%(year)s"

    def test_a_free_name_skips_an_archived_lot(self):
        product = self.Product.create(
            {"name": "Free name", "is_storable": True, "tracking": "serial"}
        )
        self.Lot.create({"name": "FREE0001", "product_id": product.id})
        archived = self.Lot.create({"name": "FREE0002", "product_id": product.id})
        archived.active = False
        self.env.flush_all()
        self.assertEqual(
            self.Lot._get_free_lot_name(self.env.company, product, "FREE0001"),
            "FREE0003",
        )


class TestLotNameFormatVocabulary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lot = cls.env["stock.lot"]

    def _product(self, lot_name_format):
        return self.env["product.product"].create(
            {
                "name": "Formatted %s" % lot_name_format,
                "is_storable": True,
                "tracking": "lot",
                "lot_name_format": lot_name_format,
            }
        )

    def test_every_parsed_placeholder_family_also_composes(self):
        placeholders = set(self.Lot._get_lot_name_placeholders()) - {"ref"}
        self.assertGreater(len(placeholders), 14, "the three families are expected")
        for placeholder in sorted(placeholders):
            with self.subTest(placeholder=placeholder):
                product = self._product("%%(%s)s-%%(ref)s-X" % placeholder)
                lot = self.Lot.create({"product_id": product.id})
                self.assertTrue(lot.name.endswith("-X"))

    def test_an_unusable_format_is_a_message_not_a_traceback(self):
        for lot_format in ("100%-%(ref)s", "%(bogus)s-%(ref)s", "%(ref)s-%(year)"):
            with self.subTest(lot_format=lot_format):
                product = self._product(lot_format)
                with self.assertRaises(UserError) as caught:
                    self.Lot.create({"product_id": product.id})
                self.assertIn(product.display_name, str(caught.exception))

    def test_a_product_with_no_sequence_at_all_says_so(self):
        product = self.env["product.product"].create(
            {"name": "Sequenceless", "is_storable": True, "tracking": "lot"}
        )
        product.lot_sequence_id = False
        self.env["ir.sequence"].search([("code", "=", "stock.lot.serial")]).unlink()
        with self.assertRaises(UserError) as caught:
            self.Lot.create({"product_id": product.id})
        self.assertIn(product.display_name, str(caught.exception))


class TestLotUniquenessSeesArchivedLots(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lot = cls.env["stock.lot"]
        cls.product = cls.env["product.product"].create(
            {"name": "Archivable", "is_storable": True, "tracking": "serial"}
        )

    def test_an_archived_lot_still_holds_its_name(self):
        archived = self.Lot.create({"name": "SN00010", "product_id": self.product.id})
        archived.active = False
        self.env.flush_all()
        with self.assertRaises(ValidationError):
            self.Lot.create({"name": "SN00010", "product_id": self.product.id})

    def test_the_cross_company_rule_sees_archived_lots(self):
        archived = self.Lot.create(
            {"name": "SNX", "product_id": self.product.id, "company_id": False}
        )
        archived.active = False
        self.env.flush_all()
        with self.assertRaises(ValidationError):
            self.Lot.create(
                {
                    "name": "SNX",
                    "product_id": self.product.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_un_archiving_re_checks_the_rule(self):
        archived = self.Lot.create(
            {"name": "SNY", "product_id": self.product.id, "company_id": False}
        )
        archived.active = False
        self.env.flush_all()
        self.env.cr.execute(
            """INSERT INTO stock_lot
               (name, product_id, company_id, active, create_uid, write_uid, create_date, write_date)
               VALUES ('SNY', %s, %s, true, 1, 1, now(), now())""",
            (self.product.id, self.env.company.id),
        )
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            archived.active = True
            self.env.flush_all()

    def test_prepare_next_lot_vals_is_the_one_place_that_decides(self):
        vals = self.Lot._prepare_next_lot_vals(self.env.company, self.product)
        self.assertEqual(vals["product_id"], self.product.id)
        self.Lot.create(vals)
        self.env.flush_all()
        self.Lot.create(self.Lot._prepare_next_lot_vals(self.env.company, self.product))
        self.env.flush_all()


class TestLotUniquenessScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lot = cls.env["stock.lot"]
        cls.product_a, cls.product_b = cls.env["product.product"].create(
            [
                {"name": "PA", "is_storable": True, "tracking": "lot"},
                {"name": "PB", "is_storable": True, "tracking": "lot"},
            ]
        )

    def test_a_violation_on_a_cross_pair_is_not_this_batch_s(self):
        lot_a = self.Lot.create({"name": "N1", "product_id": self.product_a.id})
        lot_b = self.Lot.create({"name": "N2", "product_id": self.product_b.id})
        self.env.flush_all()
        self.env.cr.execute(
            """INSERT INTO stock_lot
               (name, product_id, company_id, active, create_uid, write_uid, create_date, write_date)
               VALUES ('N1', %s, NULL, true, 1, 1, now(), now()),
                      ('N1', %s, %s,   true, 1, 1, now(), now())""",
            (self.product_b.id, self.product_b.id, self.env.company.id),
        )
        self.env.invalidate_all()
        (lot_a + lot_b)._check_unique_lot()

    def test_a_real_duplicate_in_the_batch_is_still_reported(self):
        lot = self.Lot.create({"name": "M1", "product_id": self.product_a.id})
        self.env.flush_all()
        with self.assertRaises(ValidationError):
            self.Lot.create({"name": "M1", "product_id": self.product_a.id})
        self.assertTrue(lot.exists())

    def test_a_lot_can_be_duplicated_more_than_once(self):
        source = self.Lot.create({"name": "ORIG", "product_id": self.product_a.id})
        self.env.flush_all()
        first = source.copy()
        second = source.copy()
        self.env.flush_all()
        self.assertNotEqual(first.name, second.name)


class TestLotCompanyAtBranchDepth(TransactionCase):
    def test_the_owner_s_branch_gets_the_lot_at_any_depth(self):
        Company = self.env["res.company"]
        root = self.env.company
        chain = [root]
        for index in range(3):
            chain.append(
                Company.create({"name": "Branch %d" % index, "parent_id": chain[-1].id})
            )
        product = self.env["product.product"].create(
            {
                "name": "Root owned",
                "is_storable": True,
                "tracking": "serial",
                "company_id": root.id,
            }
        )
        for depth, company in enumerate(chain[1:], start=1):
            with self.subTest(depth=depth):
                lot = (
                    self.env["stock.lot"]
                    .with_company(company)
                    .with_context(allowed_company_ids=company.ids)
                    .new({"product_id": product.id})
                )
                lot._compute_company_id()
                self.assertEqual(
                    lot.company_id,
                    company,
                    "a branch that cannot reach the owner keeps its own company",
                )

    def test_an_accessible_owner_still_wins(self):
        product = self.env["product.product"].create(
            {
                "name": "Own company",
                "is_storable": True,
                "tracking": "serial",
                "company_id": self.env.company.id,
            }
        )
        lot = self.env["stock.lot"].create({"product_id": product.id})
        self.assertEqual(lot.company_id, self.env.company)

    def test_a_shared_product_makes_a_company_less_lot(self):
        product = self.env["product.product"].create(
            {"name": "Shared", "is_storable": True, "tracking": "serial"}
        )
        lot = self.env["stock.lot"].create({"product_id": product.id})
        self.assertFalse(lot.company_id)


class TestLotQuantityScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Shelf", "usage": "internal", "location_id": cls.stock.id}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Scoped", "is_storable": True, "tracking": "lot"}
        )
        cls.lot = cls.env["stock.lot"].create(
            {"name": "SCOPE", "product_id": cls.product.id}
        )
        cls.quant = cls.env["stock.quant"].create(
            {
                "product_id": cls.product.id,
                "location_id": cls.shelf.id,
                "quantity": 12.0,
                "lot_id": cls.lot.id,
            }
        )

    def test_strict_is_a_dependency_of_product_qty(self):
        scoped = {"location": self.stock.id}
        loose = self.lot.with_context(**scoped).product_qty
        strict = self.lot.with_context(strict=True, **scoped).product_qty
        self.assertEqual(loose, 12.0)
        self.assertEqual(strict, 0.0, "the quant is in a child of the scope")

    def test_moving_a_quant_moves_the_lot_s_single_location(self):
        self.assertEqual(self.lot.location_id, self.shelf)
        other = self.env["stock.location"].create(
            {"name": "Other", "usage": "internal", "location_id": self.stock.id}
        )
        self.quant.location_id = other
        self.env.flush_all()
        self.assertEqual(self.lot.location_id, other)

    def test_the_quantity_search_answers_the_operators_product_does(self):
        self.assertIn(
            self.lot,
            self.env["stock.lot"].search([("product_qty", "ilike", "12")]),
        )


class TestLotHookContracts(TransactionCase):
    def test_the_outgoing_domain_is_a_domain(self):
        self.assertIsInstance(
            self.env["stock.lot"]._get_domain_outgoing_move_lines(),
            Domain,
            "overrides combine it with | and callers with &",
        )

    def test_partners_from_deliveries_is_a_recordset(self):
        pickings = self.env["stock.picking"]
        self.assertEqual(
            self.env["stock.lot"]._get_partners_from_deliveries(pickings)._name,
            "res.partner",
        )

    def test_generate_lot_names_returns_names(self):
        names = self.env["stock.lot"].prepare_lot_names("SN0009", 3)
        self.assertEqual(names, ["SN0009", "SN0010", "SN0011"])

    def test_the_permission_hook_takes_its_products_as_an_argument(self):
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "incoming")], limit=1
        )
        picking_type.use_create_lots = False
        product = self.env["product.product"].create(
            {"name": "Blocked", "is_storable": True, "tracking": "lot"}
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.env.ref("stock.stock_location_stock").id,
            }
        )
        Lot = self.env["stock.lot"].with_context(active_picking_id=picking.id)
        with self.assertRaises(UserError):
            Lot.create({"name": "NOPE", "product_id": product.id})

    def test_renaming_a_lot_is_the_same_permission_as_naming_one(self):
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "incoming")], limit=1
        )
        product = self.env["product.product"].create(
            {"name": "Renamable", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create({"name": "KEEP", "product_id": product.id})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.env.ref("stock.stock_location_stock").id,
            }
        )
        picking_type.use_create_lots = False
        with self.assertRaises(UserError):
            lot.with_context(active_picking_id=picking.id).write({"name": "RENAMED"})


class TestDisplayCompleteHasTwoInputs(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Displayable", "is_storable": True, "tracking": "lot"}
        )

    def test_a_saved_lot_is_complete_with_no_context(self):
        lot = self.env["stock.lot"].create({"product_id": self.product.id})
        self.assertTrue(lot.display_complete)

    def test_an_unsaved_lot_is_not_complete_by_default(self):
        lot = self.env["stock.lot"].new({"product_id": self.product.id})
        self.assertFalse(lot.display_complete)

    def test_the_context_key_completes_an_unsaved_lot(self):
        lot = (
            self.env["stock.lot"]
            .with_context(display_complete=True)
            .new({"product_id": self.product.id})
        )
        self.assertTrue(lot.display_complete)

    def test_the_key_is_a_declared_dependency(self):
        Lot = self.env["stock.lot"]
        __, depends_context = Lot._fields["display_complete"].get_depends(Lot)
        self.assertIn("display_complete", depends_context)

    def test_strict_is_a_declared_dependency_of_product_qty(self):
        Lot = self.env["stock.lot"]
        __, depends_context = Lot._fields["product_qty"].get_depends(Lot)
        self.assertIn("strict", depends_context)

    def test_the_value_is_a_boolean(self):
        lot = self.env["stock.lot"].create({"product_id": self.product.id})
        self.assertIs(lot.display_complete, True)
