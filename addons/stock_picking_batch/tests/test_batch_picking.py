from datetime import datetime, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, HttpCase, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import float_round


class TestBatchPicking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type_in = cls.env["ir.model.data"]._xmlid_to_res_id(
            "stock.picking_type_in"
        )
        cls.picking_type_out = cls.env["ir.model.data"]._xmlid_to_res_id(
            "stock.picking_type_out"
        )
        cls.env["stock.picking.type"].browse(
            cls.picking_type_out
        ).reservation_method = "manual"
        cls.productA = cls.env["product.product"].create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )
        cls.productB = cls.env["product.product"].create(
            {
                "name": "Product B",
                "is_storable": True,
            }
        )

        cls.client_1 = cls.env["res.partner"].create({"name": "Client 1"})
        cls.picking_client_1 = cls.env["stock.picking"].create(
            {
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
                "picking_type_id": cls.picking_type_out,
                "partner_id": cls.client_1.id,
                "company_id": cls.env.company.id,
            }
        )

        cls.env["stock.move"].create(
            {
                "product_id": cls.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": cls.productA.uom_id.id,
                "picking_id": cls.picking_client_1.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

        cls.client_2 = cls.env["res.partner"].create({"name": "Client 2"})
        cls.picking_client_2 = cls.env["stock.picking"].create(
            {
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
                "picking_type_id": cls.picking_type_out,
                "partner_id": cls.client_2.id,
                "company_id": cls.env.company.id,
            }
        )

        cls.env["stock.move"].create(
            {
                "product_id": cls.productB.id,
                "product_uom_qty": 10,
                "product_uom_id": cls.productA.uom_id.id,
                "picking_id": cls.picking_client_2.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

        cls.picking_client_3 = cls.env["stock.picking"].create(
            {
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
                "picking_type_id": cls.picking_type_out,
                "company_id": cls.env.company.id,
            }
        )

        cls.env["stock.move"].create(
            {
                "product_id": cls.productB.id,
                "product_uom_qty": 10,
                "product_uom_id": cls.productA.uom_id.id,
                "picking_id": cls.picking_client_3.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

        cls.batch = cls.env["stock.picking.batch"].create(
            {
                "name": "Batch 1",
                "company_id": cls.env.company.id,
                "picking_ids": [
                    (4, cls.picking_client_1.id),
                    (4, cls.picking_client_2.id),
                ],
            }
        )

    def test_batch_date_planned(self):

        now = datetime.now().replace(microsecond=0)
        self.batch.date_planned = now

        picking1_date_planned = now - timedelta(days=2)
        picking2_date_planned = now - timedelta(days=3)
        picking3_date_planned = now - timedelta(days=4)

        self.picking_client_1.date_planned = picking1_date_planned
        self.picking_client_2.date_planned = picking2_date_planned
        self.assertEqual(self.batch.date_planned, self.picking_client_2.date_planned)
        self.assertEqual(self.picking_client_1.date_planned, picking1_date_planned)
        self.assertEqual(self.picking_client_2.date_planned, picking2_date_planned)

        self.picking_client_3.date_planned = picking3_date_planned
        self.batch.write({"picking_ids": [(4, self.picking_client_3.id)]})
        self.assertEqual(self.batch.date_planned, self.picking_client_3.date_planned)

        self.batch.write({"picking_ids": [(3, self.picking_client_3.id)]})
        self.assertEqual(self.batch.date_planned, self.picking_client_2.date_planned)

        self.assertEqual(self.picking_client_1.date_planned, picking1_date_planned)
        self.assertEqual(self.picking_client_2.date_planned, picking2_date_planned)

        self.batch.action_cancel()
        self.assertEqual(len(self.batch.picking_ids), 0)
        self.assertEqual(self.batch.date_planned, False)

    def test_simple_batch_with_manual_quantity(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        self.picking_client_1.move_ids.write({"quantity": 10, "picked": True})
        self.picking_client_2.move_ids.write({"quantity": 10, "picked": True})
        self.batch.action_done()

        self.assertEqual(
            self.picking_client_1.state, "done", "Picking 1 should be done"
        )
        self.assertEqual(
            self.picking_client_2.state, "done", "Picking 2 should be done"
        )

        quant_A = self.env["stock.quant"]._gather(self.productA, self.stock_location)
        quant_B = self.env["stock.quant"]._gather(self.productB, self.stock_location)

        self.assertFalse(sum(quant_A.mapped("quantity")))
        self.assertFalse(sum(quant_B.mapped("quantity")))

        with self.assertRaises(UserError):
            self.batch.unlink()

    def test_simple_batch_with_wizard(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        self.batch.action_done()
        self.assertEqual(
            self.picking_client_1.state, "done", "Picking 1 should be done"
        )
        self.assertEqual(
            self.picking_client_2.state, "done", "Picking 2 should be done"
        )

        quant_A = self.env["stock.quant"]._gather(self.productA, self.stock_location)
        quant_B = self.env["stock.quant"]._gather(self.productB, self.stock_location)

        self.assertFalse(sum(quant_A.mapped("quantity")))
        self.assertFalse(sum(quant_B.mapped("quantity")))

    def test_batch_with_backorder_wizard(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 5.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        self.picking_client_1.move_ids.write({"quantity": 5, "picked": True})
        self.picking_client_2.move_ids.write({"quantity": 10, "picked": True})

        back_order_wizard_dict = self.batch.action_done()
        self.assertTrue(back_order_wizard_dict)
        back_order_wizard = Form.from_action(self.env, back_order_wizard_dict).save()
        self.assertEqual(len(back_order_wizard.pick_ids), 1)
        back_order_wizard.process()

        self.assertEqual(
            self.picking_client_2.state, "done", "Picking 2 should be done"
        )
        self.assertEqual(
            self.picking_client_1.state, "done", "Picking 1 should be done"
        )
        self.assertEqual(
            self.picking_client_1.move_ids.product_uom_qty,
            5,
            "initial demand should be 5 after picking split",
        )
        self.assertTrue(
            self.env["stock.picking"].search(
                [("backorder_id", "=", self.picking_client_1.id)]
            ),
            "no back order created",
        )

        quant_A = self.env["stock.quant"]._gather(self.productA, self.stock_location)
        quant_B = self.env["stock.quant"]._gather(self.productB, self.stock_location)

        self.assertFalse(sum(quant_A.mapped("quantity")))
        self.assertFalse(sum(quant_B.mapped("quantity")))

    def test_batch_with_immediate_transfer_and_backorder_wizard(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 5.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        back_order_wizard_dict = self.batch.action_done()
        self.assertTrue(back_order_wizard_dict)
        back_order_wizard = Form.from_action(self.env, back_order_wizard_dict).save()
        self.assertEqual(len(back_order_wizard.pick_ids), 1)
        back_order_wizard.process()

        self.assertEqual(
            self.picking_client_1.state, "done", "Picking 1 should be done"
        )
        self.assertEqual(
            self.picking_client_1.move_ids.product_uom_qty,
            5,
            "initial demand should be 5 after picking split",
        )
        self.assertTrue(
            self.env["stock.picking"].search(
                [("backorder_id", "=", self.picking_client_1.id)]
            ),
            "no back order created",
        )

        quant_A = self.env["stock.quant"]._gather(self.productA, self.stock_location)
        quant_B = self.env["stock.quant"]._gather(self.productB, self.stock_location)

        self.assertFalse(sum(quant_A.mapped("quantity")))
        self.assertFalse(sum(quant_B.mapped("quantity")))

    def test_batch_with_immediate_transfer_and_backorder_wizard_with_manual_operations(
        self,
    ):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 5.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        self.picking_client_1.move_ids.write({"quantity": 5, "picked": True})
        back_order_wizard_dict = self.batch.action_done()
        self.assertTrue(back_order_wizard_dict)
        self.assertEqual(
            back_order_wizard_dict.get("res_model"), "stock.backorder.confirmation"
        )
        back_order_wizard = Form.from_action(self.env, back_order_wizard_dict).save()
        self.assertEqual(len(back_order_wizard.pick_ids), 1)
        back_order_wizard.process()

        self.assertEqual(
            self.picking_client_1.state, "done", "Picking 1 should be done"
        )
        self.assertEqual(
            self.picking_client_1.move_ids.product_uom_qty,
            5,
            "initial demand should be 5 after picking split",
        )
        self.assertFalse(self.picking_client_2.batch_id)

    def test_put_in_pack(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.assertEqual(
            self.picking_client_1.state, "confirmed", "Picking 1 should be confirmed"
        )
        self.assertEqual(
            self.picking_client_2.state, "confirmed", "Picking 2 should be confirmed"
        )
        self.batch.action_assign()
        self.assertEqual(
            self.picking_client_1.state, "assigned", "Picking 1 should be ready"
        )
        self.assertEqual(
            self.picking_client_2.state, "assigned", "Picking 2 should be ready"
        )

        self.batch.move_line_ids.quantity = 5
        self.batch.move_line_ids[0].location_dest_id = self.stock_location.id
        self.batch.move_ids.picked = True
        wizard_values = self.batch.action_put_in_pack()
        wizard = self.env[(wizard_values.get("res_model"))].browse(
            wizard_values.get("res_id")
        )
        wizard.location_dest_id = self.customer_location.id
        package = wizard.action_done()

        self.assertTrue(package)
        done_qty_move_lines = self.batch.move_line_ids.filtered(
            lambda ml: ml.quantity == 5
        )
        self.assertEqual(done_qty_move_lines[0].result_package_id.id, package.id)
        self.assertEqual(done_qty_move_lines[1].result_package_id.id, package.id)

        back_order_wizard_dict = self.batch.action_done()
        self.assertTrue(back_order_wizard_dict)
        back_order_wizard = Form.from_action(self.env, back_order_wizard_dict).save()
        self.assertEqual(len(back_order_wizard.pick_ids), 2)
        back_order_wizard.process()

        self.assertEqual(package.location_id.id, self.customer_location.id)

    def test_put_in_pack_within_single_picking(self):

        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 10.0
        )

        self.batch.action_confirm()
        self.batch.action_assign()
        self.batch.move_line_ids.quantity = 5
        package = self.picking_client_1.action_put_in_pack()
        self.assertEqual(self.picking_client_1.move_line_ids.result_package_id, package)
        self.assertFalse(
            self.picking_client_2.move_line_ids.result_package_id,
            "Other picking in batch shouldn't have been put in a package",
        )

    def test_auto_batch(self):
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        type_special_out = self.env["stock.picking.type"].create(
            {
                "name": "Special Delivery",
                "sequence_code": "SPECOUT",
                "code": "outgoing",
                "company_id": self.env.company.id,
                "warehouse_id": warehouse.id,
                "auto_batch": True,
                "batch_group_by_partner": True,
            }
        )
        partner_1 = self.env["res.partner"].create({"name": "Partner 1"})
        partner_2 = self.env["res.partner"].create({"name": "Partner 2"})
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 20
        )

        picking_out_1 = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": type_special_out.id,
                "company_id": self.env.company.id,
                "partner_id": partner_1.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_out_1.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        picking_out_2 = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": type_special_out.id,
                "company_id": self.env.company.id,
                "partner_id": partner_2.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": picking_out_2.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        picking_out_3 = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": type_special_out.id,
                "company_id": self.env.company.id,
                "partner_id": partner_1.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 10,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": picking_out_3.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )

        all_pickings = picking_out_1 | picking_out_2 | picking_out_3
        self.assertFalse(all_pickings.batch_id)

        all_pickings.action_confirm()
        self.assertTrue(picking_out_1.batch_id)
        self.assertTrue(picking_out_3.batch_id)
        self.assertEqual(picking_out_1.batch_id.id, picking_out_3.batch_id.id)
        self.assertTrue(picking_out_2.batch_id)
        self.assertTrue(
            picking_out_2.user_id == picking_out_2.batch_id.user_id == self.env.user
        )
        self.assertNotEqual(picking_out_2.batch_id.id, picking_out_1.batch_id.id)
        picking_out_1.move_ids.write({"quantity": 10, "picked": True})
        picking_out_1.button_validate()
        self.assertFalse(picking_out_1.batch_id)
        self.assertEqual(len(picking_out_3.batch_id.picking_ids), 1)

    def test_auto_batch_02(self):
        warehouse_1 = self.env["stock.warehouse"].create(
            {
                "name": "WH 1",
                "code": "WH1",
                "company_id": self.env.company.id,
            }
        )
        warehouse_2 = self.env["stock.warehouse"].create(
            {
                "name": "WH 2",
                "code": "WH2",
                "company_id": warehouse_1.company_id.id,
                "resupply_wh_ids": [(6, 0, [warehouse_1.id])],
                "reception_steps": "three_steps",
            }
        )
        warehouse_1.out_type_id.write(
            {
                "reservation_method": "at_confirm",
                "auto_batch": True,
                "batch_group_by_src_loc": True,
            }
        )
        (warehouse_2.qc_type_id | warehouse_2.store_type_id).write(
            {
                "auto_batch": True,
                "batch_group_by_dest_loc": True,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productA, warehouse_1.lot_stock_id, 10
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, warehouse_1.lot_stock_id, 10
        )
        op1 = self.env["stock.warehouse.orderpoint"].create(
            {
                "name": "Product A",
                "location_id": warehouse_2.lot_stock_id.id,
                "product_id": self.productA.id,
                "product_min_qty": 1,
                "product_max_qty": 1,
                "route_id": warehouse_2.resupply_route_ids[0].id,
            }
        )
        op2 = self.env["stock.warehouse.orderpoint"].create(
            {
                "name": "Product B",
                "location_id": warehouse_2.lot_stock_id.id,
                "product_id": self.productB.id,
                "product_min_qty": 1,
                "product_max_qty": 1,
                "route_id": warehouse_2.resupply_route_ids[0].id,
            }
        )
        self.productA.route_ids = warehouse_2.resupply_route_ids
        self.productB.route_ids = warehouse_2.resupply_route_ids
        (op1 | op2)._procure_orderpoint_confirm()
        pAbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_1.id),
                    ("product_id", "=", self.productA.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        pBbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_1.id),
                    ("product_id", "=", self.productB.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(len(pAbatch), 1)
        self.assertEqual(pAbatch, pBbatch)

        pAbatch.move_ids.write({"quantity": 1, "picked": True})
        pAbatch.action_done()
        done_batches = pAbatch
        pAbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_2.id),
                    ("product_id", "=", self.productA.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(len(pAbatch), 1)
        pBbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_2.id),
                    ("product_id", "=", self.productB.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(pAbatch, pBbatch)

        current_batch = pAbatch - done_batches
        current_batch.move_ids.write({"quantity": 1, "picked": True})
        current_batch.action_done()
        done_batches += pAbatch
        pAbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_2.id),
                    ("picking_code", "=", "internal"),
                    ("product_id", "=", self.productA.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(len(pAbatch), 1)
        pBbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("warehouse_id", "=", warehouse_2.id),
                    ("picking_code", "=", "internal"),
                    ("product_id", "=", self.productB.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(pAbatch, pBbatch)

        current_batch = pAbatch - done_batches
        current_batch.move_ids.write({"quantity": 1, "picked": True})
        current_batch.action_done()
        pAbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("location_dest_id", "=", warehouse_2.lot_stock_id.id),
                    ("picking_code", "=", "internal"),
                    ("product_id", "=", self.productA.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(len(pAbatch), 1)
        pBbatch = (
            self.env["stock.move"]
            .search(
                [
                    ("location_dest_id", "=", warehouse_2.lot_stock_id.id),
                    ("picking_code", "=", "internal"),
                    ("product_id", "=", self.productB.id),
                    ("state", "in", ["done", "assigned"]),
                ]
            )
            .picking_id.batch_id
        )
        self.assertEqual(pAbatch, pBbatch)

    def test_auto_batch_3(self):
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        warehouse.out_type_id.write(
            {
                "auto_batch": True,
                "batch_group_by_partner": True,
            }
        )
        partner = self.env["res.partner"].create({"name": "Lovely product"})
        delivery = self.env["stock.picking"].create(
            {
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": warehouse.out_type_id.id,
                "partner_id": partner.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 10,
                            "product_uom_id": self.productA.uom_id.id,
                            "location_id": warehouse.lot_stock_id.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        delivery.action_confirm()

        self.assertRecordValues(
            delivery,
            [
                {"state": "confirmed", "batch_id": False},
            ],
        )
        delivery.move_ids.quantity = 1
        self.assertEqual(delivery.state, "assigned")
        self.assertTrue(delivery.batch_id)

    def test_remove_all_transfers_from_confirmed_batch(self):
        self.batch.action_confirm()
        self.assertEqual(
            self.batch.state, "in_progress", "Batch Transfers should be in progress."
        )
        self.batch.write({"picking_ids": [[5, 0, 0]]})
        self.assertEqual(
            self.batch.state,
            "cancel",
            "Batch Transfers should be cancelled when there are no transfers.",
        )

    def test_remove_all_transfers_from_confirmed_batch_multi_record_write(self):
        other_batch = self.env["stock.picking.batch"].create(
            {
                "name": "Batch 2",
                "company_id": self.env.company.id,
                "picking_ids": [(4, self.picking_client_3.id)],
            }
        )
        self.batch.action_confirm()
        other_batch.action_confirm()

        (self.picking_client_1 | self.picking_client_2).batch_id = False
        self.assertFalse(self.batch.picking_ids)
        self.assertEqual(
            self.batch.state,
            "cancel",
            "An in-progress batch emptied from the picking side is cancelled.",
        )
        self.assertEqual(
            other_batch.state,
            "in_progress",
            "Batch that still has pickings should not be affected.",
        )

    def test_backorder_on_one_picking(self):
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 10.0
        )
        self.env["stock.quant"]._update_available_quantity(
            self.productB, self.stock_location, 8.0
        )

        self.batch.action_confirm()

        self.batch.action_assign()
        self.picking_client_1.move_ids.write({"quantity": 10, "picked": True})
        self.picking_client_2.move_ids.write({"quantity": 7, "picked": True})

        Form.from_action(
            self.env, self.batch.action_done()
        ).save().action_cancel_backorder()

        self.assertEqual(self.picking_client_1.state, "done")
        self.assertEqual(self.picking_client_2.state, "done")
        self.assertEqual(
            self.batch.picking_ids, self.picking_client_1 | self.picking_client_2
        )
        self.assertRecordValues(
            self.batch.move_ids.sorted("id"),
            [
                {
                    "product_id": self.productA.id,
                    "product_uom_qty": 10.0,
                    "quantity": 10.0,
                    "state": "done",
                },
                {
                    "product_id": self.productB.id,
                    "product_uom_qty": 10.0,
                    "quantity": 7.0,
                    "state": "done",
                },
            ],
        )

    def test_process_picking_with_reception_report(self):
        self.env.user.group_ids = [(4, self.ref("stock.group_reception_report"))]
        self.env["stock.picking.type"].browse(self.picking_type_in).write(
            {
                "auto_show_reception_report": True,
                "auto_batch": True,
                "batch_group_by_partner": True,
            }
        )

        partner = self.env["res.partner"].create({"name": "Super Partner"})

        pickings = self.env["stock.picking"].create(
            [
                {
                    "partner_id": partner_id,
                    "picking_type_id": type_id,
                    "location_id": from_loc.id,
                    "location_dest_id": to_loc.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": product.id,
                                "product_uom_id": product.uom_id.id,
                                "product_uom_qty": 1,
                                "location_id": from_loc.id,
                                "location_dest_id": to_loc.id,
                            },
                        )
                    ],
                }
                for partner_id, product, type_id, from_loc, to_loc in [
                    (
                        False,
                        self.productA,
                        self.picking_type_out,
                        self.stock_location,
                        self.customer_location,
                    ),
                    (
                        partner.id,
                        self.productA,
                        self.picking_type_in,
                        self.supplier_location,
                        self.stock_location,
                    ),
                    (
                        partner.id,
                        self.productB,
                        self.picking_type_in,
                        self.supplier_location,
                        self.stock_location,
                    ),
                ]
            ]
        )
        pickings.action_confirm()
        _delivery, receipt01, receipt02 = pickings

        batch = receipt01.batch_id
        self.assertTrue(batch)
        self.assertEqual(batch.picking_ids, receipt01 | receipt02)

        receipt01.move_ids.quantity = 0.75
        res = Form.from_action(self.env, receipt01.button_validate()).save().process()
        self.assertEqual(receipt01.state, "done")
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "report.stock.report_reception")

        backorder = receipt01.backorder_ids
        self.assertTrue(backorder)
        self.assertEqual(batch.picking_ids, receipt02 | backorder)

        receipt03 = self.env["stock.picking"].create(
            {
                "partner_id": partner.id,
                "picking_type_id": self.picking_type_in,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.productA.id,
                            "product_uom_id": self.productA.uom_id.id,
                            "product_uom_qty": 1,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        },
                    )
                ],
            }
        )
        receipt03.action_confirm()
        self.assertEqual(batch.picking_ids, backorder | receipt02 | receipt03)

    def test_batch_merge(self):
        descriptions = ["Great batch", "Amazing batch", "Without scheduled date batch"]
        pickings = [self.picking_client_1, self.picking_client_2, self.picking_client_3]

        batches = self.env["stock.picking.batch"].create(
            [
                {
                    "company_id": self.env.company.id,
                    "picking_ids": [Command.link(picking.id)],
                    "description": description,
                    "user_id": self.env.user.id,
                }
                for description, picking in zip(descriptions, pickings, strict=True)
            ]
        )
        batch_1, batch_2, batch_3 = batches

        batch_1.action_confirm()
        with self.assertRaises(UserError):
            (batch_1 | batch_2).action_merge()
        batch_2.action_confirm()
        batch_3.action_confirm()
        batch_3.date_planned = False

        with self.assertRaises(UserError):
            batch_1.action_merge()

        early_date = fields.Datetime.now() - timedelta(days=1)
        batch_2.date_planned = early_date

        (batch_1 | batch_2 | batch_3).action_merge()
        self.assertEqual(
            batch_1.picking_ids,
            self.picking_client_1 | self.picking_client_2 | self.picking_client_3,
        )
        self.assertEqual(
            batch_1.description,
            "Amazing batch",
            "The description should be the one of the earliest batch",
        )
        self.assertEqual(batch_1.date_planned, early_date)


@tagged("-at_install", "post_install")
class TestBatchPicking02(TransactionCase):
    def setUp(self):
        super().setUp()
        self.stock_location = self.env.ref("stock.stock_location_stock")
        if not self.stock_location.child_ids:
            self.stock_location.create(
                [
                    {
                        "name": "Shelf 1",
                        "location_id": self.stock_location.id,
                    },
                    {
                        "name": "Shelf 2",
                        "location_id": self.stock_location.id,
                    },
                ]
            )
        self.picking_type_internal = self.env.ref("stock.picking_type_internal")
        self.productA = self.env["product.product"].create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )
        self.productB = self.env["product.product"].create(
            {
                "name": "Product B",
                "is_storable": True,
            }
        )
        self.package_type = self.env["stock.package.type"].create(
            {
                "name": "Big box",
                "base_weight": 10,
                "packaging_length": 500,
                "width": 500,
                "height": 500,
            }
        )

    def test_same_package_several_pickings(self):
        package = self.env["stock.package"].create(
            {
                "name": "superpackage",
                "package_type_id": self.package_type.id,
            }
        )
        self.productA.weight = 10
        self.productB.weight = 15

        loc1, loc2 = self.stock_location.child_ids
        self.env["stock.quant"]._update_available_quantity(
            self.productA, loc1, 10, package_id=package
        )
        self.env["stock.quant"]._update_available_quantity(self.productB, loc1, 10)

        pickings = self.env["stock.picking"].create(
            [
                {
                    "location_id": loc1.id,
                    "location_dest_id": loc2.id,
                    "picking_type_id": self.picking_type_internal.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "location_id": loc1.id,
                                "location_dest_id": loc2.id,
                                "product_id": self.productA.id,
                                "product_uom_id": self.productA.uom_id.id,
                                "product_uom_qty": qty,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "location_id": loc1.id,
                                "location_dest_id": loc2.id,
                                "product_id": self.productB.id,
                                "product_uom_id": self.productB.uom_id.id,
                                "product_uom_qty": qty,
                            },
                        ),
                    ],
                }
                for qty in (3, 7)
            ]
        )
        pickings.action_confirm()
        pickings.action_assign()

        batch_form = Form(self.env["stock.picking.batch"])
        batch_form.picking_ids.add(pickings[0])
        batch_form.picking_ids.add(pickings[1])
        batch = batch_form.save()
        batch.action_confirm()

        pickings.move_ids.picked = True
        pickings.move_line_ids.filtered(
            lambda l: l.product_id == self.productA
        ).result_package_id = package

        batch.action_done()
        self.assertEqual(batch.estimated_shipping_weight, 10 + 10 * 10 + 10 * 15)
        precision = self.env["decimal.precision"].get_precision("Product Unit")
        volume = float_round((500 * 500 * 500) / 1000**3, precision_digits=precision)
        self.assertEqual(batch.estimated_shipping_volume, volume)
        self.assertRecordValues(
            pickings.move_ids,
            [
                {"state": "done", "quantity": 3},
                {"state": "done", "quantity": 3},
                {"state": "done", "quantity": 7},
                {"state": "done", "quantity": 7},
            ],
        )
        self.assertEqual(pickings.move_line_ids.result_package_id, package)

    def test_batch_validation_without_backorder(self):
        loc1, loc2 = self.stock_location.child_ids
        self.env["stock.quant"]._update_available_quantity(self.productA, loc1, 10)
        self.env["stock.quant"]._update_available_quantity(self.productB, loc1, 10)
        picking_1 = self.env["stock.picking"].create(
            {
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
                "picking_type_id": self.picking_type_internal.id,
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 1,
                "product_uom_id": self.productA.uom_id.id,
                "picking_id": picking_1.id,
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
            }
        )

        picking_2 = self.env["stock.picking"].create(
            {
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
                "picking_type_id": self.picking_type_internal.id,
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 5,
                "product_uom_id": self.productB.uom_id.id,
                "picking_id": picking_2.id,
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
            }
        )
        (picking_1 | picking_2).action_confirm()
        (picking_1 | picking_2).action_assign()
        picking_2.move_ids.move_line_ids.write({"quantity": 1})
        picking_2.move_ids.picked = True

        batch = self.env["stock.picking.batch"].create(
            {
                "name": "Batch 1",
                "company_id": self.env.company.id,
                "picking_ids": [(4, picking_1.id), (4, picking_2.id)],
            }
        )
        batch.action_confirm()
        self.assertFalse((picking_1 | picking_2).user_id.id)
        batch.user_id = self.env.user
        self.assertEqual((picking_1 | picking_2).user_id, self.env.user)
        batch.user_id = False
        self.assertFalse((picking_1 | picking_2).user_id.id)
        action = batch.action_done()
        self.assertEqual(batch.picking_ids, picking_1 | picking_2)
        Form.from_action(self.env, action).save().action_cancel_backorder()
        self.assertEqual(batch.state, "done")
        self.assertEqual(batch.picking_ids, picking_2)

    def test_backorder_batching(self):
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse test",
                "code": "WHTEST",
                "company_id": self.env.company.id,
            }
        )
        warehouse.in_type_id.auto_batch = True
        warehouse.in_type_id.batch_group_by_partner = True
        productA, productB = self.productA, self.productB
        partner = self.env["res.partner"].create({"name": "Mr. Belougat"})
        pickings = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": warehouse.in_type_id.id,
                    "company_id": self.env.company.id,
                    "partner_id": partner.id,
                },
                {
                    "picking_type_id": warehouse.in_type_id.id,
                    "company_id": self.env.company.id,
                    "partner_id": partner.id,
                },
            ]
        )
        picking_1, picking_2 = pickings
        self.env["stock.move"].create(
            [
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": picking_1.id,
                    "location_id": picking_1.location_id.id,
                    "location_dest_id": picking_1.location_dest_id.id,
                },
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": picking_2.id,
                    "location_id": picking_2.location_id.id,
                    "location_dest_id": picking_2.location_dest_id.id,
                },
                {
                    "product_id": productB.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productB.uom_id.id,
                    "picking_id": picking_2.id,
                    "location_id": picking_2.location_id.id,
                    "location_dest_id": picking_2.location_dest_id.id,
                },
            ]
        )
        pickings.action_confirm()
        batch = pickings.batch_id
        self.assertEqual(batch.picking_ids, picking_1 | picking_2)
        picking_2.move_ids.filtered(lambda m: m.product_id == productA).quantity = 0.0
        Form.from_action(self.env, picking_2.button_validate()).save().process()
        self.assertEqual(picking_2.state, "done")
        self.assertFalse(picking_2 in batch.picking_ids)
        backorder = batch.picking_ids - picking_1
        self.assertTrue(backorder)
        self.assertRecordValues(
            backorder.move_ids, [{"product_id": productA.id, "quantity": 1.0}]
        )

    def test_backorder_batching_2(self):
        warehouse = self.env.ref("stock.warehouse0")
        productA, productB = self.productA, self.productB
        partner = self.env["res.partner"].create({"name": "Mr. Belougat"})

        pickings = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": warehouse.in_type_id.id,
                    "company_id": self.env.company.id,
                    "partner_id": partner.id,
                }
                for i in range(3)
            ]
        )
        self.env["stock.move"].create(
            [
                {
                    "product_id": productA.id,
                    "product_uom_qty": 4.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[0].id,
                    "location_id": pickings[0].location_id.id,
                    "location_dest_id": pickings[0].location_dest_id.id,
                },
                {
                    "product_id": productB.id,
                    "product_uom_qty": 4.0,
                    "product_uom_id": productB.uom_id.id,
                    "picking_id": pickings[1].id,
                    "location_id": pickings[1].location_id.id,
                    "location_dest_id": pickings[1].location_dest_id.id,
                },
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[2].id,
                    "location_id": pickings[2].location_id.id,
                    "location_dest_id": pickings[2].location_dest_id.id,
                },
            ]
        )
        pickings.action_confirm()
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [
                    Command.link(pickings[0].id),
                    Command.link(pickings[1].id),
                    Command.link(pickings[2].id),
                ],
                "picking_type_id": warehouse.in_type_id.id,
            }
        )
        pickings.move_ids.quantity = 1.0
        batch.action_confirm()
        Form.from_action(self.env, batch.action_done()).save().process()
        self.assertEqual(batch.state, "done")
        self.assertEqual(batch.picking_ids.mapped("state"), ["done", "done", "done"])
        bo_1 = pickings[0].backorder_ids
        bo_2 = pickings[1].backorder_ids
        self.assertTrue(bo_1 and bo_2)
        backorders = bo_1 | bo_2
        self.assertEqual(pickings.backorder_ids, backorders)
        self.assertEqual(backorders.move_ids.mapped("product_qty"), [3.0, 3.0])

        bo_batch = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [Command.link(bo_1.id), Command.link(bo_2.id)],
                "picking_type_id": warehouse.in_type_id.id,
            }
        )
        backorders.action_confirm()
        backorders.move_ids.quantity = 1.0
        bo_batch.action_confirm()
        Form.from_action(self.env, bo_batch.action_done()).save().process()
        self.assertEqual(bo_batch.state, "done")
        self.assertEqual(bo_batch.picking_ids.mapped("state"), ["done", "done"])
        bo_3 = bo_batch.picking_ids[0].backorder_ids
        bo_4 = bo_batch.picking_ids[1].backorder_ids
        self.assertTrue(bo_3 and bo_4)
        backorders_2 = bo_3 | bo_4
        self.assertEqual(bo_batch.picking_ids.backorder_ids, backorders_2)
        self.assertEqual(backorders_2.move_ids.mapped("product_qty"), [2.0, 2.0])

        bo_batch_2 = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [Command.link(bo_3.id), Command.link(bo_4.id)],
                "picking_type_id": warehouse.in_type_id.id,
            }
        )
        backorders_2.action_confirm()
        bo_batch_2.action_confirm()
        bo_batch_2.action_done()
        self.assertEqual(bo_batch_2.state, "done")
        self.assertEqual(bo_batch_2.picking_ids.mapped("state"), ["done", "done"])
        self.assertRecordValues(
            bo_batch_2.move_ids,
            [
                {"quantity": 2.0, "picked": True},
                {"quantity": 2.0, "picked": True},
            ],
        )

    def test_backorder_batching_3(self):
        warehouse = self.env.ref("stock.warehouse0")
        warehouse.int_type_id.write(
            {
                "auto_batch": True,
                "batch_group_by_destination": True,
            }
        )
        productA, productB = self.productA, self.productB
        partner = self.env["res.partner"].create({"name": "Mr. Belougat"})

        pickings = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": warehouse.int_type_id.id,
                    "company_id": self.env.company.id,
                    "partner_id": partner.id,
                }
                for _ in range(2)
            ]
        )
        self.env["stock.move"].create(
            [
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[0].id,
                    "location_id": pickings[0].location_id.id,
                    "location_dest_id": pickings[0].location_dest_id.id,
                },
                {
                    "product_id": productB.id,
                    "product_uom_qty": 4.0,
                    "product_uom_id": productB.uom_id.id,
                    "picking_id": pickings[0].id,
                    "location_id": pickings[0].location_id.id,
                    "location_dest_id": pickings[0].location_dest_id.id,
                },
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[1].id,
                    "location_id": pickings[1].location_id.id,
                    "location_dest_id": pickings[1].location_dest_id.id,
                },
            ]
        )
        pickings.action_confirm()
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [
                    Command.link(pickings[0].id),
                    Command.link(pickings[1].id),
                ],
                "picking_type_id": warehouse.int_type_id.id,
            }
        )
        batch.action_confirm()
        pickings.move_ids.filtered(lambda m: m.product_id == productA).quantity = 1.0
        moveB = pickings.move_ids.filtered(lambda m: m.product_id == productB)
        moveB.quantity = 4.0
        moveB.picked = True
        batch.with_context(skip_backorder=True).action_done()
        self.assertEqual(batch.picking_ids, pickings[0])
        self.assertEqual(batch.state, "done")
        self.assertTrue(pickings[1].batch_id)

    def test_backorder_batching_4(self):
        warehouse = self.env.ref("stock.warehouse0")
        warehouse.int_type_id.auto_batch = False
        productA, productB = self.productA, self.productB
        partner = self.env["res.partner"].create({"name": "Mr. Belougat"})

        pickings = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": warehouse.int_type_id.id,
                    "company_id": self.env.company.id,
                    "partner_id": partner.id,
                }
                for _ in range(2)
            ]
        )
        self.env["stock.move"].create(
            [
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[0].id,
                    "location_id": pickings[0].location_id.id,
                    "location_dest_id": pickings[0].location_dest_id.id,
                },
                {
                    "product_id": productB.id,
                    "product_uom_qty": 4.0,
                    "product_uom_id": productB.uom_id.id,
                    "picking_id": pickings[0].id,
                    "location_id": pickings[0].location_id.id,
                    "location_dest_id": pickings[0].location_dest_id.id,
                },
                {
                    "product_id": productA.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": productA.uom_id.id,
                    "picking_id": pickings[1].id,
                    "location_id": pickings[1].location_id.id,
                    "location_dest_id": pickings[1].location_dest_id.id,
                },
            ]
        )
        pickings.action_confirm()
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_ids": [
                    Command.link(pickings[0].id),
                    Command.link(pickings[1].id),
                ],
                "picking_type_id": warehouse.int_type_id.id,
            }
        )
        batch.action_confirm()
        pickings.move_ids.filtered(lambda m: m.product_id == productA).quantity = 1.0
        moveB = pickings.move_ids.filtered(lambda m: m.product_id == productB)
        moveB.quantity = 4.0
        moveB.picked = True
        batch.with_context(skip_backorder=True).action_done()
        self.assertEqual(batch.picking_ids, pickings[0])
        self.assertEqual(batch.state, "done")
        self.assertFalse(pickings[1].batch_id)


