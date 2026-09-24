import datetime

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.stock.tests.common import TestStockCommon


class TestRobustness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.product1 = cls.env["product.product"].create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )

    def test_create_done_line_frees_over_reservation(self):
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(self.product1, self.stock_location, 10.0)

        move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 10.0,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        quant = Quant._gather(self.product1, self.stock_location, strict=True)
        self.assertEqual(quant.reserved_quantity, 10.0)

        loss_move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 0.0,
                "state": "done",
            }
        )
        self.env["stock.move.line"].create(
            {
                "move_id": loss_move.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 6.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        quant.invalidate_recordset(["quantity", "reserved_quantity"])
        self.assertEqual(quant.quantity, 4.0)
        self.assertEqual(quant.reserved_quantity, 4.0)

    def test_uom_factor(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product1,
            self.stock_location,
            12,
        )

        move1 = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_dozen.id,
                "product_uom_qty": 1,
            }
        )
        move1._action_confirm()
        move1._action_assign()
        self.assertEqual(move1.state, "assigned")
        quant = self.env["stock.quant"]._gather(
            self.product1,
            self.stock_location,
        )

        self.assertEqual(quant.reserved_quantity, 12)
        self.assertEqual(move1.state, "assigned")
        self.assertEqual(move1.product_qty, 12)

        move1._unreserve()

    def test_location_usage(self):
        test_stock_location = self.env["stock.location"].create(
            {
                "name": "Test Location",
                "location_id": self.stock_location.id,
            }
        )
        test_stock_location.usage = "inventory"

        self.env["stock.quant"]._update_available_quantity(
            self.product1,
            test_stock_location,
            1,
        )

        move = self.env["stock.move"].create(
            {
                "location_id": test_stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, "done")

        test_stock_location.usage = "internal"

        self.env["stock.quant"]._update_available_quantity(
            self.product1,
            test_stock_location,
            1,
        )

        with self.assertRaises(UserError):
            test_stock_location.usage = "inventory"

    def test_package_unpack(self):
        package = self.env["stock.package"].create(
            {
                "name": "Shell Helix HX7 10W30",
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            self.product1, self.stock_location, 10, package_id=package
        )

        move1 = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 10,
            }
        )
        move1._action_confirm()
        move1._action_assign()

        self.assertEqual(move1.move_line_ids.package_id, package)
        package.action_unpack()
        self.assertEqual(move1.move_line_ids.package_id, self.env["stock.package"])

        move1._unreserve()
        self.assertEqual(
            len(self.env["stock.quant"]._gather(self.product1, self.stock_location)), 1
        )
        self.assertEqual(
            len(
                self.env["stock.quant"]._gather(
                    self.product1, self.stock_location, package_id=package
                )
            ),
            0,
        )

        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product1, self.stock_location)
            .reserved_quantity,
            0,
        )

    def test_lot_id_product_id_mix(self):
        product1 = self.env["product.product"].create(
            {
                "name": "Product 1",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        product2 = self.env["product.product"].create(
            {
                "name": "Product 2",
                "is_storable": True,
                "tracking": "lot",
            }
        )

        lot1 = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": product1.id,
            }
        )
        lot2 = self.env["stock.lot"].create(
            {
                "name": "lot2",
                "product_id": product2.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            product1, self.stock_location, 1, lot_id=lot1
        )
        self.env["stock.quant"]._update_available_quantity(
            product2, self.stock_location, 1, lot_id=lot2
        )

        move1 = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1.0,
            }
        )
        move2 = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product2.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1.0,
            }
        )
        (move1 + move2)._action_confirm()

        with self.assertRaises(ValidationError):
            move1.write(
                {
                    "move_line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": product1.id,
                                "product_uom_id": self.uom_unit.id,
                                "quantity": 1,
                                "lot_id": lot2.id,
                                "location_id": move1.location_id.id,
                                "location_dest_id": move1.location_dest_id.id,
                            },
                        )
                    ]
                }
            )

        with self.assertRaises(ValidationError):
            move2.write(
                {
                    "move_line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": product2.id,
                                "product_uom_id": self.uom_unit.id,
                                "quantity": 1,
                                "lot_id": lot1.id,
                                "location_id": move2.location_id.id,
                                "location_dest_id": move2.location_dest_id.id,
                            },
                        )
                    ]
                }
            )

    def test_lot_quantity_remains_unchanged_after_done(self):
        productA = self.env["product.product"].create(
            {
                "name": "ProductA",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        lotA = self.env["stock.lot"].create(
            {
                "name": "lotA",
                "product_id": productA.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            productA, self.stock_location, 5, lot_id=lotA
        )
        moveA = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": productA.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 5.0,
            }
        )

        moveA._action_confirm()
        moveA.write(
            {
                "move_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": productA.id,
                            "product_uom_id": self.uom_unit.id,
                            "quantity": 5,
                            "lot_id": lotA.id,
                            "location_id": moveA.location_id.id,
                            "location_dest_id": moveA.location_dest_id.id,
                        },
                    )
                ]
            }
        )
        moveA._action_done()
        moveA._inverse_lot_ids()

        self.assertEqual(moveA.quantity, 5)

    def test_new_move_done_picking(self):
        product1 = self.env["product.product"].create(
            {"name": "P1", "is_storable": True}
        )
        product2 = self.env["product.product"].create(
            {"name": "P2", "is_storable": True}
        )

        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
            }
        )
        move1 = self.env["stock.move"].create(
            {
                "location_id": receipt.location_id.id,
                "location_dest_id": receipt.location_dest_id.id,
                "picking_id": receipt.id,
                "product_id": product1.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1.0,
            }
        )
        receipt.action_confirm()
        receipt.action_assign()
        move1.picked = True

        receipt.button_validate()

        self.assertEqual(receipt.state, "done")
        self.assertEqual(move1.state, "done")

        move2 = self.env["stock.move"].create(
            {
                "location_id": receipt.location_id.id,
                "location_dest_id": receipt.location_dest_id.id,
                "picking_id": receipt.id,
                "state": "draft",
                "product_id": product2.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 1.0,
                "quantity": 1.0,
            }
        )

        self.assertEqual(receipt.state, "done")
        self.assertEqual(move1.state, "done")
        self.assertEqual(move2.state, "done")

    def test_clean_quants_synch(self):
        product_reservation_too_high = self.env["product.product"].create(
            {
                "name": "Product Reservation",
                "is_storable": True,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product_reservation_too_high, self.stock_location, 10
        )
        quant = self.env["stock.quant"]._gather(
            product_reservation_too_high, self.stock_location
        )

        move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product_reservation_too_high.id,
                "product_uom_qty": 5,
            }
        )
        move._action_confirm()
        move._action_assign()

        self.env["stock.quant"]._update_reserved_quantity(
            product_reservation_too_high, self.stock_location, 2
        )
        self.assertEqual(quant.reserved_quantity, 7)
        self.env["stock.quant"]._sync_reserved_quantities()
        self.assertEqual(quant.reserved_quantity, 5)

        self.env["stock.quant"]._update_reserved_quantity(
            product_reservation_too_high, self.stock_location, -2
        )
        self.assertEqual(quant.reserved_quantity, 3)
        self.env["stock.quant"]._sync_reserved_quantities()
        self.assertEqual(quant.reserved_quantity, 5)

        self.env["stock.quant"]._update_reserved_quantity(
            product_reservation_too_high, self.stock_location, -2
        )
        self.assertEqual(quant.reserved_quantity, 3)
        move.picked = True
        move._action_done()
        self.assertEqual(quant.reserved_quantity, 0)

        product_without_move = self.env["product.product"].create(
            {
                "name": "Product reserved without move",
                "is_storable": True,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product_without_move, self.stock_location, 10
        )
        quant = self.env["stock.quant"]._gather(
            product_without_move, self.stock_location
        )
        self.env["stock.quant"]._update_reserved_quantity(
            product_without_move, self.stock_location, 2
        )

        self.assertEqual(quant.reserved_quantity, 2)
        self.env["stock.quant"]._sync_reserved_quantities()
        self.assertEqual(quant.reserved_quantity, 0)

    def test_clean_quants_synch_with_different_uom(self):
        uom_kg = self.env.ref("uom.product_uom_kgm")
        product_reservation_too_high = self.env["product.product"].create(
            {
                "name": "Product Reservation",
                "is_storable": True,
                "uom_id": uom_kg.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product_reservation_too_high, self.stock_location, 1
        )
        quant = self.env["stock.quant"]._gather(
            product_reservation_too_high, self.stock_location
        )
        move = self.env["stock.move"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product_reservation_too_high.id,
                "product_uom_qty": 100,
                "product_uom_id": self.env.ref("uom.product_uom_gram").id,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.env["stock.quant"]._update_reserved_quantity(
            product_reservation_too_high, self.stock_location, 0.2
        )
        self.assertAlmostEqual(quant.reserved_quantity, 0.3)
        self.env["stock.quant"]._sync_reserved_quantities()
        self.assertEqual(quant.reserved_quantity, 0.1)

    def test_clean_quants_synch_in_non_company_specific_locations(self):
        product_without_quant = self.env["product.product"].create(
            {
                "name": "Product reserved without quant",
                "is_storable": True,
                "company_id": self.stock_location.company_id.id,
            }
        )
        reservation_move = self.env["stock.move"].create(
            {
                "company_id": self.stock_location.company_id.id,
                "location_id": self.ref("stock.stock_location_inter_company"),
                "location_dest_id": self.stock_location.id,
                "product_id": product_without_quant.id,
                "product_uom_id": product_without_quant.uom_id.id,
                "product_uom_qty": 5.0,
            }
        )

        reservation_move._action_confirm()
        reservation_move.quantity = 5
        self.assertRecordValues(
            product_without_quant.stock_quant_ids,
            [
                {
                    "location_id": self.ref("stock.stock_location_inter_company"),
                    "reserved_quantity": 5.0,
                }
            ],
        )
        product_without_quant.stock_quant_ids.unlink()
        self.assertFalse(product_without_quant.stock_quant_ids)
        self.env["stock.quant"].action_view_quants()
        self.assertRecordValues(
            product_without_quant.stock_quant_ids,
            [
                {
                    "location_id": self.ref("stock.stock_location_inter_company"),
                    "reserved_quantity": 5.0,
                }
            ],
        )

    def test_push_rule_circular_recursion_guard(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        loc_a = self.env["stock.location"].create(
            {
                "name": "Location A",
                "usage": "internal",
                "location_id": warehouse.lot_stock_id.id,
            }
        )
        loc_b = self.env["stock.location"].create(
            {
                "name": "Location B",
                "usage": "internal",
                "location_id": warehouse.lot_stock_id.id,
            }
        )
        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Circular PT",
                "code": "internal",
                "sequence_code": "CIRC",
                "default_location_src_id": loc_a.id,
                "default_location_dest_id": loc_b.id,
                "warehouse_id": warehouse.id,
            }
        )
        route = self.env["stock.route"].create(
            {
                "name": "Circular Route",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "A → B",
                            "location_src_id": loc_a.id,
                            "location_dest_id": loc_b.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "transparent",
                            "picking_type_id": picking_type.id,
                        }
                    ),
                    Command.create(
                        {
                            "name": "B → A",
                            "location_src_id": loc_b.id,
                            "location_dest_id": loc_a.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "transparent",
                            "picking_type_id": picking_type.id,
                        }
                    ),
                ],
            }
        )
        product = self.env["product.product"].create(
            {
                "name": "Circular Product",
                "is_storable": True,
                "route_ids": [Command.link(route.id)],
            }
        )
        move = self.env["stock.move"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": loc_a.id,
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "product_uom_id": self.uom_unit.id,
                "move_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_id": self.uom_unit.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": loc_a.id,
                            "quantity": 1.0,
                        }
                    )
                ],
            }
        )
        move.picked = True
        with self.assertRaises(UserError):
            move._action_done()

    def test_move_location_write_unlinks_incompatible_lines(self):
        product = self.env["product.product"].create(
            {
                "name": "Test Product",
                "is_storable": True,
            }
        )
        other_location = self.env["stock.location"].create(
            {
                "name": "Other Location",
                "usage": "internal",
            }
        )
        empty_location = self.env["stock.location"].create(
            {
                "name": "Empty Location",
                "usage": "internal",
            }
        )
        self.env["stock.quant"]._update_available_quantity(product, other_location, 5.0)

        move = self.env["stock.move"].create(
            {
                "location_id": other_location.id,
                "location_dest_id": self.customer_location.id,
                "product_id": product.id,
                "product_uom_qty": 5.0,
                "product_uom_id": self.uom_unit.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.assertEqual(move.state, "assigned")
        self.assertTrue(move.move_line_ids)
        old_ml_ids = move.move_line_ids.ids

        move.location_id = empty_location
        self.assertFalse(self.env["stock.move.line"].browse(old_ml_ids).exists())

    def test_product_tmpl_id_stored_and_synced(self):
        template_a = self.env["product.template"].create(
            {
                "name": "Template A",
                "is_storable": True,
            }
        )
        template_b = self.env["product.template"].create(
            {
                "name": "Template B",
                "is_storable": True,
            }
        )
        product_a = template_a.product_variant_id
        product_b = template_b.product_variant_id

        move = self.env["stock.move"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": product_a.id,
                "product_uom_qty": 1.0,
                "product_uom_id": self.uom_unit.id,
            }
        )
        self.assertEqual(move.product_tmpl_id, template_a)

        found = self.env["stock.move"].search(
            [
                ("id", "=", move.id),
                ("product_tmpl_id", "=", template_a.id),
            ]
        )
        self.assertEqual(found, move)

        move.product_id = product_b
        self.assertEqual(move.product_tmpl_id, template_b)

        found = self.env["stock.move"].search(
            [
                ("id", "=", move.id),
                ("product_tmpl_id", "=", template_b.id),
            ]
        )
        self.assertEqual(found, move)


@tagged("post_install", "-at_install")
class TestCrossModelEdgeCases(TestStockCommon):
    def test_reserved_release_not_dropped_in_multirow_group(self):
        Quant = self.env["stock.quant"]
        loc = self.env["stock.location"].create(
            {
                "name": "H1_loc",
                "usage": "internal",
                "location_id": self.stock_location.id,
            }
        )
        prod = self.env["product.product"].create(
            {"name": "H1_prod", "type": "consu", "is_storable": True}
        )
        t = datetime.datetime(2026, 1, 1)
        q1 = Quant.create(
            {
                "product_id": prod.id,
                "location_id": loc.id,
                "quantity": 5.0,
                "reserved_quantity": 0.0,
                "in_date": t,
            }
        )
        q2 = Quant.create(
            {
                "product_id": prod.id,
                "location_id": loc.id,
                "quantity": 0.0,
                "reserved_quantity": 5.0,
                "in_date": t,
            }
        )
        self.assertEqual(q1.reserved_quantity + q2.reserved_quantity, 5.0)

        Quant._update_reserved_quantity(prod, loc, -5.0)
        self.env.flush_all()

        total = sum(
            Quant.search(
                [("product_id", "=", prod.id), ("location_id", "=", loc.id)]
            ).mapped("reserved_quantity")
        )
        self.assertEqual(total, 0.0, "the release of 5 must bring group reserved to 0")

    def test_deadline_date_counts_two_step_receipt(self):
        company = self.env.company
        company.stock_config_id.horizon_days = 60
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
                {
                    "product_id": prod.id,
                    "location_id": stock_loc.id,
                    "warehouse_id": wh.id,
                    "product_min_qty": 10.0,
                    "product_max_qty": 50.0,
                }
            )
            base = datetime.datetime.combine(today, datetime.time(12))
            m_in = self.env["stock.move"].create(
                {
                    "product_id": prod.id,
                    "product_uom_qty": 20.0,
                    "product_uom_id": prod.uom_id.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": in_dest.id,
                    "location_final_id": in_final.id,
                    "picking_type_id": wh.in_type_id.id,
                    "date": base + datetime.timedelta(days=10),
                }
            )
            m_out = self.env["stock.move"].create(
                {
                    "product_id": prod.id,
                    "product_uom_qty": 20.0,
                    "product_uom_id": prod.uom_id.id,
                    "location_id": stock_loc.id,
                    "location_dest_id": self.customer_location.id,
                    "location_final_id": self.customer_location.id,
                    "picking_type_id": wh.out_type_id.id,
                    "date": base + datetime.timedelta(days=20),
                }
            )
            (m_in | m_out)._action_confirm()
            self.env.flush_all()
            op.invalidate_recordset(["deadline_date"])
            return op.deadline_date

        control = deadline_for(stock_loc, stock_loc)
        two_step = deadline_for(input_loc, stock_loc)
        self.assertFalse(control, "1-step receipt should cover the shortage")
        self.assertEqual(
            two_step,
            control,
            "2-step receipt covers identically; deadline must match the 1-step case",
        )

    def test_button_validate_skips_cancelled_picking(self):
        prod = self.env["product.product"].create(
            {"name": "M2_prod", "type": "consu", "is_storable": True}
        )
        pick = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": prod.id,
                "product_uom_qty": 5.0,
                "product_uom_id": prod.uom_id.id,
                "picking_id": pick.id,
                "location_id": pick.location_id.id,
                "location_dest_id": pick.location_dest_id.id,
            }
        )
        pick.action_confirm()
        pick.action_cancel()
        self.assertEqual(pick.state, "cancel")
        pick.button_validate()

    def test_traceability_get_lines_rejects_foreign_model(self):
        report = self.env["stock.traceability.report"]
        partner = self.env.ref("base.partner_admin")
        res = report.get_lines(line_id=1, model_name="res.partner", model_id=partner.id)
        self.assertEqual(res, [])
        self.assertIn("stock.move.line", report._get_models_allowed_line())
        self.assertNotIn("res.partner", report._get_models_allowed_line())

    def test_qty_available_not_aliased_across_search_locations(self):
        Loc = self.env["stock.location"]
        la = Loc.create(
            {"name": "M6_A", "usage": "internal", "location_id": self.stock_location.id}
        )
        lb = Loc.create(
            {"name": "M6_B", "usage": "internal", "location_id": self.stock_location.id}
        )
        prod = self.env["product.product"].create(
            {"name": "M6_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"].create(
            [
                {"product_id": prod.id, "location_id": la.id, "quantity": 3.0},
                {"product_id": prod.id, "location_id": lb.id, "quantity": 7.0},
            ]
        )
        self.env.flush_all()
        qa = prod.with_context(search_location=la.id).qty_available
        qb = prod.with_context(search_location=lb.id).qty_available
        self.assertEqual(qa, 3.0)
        self.assertEqual(qb, 7.0, "second read must reflect location B, not A's cache")

    def test_scrap_cannot_be_validated_twice(self):
        prod = self.env["product.product"].create(
            {"name": "M7_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, self.stock_location, 10.0
        )
        scrap = self.env["stock.scrap"].create(
            {
                "product_id": prod.id,
                "product_uom_id": prod.uom_id.id,
                "scrap_qty": 3.0,
                "location_id": self.stock_location.id,
            }
        )
        scrap._action_done()
        self.assertEqual(scrap.state, "done")
        first_name = scrap.name
        with self.assertRaises(UserError):
            scrap._action_done()
        self.assertEqual(scrap.name, first_name)

    def test_lot_batch_relocate_each_single_location(self):
        prod = self.env["product.product"].create(
            {"name": "M9_prod", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        loc_a, loc_b, loc_c = self.env["stock.location"].create(
            [
                {
                    "name": f"M9_{n}",
                    "usage": "internal",
                    "location_id": self.stock_location.id,
                }
                for n in ("A", "B", "C")
            ]
        )
        lot1, lot2 = self.env["stock.lot"].create(
            [
                {"name": "M9-L1", "product_id": prod.id},
                {"name": "M9-L2", "product_id": prod.id},
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, loc_a, 5.0, lot_id=lot1
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, loc_b, 5.0, lot_id=lot2
        )
        self.env.flush_all()
        (lot1 | lot2).location_id = loc_c
        self.env.flush_all()
        self.assertEqual(lot1.location_id, loc_c)
        self.assertEqual(lot2.location_id, loc_c)

    def test_serial_prefix_does_not_hijack_foreign_sequence(self):
        foreign = self.env["ir.sequence"].create(
            {
                "name": "Foreign",
                "code": "sale.order",
                "prefix": "ZZHIJACK/",
                "padding": 5,
            }
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
        self.assertIn(
            pkg,
            self.env["stock.package"].search(
                [("contained_quant_ids", "in", quant.ids)]
            ),
        )
        self.assertNotIn(
            pkg,
            self.env["stock.package"].search(
                [("contained_quant_ids", "not in", quant.ids)]
            ),
        )

    def test_reception_assign_rejects_done_out(self):
        report = self.env["report.stock.report_reception"]
        prod = self.env["product.product"].create(
            {"name": "M3_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, self.stock_location, 10.0
        )
        out_pick = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        out_move = self.env["stock.move"].create(
            {
                "product_id": prod.id,
                "product_uom_qty": 5.0,
                "product_uom_id": prod.uom_id.id,
                "picking_id": out_pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        out_pick.action_confirm()
        out_move.quantity = 5.0
        out_move.picked = True
        out_pick.button_validate()
        self.assertEqual(out_move.state, "done")
        in_move = self.env["stock.move"].create(
            {
                "product_id": prod.id,
                "product_uom_qty": 5.0,
                "product_uom_id": prod.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.warehouse_1.in_type_id.id,
            }
        )
        in_move._action_confirm()
        with self.assertRaises(UserError):
            report.action_assign([out_move.id], [5.0], [[in_move.id]])

    def test_date_done_does_not_redate_scrap_moves(self):
        prod = self.env["product.product"].create(
            {"name": "L9_prod", "type": "consu", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(
            prod, self.stock_location, 10.0
        )
        pick = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        normal_move = self.env["stock.move"].create(
            {
                "product_id": prod.id,
                "product_uom_qty": 5.0,
                "product_uom_id": prod.uom_id.id,
                "picking_id": pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        pick.action_confirm()
        normal_move.quantity = 5.0
        normal_move.picked = True
        pick.button_validate()
        self.assertEqual(pick.state, "done")
        old_date = datetime.datetime(2026, 1, 1, 8, 0, 0)
        scrap_move = self.env["stock.move"].create(
            {
                "product_id": prod.id,
                "product_uom_qty": 1.0,
                "product_uom_id": prod.uom_id.id,
                "picking_id": pick.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.scrap_location.id,
                "state": "done",
                "date": old_date,
            }
        )
        self.assertEqual(scrap_move.location_dest_usage, "inventory")
        pick.write({"date_done": datetime.datetime(2026, 5, 5, 12, 0, 0)})
        self.assertEqual(
            scrap_move.date, old_date, "the done scrap move must keep its own date"
        )

    def test_lot_filtered_quant_cache_not_authoritative_for_unseeded_lot(self):
        Quant = self.env["stock.quant"]
        prod = self.env["product.product"].create(
            {"name": "D7_prod", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        lot_a, lot_b = self.env["stock.lot"].create(
            [
                {"name": "D7-A", "product_id": prod.id},
                {"name": "D7-B", "product_id": prod.id},
            ]
        )
        Quant._update_available_quantity(prod, self.stock_location, 5.0, lot_id=lot_a)
        Quant._update_available_quantity(prod, self.stock_location, 7.0, lot_id=lot_b)
        self.env.flush_all()
        cache = Quant._get_quants_by_products_locations(
            prod, self.stock_location, lot_scope=lot_a
        )
        self.assertTrue(cache.is_covering(prod, self.stock_location, lot_a))
        self.assertFalse(
            cache.is_covering(prod, self.stock_location, lot_b),
            "an unseeded lot must not be reported as covered",
        )
        res = Quant.with_context(quants_cache=cache)._gather(
            prod, self.stock_location, lot_id=lot_b, strict=True
        )
        self.assertEqual(sum(res.mapped("quantity")), 7.0)
