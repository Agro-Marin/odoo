from odoo.addons.stock.tests.common import TestStockCommon


class TestReplenishment(TestStockCommon):
    def test_effective_route(self):
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.productA.id,
                "product_min_qty": 2,
                "product_max_qty": 4,
            }
        )
        self.assertFalse(orderpoint.effective_route_id)

        manufacture = self.env["stock.route"].create(
            {
                "name": "Manufacture",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Manufacture",
                            "location_dest_id": self.stock_location.id,
                            "action": "manufacture",
                            "picking_type_id": self.picking_type_in.id,
                        },
                    ),
                ],
            }
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.productA.product_tmpl_id.id,
                "product_qty": 1,
            }
        )
        buy = self.env["stock.route"].create(
            {
                "name": "Buy",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Buy",
                            "location_dest_id": self.stock_location.id,
                            "action": "buy",
                            "picking_type_id": self.picking_type_in.id,
                        },
                    ),
                ],
            }
        )
        self.env["product.supplierinfo"].create(
            {
                "product_id": self.productA.id,
                "partner_id": self.partner_1.id,
                "min_qty": 10,
                "price": 50,
            }
        )

        self.productA.write(
            {
                "route_ids": [(4, manufacture.id)],
            }
        )
        self.env.invalidate_all()
        self.assertEqual(orderpoint.effective_route_id, manufacture)
        self.assertEqual(orderpoint.effective_bom_id, bom)
        self.assertFalse(orderpoint.effective_vendor_id)

        self.productA.write(
            {
                "route_ids": [(4, buy.id)],
            }
        )
        self.env.invalidate_all()
        self.assertEqual(orderpoint.effective_route_id, manufacture)
        self.assertEqual(orderpoint.effective_bom_id, bom)
        self.assertFalse(orderpoint.effective_vendor_id)

        orderpoint.route_id = buy
        self.env.invalidate_all()
        self.assertEqual(orderpoint.effective_route_id, buy)
        self.assertEqual(orderpoint.route_id, buy)
        self.assertEqual(orderpoint.effective_vendor_id, self.partner_1)
        self.assertFalse(orderpoint.effective_bom_id)

        orderpoint.route_id = False

        self.productA.write(
            {
                "route_ids": [(3, manufacture.id)],
            }
        )
        self.env.invalidate_all()
        self.assertEqual(orderpoint.effective_route_id, buy)
        self.assertFalse(orderpoint.route_id)
        self.assertEqual(orderpoint.effective_vendor_id, self.partner_1)
        self.assertFalse(orderpoint.effective_bom_id)

    def test_replenishment_wizard_warehouse_routes(self):
        def create_replenish_wizard(warehouse, product):
            return self.env["product.replenish"].create(
                {
                    "product_id": product.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_uom_id": product.uom_id.id,
                    "quantity": 1,
                    "warehouse_id": warehouse.id,
                }
            )

        self.warehouse_1.write(
            {
                "buy_to_resupply": True,
                "manufacture_to_resupply": True,
            }
        )
        manufacture_route = self.warehouse_1.route_ids.filtered(
            lambda r: any(rule.action == "manufacture" for rule in r.rule_ids)
        )
        buy_route = self.warehouse_1.route_ids.filtered(
            lambda r: any(rule.action == "buy" for rule in r.rule_ids)
        )
        self.productA.route_ids = False

        self.assertRecordValues(
            self.productA,
            [
                {
                    "route_ids": self.env["stock.route"],
                    "seller_ids": self.env["product.supplierinfo"],
                    "bom_ids": self.env["mrp.bom"],
                }
            ],
        )
        replenish_empty = create_replenish_wizard(self.warehouse_1, self.productA)
        self.assertFalse(replenish_empty.allowed_route_ids)

        self.warehouse_1.mto_pull_id.route_id.active = True
        self.productA.route_ids = self.warehouse_1.mto_pull_id.route_id

        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.productA.product_tmpl_id.id,
                "product_qty": 1,
            }
        )
        replenish_manufacture = create_replenish_wizard(self.warehouse_1, self.productA)
        self.assertEqual(replenish_manufacture.allowed_route_ids, manufacture_route)

        self.env["product.supplierinfo"].create(
            {
                "product_id": self.productA.id,
                "partner_id": self.partner_1.id,
            }
        )
        replenish_both = create_replenish_wizard(self.warehouse_1, self.productA)
        self.assertEqual(
            set(replenish_both.allowed_route_ids.ids),
            set((manufacture_route | buy_route).ids),
        )

    def test_replenishment_cache_route_placeholder(self):
        self.assertFalse(self.productA.route_ids)
        self.assertFalse(self.productB.route_ids)

        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.productA.product_tmpl_id.id,
                "product_qty": 1,
            }
        )
        self.env["product.supplierinfo"].create(
            {
                "product_id": self.productB.id,
                "partner_id": self.partner_1.id,
                "min_qty": 10,
                "price": 50,
            }
        )
        orderpointA, orderpointB = self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": self.productA.id,
                },
                {
                    "product_id": self.productB.id,
                },
            ]
        )

        (orderpointA | orderpointB)._compute_rule_ids()
        self.assertEqual(orderpointA.route_id_placeholder, "Manufacture")
        self.assertEqual(orderpointB.route_id_placeholder, "Buy")

        (orderpointB | orderpointA)._compute_rule_ids()

        self.assertEqual(orderpointA.route_id_placeholder, "Manufacture")
        self.assertEqual(orderpointB.route_id_placeholder, "Buy")