@tagged("post_install", "-at_install")
class TestBatchPickingSynchronization(HttpCase):
    def test_stock_picking_batch_sm_to_sml_synchronization(self):

        self.env["res.config.settings"].create(
            {"group_stock_multi_locations": True}
        ).execute()
        location = self.env.ref("stock.stock_location_stock")
        loc1, loc2 = self.env["stock.location"].create(
            [
                {
                    "name": "Shelf A",
                    "location_id": location.id,
                },
                {
                    "name": "Shelf B",
                    "location_id": location.id,
                },
            ]
        )

        productA = self.env["product.product"].create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )

        picking_type_internal = self.env.ref("stock.picking_type_internal")
        self.env["stock.quant"]._update_available_quantity(productA, loc1, 50)
        picking_1 = self.env["stock.picking"].create(
            {
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
                "picking_type_id": picking_type_internal.id,
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": productA.id,
                "product_uom_qty": 1,
                "product_uom_id": productA.uom_id.id,
                "picking_id": picking_1.id,
                "location_id": loc1.id,
                "location_dest_id": loc2.id,
            }
        )
        picking_1.action_confirm()
        picking_1.action_assign()
        picking_1.move_ids.move_line_ids.write({"quantity": 1})
        picking_1.move_ids.picked = True

        batch = self.env["stock.picking.batch"].create(
            {
                "name": "Batch 1",
                "company_id": self.env.company.id,
                "picking_ids": [(4, picking_1.id)],
            }
        )

        action_id = self.env.ref("stock_picking_batch.stock_picking_batch_menu").action
        url = f"/odoo/action-{action_id.id}/{batch.id}"
        self.start_tour(
            url,
            "test_stock_picking_batch_sm_to_sml_synchronization",
            login="admin",
            timeout=100,
        )
        self.assertEqual(batch.picking_ids.move_ids.quantity, 7)
        self.assertEqual(batch.picking_ids.move_ids.move_line_ids.quantity, 7)

    def test_add_pickings_from_the_wave_form(self):
        productA = self.env["product.product"].create(
            {"name": "Product A", "is_storable": True}
        )
        stock_location = self.env.ref("stock.stock_location_stock")
        picking_type_out = self.env.ref("stock.picking_type_out")
        self.env["stock.quant"]._update_available_quantity(productA, stock_location, 50)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type_out.id,
                "location_id": stock_location.id,
                "location_dest_id": picking_type_out.default_location_dest_id.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": productA.id,
                            "product_uom_qty": 5,
                            "location_id": stock_location.id,
                            "location_dest_id": (
                                picking_type_out.default_location_dest_id.id
                            ),
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        wave = self.env["stock.picking.batch"].create(
            {"is_wave": True, "picking_type_id": picking_type_out.id}
        )
        self.start_tour(
            f"/odoo/action-stock_picking_batch.action_picking_tree_wave/{wave.id}",
            "test_stock_picking_batch_add_pickings_from_wave_form",
            login="admin",
            timeout=100,
        )
        self.assertEqual(wave.picking_ids, picking)
        self.assertEqual(wave.state, "in_progress")
