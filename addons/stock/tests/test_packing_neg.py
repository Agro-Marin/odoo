from odoo.tests.common import TransactionCase


class TestPackingNeg(TransactionCase):
    def test_packing_neg(self):
        res_partner_2 = self.env["res.partner"].create(
            {
                "name": "Acme Corporation",
                "email": "acme.corportation82@example.com",
            }
        )

        res_partner_4 = self.env["res.partner"].create(
            {
                "name": "Ready Mat",
                "email": "ready.mat28@example.com",
            }
        )

        product_neg = self.env["product.product"].create(
            {
                "name": "Negative product",
                "is_storable": True,
                "list_price": 100.0,
                "standard_price": 70.0,
                "seller_ids": [
                    (
                        0,
                        0,
                        {
                            "delay": 1,
                            "partner_id": res_partner_2.id,
                            "min_qty": 2.0,
                        },
                    )
                ],
                "uom_id": self.ref("uom.product_uom_unit"),
            }
        )

        vals = {
            "name": "Incoming picking (negative product)",
            "partner_id": res_partner_2.id,
            "picking_type_id": self.ref("stock.picking_type_in"),
            "location_id": self.ref("stock.stock_location_suppliers"),
            "location_dest_id": self.ref("stock.stock_location_stock"),
            "move_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product_neg.id,
                        "product_uom_id": product_neg.uom_id.id,
                        "product_uom_qty": 300.00,
                        "location_id": self.ref("stock.stock_location_suppliers"),
                        "location_dest_id": self.ref("stock.stock_location_stock"),
                    },
                )
            ],
            "state": "draft",
        }
        pick_neg = self.env["stock.picking"].create(vals)
        pick_neg._onchange_picking_type()

        pick_neg.action_confirm()
        pick_neg.action_assign()

        lot_a = self.env["stock.lot"].create(
            {"name": "Lot neg", "product_id": product_neg.id}
        )
        package1 = self.env["stock.package"].create({"name": "Palneg 1"})
        package2 = self.env["stock.package"].create({"name": "Palneg 2"})
        package3 = self.env["stock.package"].create({"name": "Palneg 3"})
        pick_neg.move_line_ids[0].write(
            {"result_package_id": package1.id, "quantity": 120}
        )
        self.env["stock.move.line"].create(
            {
                "product_id": product_neg.id,
                "product_uom_id": self.ref("uom.product_uom_unit"),
                "picking_id": pick_neg.id,
                "lot_id": lot_a.id,
                "quantity": 120,
                "result_package_id": package2.id,
                "location_id": self.ref("stock.stock_location_suppliers"),
                "location_dest_id": self.ref("stock.stock_location_stock"),
            }
        )
        self.env["stock.move.line"].create(
            {
                "product_id": product_neg.id,
                "product_uom_id": self.ref("uom.product_uom_unit"),
                "picking_id": pick_neg.id,
                "result_package_id": package3.id,
                "quantity": 60,
                "location_id": self.ref("stock.stock_location_suppliers"),
                "location_dest_id": self.ref("stock.stock_location_stock"),
            }
        )

        pick_neg.move_ids.picked = True
        pick_neg._action_done()

        vals = {
            "name": "outgoing picking (negative product)",
            "partner_id": res_partner_4.id,
            "picking_type_id": self.ref("stock.picking_type_out"),
            "location_id": self.ref("stock.stock_location_stock"),
            "location_dest_id": self.ref("stock.stock_location_customers"),
            "move_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product_neg.id,
                        "product_uom_id": product_neg.uom_id.id,
                        "product_uom_qty": 300.00,
                        "location_id": self.ref("stock.stock_location_stock"),
                        "location_dest_id": self.ref("stock.stock_location_customers"),
                    },
                )
            ],
            "state": "draft",
        }
        delivery_order_neg = self.env["stock.picking"].create(vals)
        delivery_order_neg._onchange_picking_type()

        delivery_order_neg.action_confirm()
        delivery_order_neg.action_assign()

        for rec in delivery_order_neg.move_line_ids:
            if rec.package_id.name == "Palneg 1":
                rec.result_package_id = False
            elif rec.package_id.name == "Palneg 2" and rec.lot_id.name == "Lot neg":
                rec.write(
                    {
                        "quantity": 140,
                        "result_package_id": False,
                    }
                )
            elif rec.package_id.name == "Palneg 3":
                rec.quantity = 10
                rec.result_package_id = False

        delivery_order_neg.move_ids.picked = True
        delivery_order_neg._action_done()

        records = self.env["stock.quant"].search(
            [("product_id", "=", product_neg.id), ("quantity", "!=", "0")]
        )
        pallet_3_stock_qty = 0
        for rec in records:
            if rec.package_id.name == "Palneg 2" and rec.location_id.id == self.ref(
                "stock.stock_location_stock"
            ):
                self.assertTrue(
                    rec.quantity == -20,
                    "Should have -20 pieces in stock on pallet 2. Got "
                    + str(rec.quantity),
                )
                self.assertTrue(
                    rec.lot_id.name == "Lot neg", "It should have kept its Lot"
                )
            elif rec.package_id.name == "Palneg 3" and rec.location_id.id == self.ref(
                "stock.stock_location_stock"
            ):
                pallet_3_stock_qty += rec.quantity
            else:
                self.assertTrue(
                    rec.location_id.id != self.ref("stock.stock_location_stock"),
                    "Unrecognized quant in stock",
                )
        self.assertEqual(
            pallet_3_stock_qty, 50, "Should have 50 pieces in stock on pallet 3"
        )

        vals = {
            "name": "reconciling_delivery",
            "partner_id": res_partner_4.id,
            "picking_type_id": self.ref("stock.picking_type_in"),
            "location_id": self.ref("stock.stock_location_suppliers"),
            "location_dest_id": self.ref("stock.stock_location_stock"),
            "move_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": product_neg.id,
                        "product_uom_id": product_neg.uom_id.id,
                        "product_uom_qty": 20.0,
                        "location_id": self.ref("stock.stock_location_suppliers"),
                        "location_dest_id": self.ref("stock.stock_location_stock"),
                    },
                )
            ],
            "state": "draft",
        }
        delivery_reconcile = self.env["stock.picking"].create(vals)
        delivery_reconcile._onchange_picking_type()

        delivery_reconcile.action_confirm()
        lot = self.env["stock.lot"].search(
            [("product_id", "=", product_neg.id), ("name", "=", "Lot neg")], limit=1
        )
        pack = self.env["stock.package"].search([("name", "=", "Palneg 2")], limit=1)
        delivery_reconcile.move_line_ids[0].write(
            {"lot_id": lot.id, "quantity": 20.0, "result_package_id": pack.id}
        )
        delivery_reconcile.move_ids.picked = True
        delivery_reconcile._action_done()

        neg_quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", product_neg.id),
                ("quantity", "<", 0),
                ("location_id.id", "!=", self.ref("stock.stock_location_suppliers")),
            ]
        )
        self.assertTrue(
            len(neg_quants) == 0, "Negative quants should have been reconciled"
        )
