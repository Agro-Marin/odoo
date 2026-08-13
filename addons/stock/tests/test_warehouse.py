from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form
from odoo.tests.common import new_test_user

from odoo.addons.stock.tests.common import TestStockCommon


class TestWarehouse(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Acme Corporation"})

    def test_inventory_product(self):
        self.product_1.is_storable = True
        product_1_quant = (
            self.env["stock.quant"]
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product_1.id,
                    "inventory_quantity": 50.0,
                    "location_id": self.warehouse_1.lot_stock_id.id,
                }
            )
        )
        product_1_quant.action_apply_inventory()

        move_in_id = self.env["stock.move"].search(
            [("is_inventory", "=", True), ("product_id", "=", self.product_1.id)]
        )
        self.assertEqual(len(move_in_id), 1)
        self.assertEqual(move_in_id.product_qty, 50.0)
        self.assertEqual(product_1_quant.quantity, 50.0)
        self.assertEqual(move_in_id.product_uom_id, self.product_1.uom_id)
        self.assertEqual(move_in_id.state, "done")

        product_1_quant.inventory_quantity = 35.0
        product_1_quant.action_apply_inventory()

        move_ids = self.env["stock.move"].search(
            [("is_inventory", "=", True), ("product_id", "=", self.product_1.id)]
        )
        self.assertEqual(len(move_ids), 2)
        move_out_id = move_ids[-1]
        self.assertEqual(move_out_id.product_qty, 15.0)
        self.assertEqual(move_out_id.location_id, self.warehouse_1.lot_stock_id)
        self.assertEqual(
            move_out_id.location_dest_id, self.product_1.property_stock_inventory
        )
        self.assertEqual(move_out_id.state, "done")

        quants = self.env["stock.quant"]._gather(
            self.product_1, self.product_1.property_stock_inventory
        )
        self.assertEqual(len(quants), 1)

        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product_1, self.warehouse_1.lot_stock_id)
            .quantity,
            35.0,
        )
        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product_1, self.warehouse_1.lot_stock_id.location_id)
            .quantity,
            35.0,
        )
        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product_1, self.warehouse_1.view_location_id)
            .quantity,
            35.0,
        )

        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product_1, self.warehouse_1.wh_input_stock_loc_id)
            .quantity,
            0.0,
        )
        self.assertEqual(
            self.env["stock.quant"]
            ._gather(self.product_1, self.env.ref("stock.stock_location_stock"))
            .quantity,
            0.0,
        )

    def test_initial_quant_location(self):
        """
        When updating product quantity, new quant should have its location set
        to the stock location of the top warehouse.
        """
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "Mixed locations",
                "code": "TEST",
                "sequence": 0,
            }
        )
        warehouse.in_type_id.default_location_dest_id = self.supplier_location
        warehouse.lot_stock_id = self.stock_location

        quant = self.env["stock.quant"].new(
            {
                "product_id": self.product_1.id,
                "inventory_quantity": 1,
            }
        )
        quant._onchange_product_id()

        self.assertEqual(quant.location_id, self.stock_location)

    def test_basic_move(self):
        self.user_stock_manager.group_ids += self.env.ref(
            "product.group_product_manager"
        )
        product = self.product_3.with_user(self.user_stock_manager)
        product.is_storable = True
        picking_out = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.warehouse_1.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        customer_move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking_out.id,
                "location_id": self.warehouse_1.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.assertEqual(customer_move.product_uom_id, product.uom_id)
        self.assertEqual(customer_move.location_id, self.warehouse_1.lot_stock_id)
        self.assertEqual(customer_move.location_dest_id, self.customer_location)

        customer_move._action_confirm()
        self.assertEqual(product.qty_available, 0.0)
        self.assertEqual(product.qty_available_virtual, -5.0)

        customer_move.quantity = 5
        customer_move.picked = True
        customer_move._action_done()
        self.assertEqual(product.qty_available, -5.0)

        receive_move = self._create_move(
            product,
            self.supplier_location,
            self.warehouse_1.lot_stock_id,
            product_uom_qty=15,
        )

        receive_move._action_confirm()
        receive_move.quantity = 15
        receive_move.picked = True
        receive_move._action_done()

        product._compute_quantities()
        self.assertEqual(product.qty_available, 10.0)
        self.assertEqual(product.qty_available_virtual, 10.0)

        customer_move_2 = self._create_move(
            product,
            self.warehouse_1.lot_stock_id,
            self.customer_location,
            product_uom_qty=2,
        )

        customer_move_2._action_confirm()
        product._compute_quantities()
        self.assertEqual(product.qty_available, 10.0)
        self.assertEqual(product.qty_available_virtual, 8.0)

        customer_move_2.quantity = 2.0
        customer_move_2.picked = True
        customer_move_2._action_done()
        product._compute_quantities()
        self.assertEqual(product.qty_available, 8.0)

    def test_inventory_adjustment_and_negative_quants_1(self):
        """Make sure negative quants from returns get wiped out with an inventory adjustment"""
        productA = self.env["product.product"].create(
            {"name": "Product A", "is_storable": True}
        )

        picking_out = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": productA.id,
                "product_uom_qty": 1,
                "product_uom_id": productA.uom_id.id,
                "picking_id": picking_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking_out.action_confirm()
        picking_out.move_ids.quantity = 1
        picking_out.move_ids.picked = True
        picking_out._action_done()

        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", productA.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        self.assertEqual(len(quant), 1)
        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=picking_out.ids,
                active_id=picking_out.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 1.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_pick = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )
        return_pick.action_assign()
        return_pick.move_ids.quantity = 1
        return_pick.move_ids.picked = True
        return_pick._action_done()

        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", productA.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        self.assertEqual(sum(quant.mapped("quantity")), 0)

    def test_inventory_adjustment_and_negative_quants_2(self):
        """Make sure negative quants get wiped out with an inventory adjustment"""
        productA = self.env["product.product"].create(
            {"name": "Product A", "is_storable": True}
        )
        location_loss = productA.property_stock_inventory

        picking_out = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": productA.id,
                "product_uom_qty": 1,
                "product_uom_id": productA.uom_id.id,
                "picking_id": picking_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking_out.action_confirm()
        picking_out.move_ids.quantity = 1
        picking_out.move_ids.picked = True
        picking_out._action_done()

        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", productA.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        self.assertEqual(len(quant), 1, "Wrong number of quants created.")
        self.assertEqual(quant.quantity, -1, "Theoretical quantity should be -1.")
        quant.inventory_quantity = 0
        quant.action_apply_inventory()

        move = self.env["stock.move"].search(
            [("product_id", "=", productA.id), ("is_inventory", "=", True)]
        )
        self.assertEqual(len(move), 1)
        self.assertEqual(move.product_qty, 1, "Moves created with wrong quantity.")
        self.assertEqual(move.location_id.id, location_loss.id)

        self.env["stock.quant"]._quant_tasks()
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", productA.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )
        self.assertEqual(sum(quants.mapped("quantity")), 0)

        quant = self.env["stock.quant"].search(
            [("product_id", "=", productA.id), ("location_id", "=", location_loss.id)]
        )
        self.assertEqual(len(quant), 1)

    def test_resupply_route(self):
        """Simulate a resupply chain between warehouses.
        Stock -> transit -> Dist. -> transit -> Shop -> Customer
        Create the move from Shop to Customer and ensure that all the pull
        rules are triggered in order to complete the move chain to Stock.
        """
        warehouse_stock = self.env["stock.warehouse"].create(
            {
                "name": "Stock.",
                "code": "STK",
            }
        )

        distribution_partner = self.env["res.partner"].create(
            {"name": "Distribution Center"}
        )
        warehouse_distribution = self.env["stock.warehouse"].create(
            {
                "name": "Dist.",
                "code": "DIST",
                "resupply_wh_ids": [Command.set([warehouse_stock.id])],
                "partner_id": distribution_partner.id,
            }
        )

        warehouse_shop = self.env["stock.warehouse"].create(
            {
                "name": "Shop",
                "code": "SHOP",
                "resupply_wh_ids": [Command.set([warehouse_distribution.id])],
            }
        )

        route_stock_to_dist = warehouse_distribution.resupply_route_ids
        route_dist_to_shop = warehouse_shop.resupply_route_ids

        route_dist_to_shop.rule_ids.procure_method = "make_to_order"

        product = self.env["product.product"].create(
            {
                "name": "Fakir",
                "is_storable": True,
                "route_ids": [
                    Command.link(route_id)
                    for route_id in [
                        route_stock_to_dist.id,
                        route_dist_to_shop.id,
                        self.warehouse_1.mto_pull_id.route_id.id,
                    ]
                ],
            }
        )

        picking_out = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": warehouse_shop.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 1,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking_out.id,
                "location_id": warehouse_shop.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
                "warehouse_id": warehouse_shop.id,
                "procure_method": "make_to_order",
            }
        )
        picking_out.action_confirm()

        moves = self.env["stock.move"].search([("product_id", "=", product.id)])
        self.assertEqual(len(moves), 5, "Invalid moves number.")
        self.assertTrue(
            self.env["stock.move"].search(
                [("location_id", "=", warehouse_stock.lot_stock_id.id)]
            )
        )
        self.assertTrue(
            self.env["stock.move"].search(
                [("location_dest_id", "=", warehouse_distribution.lot_stock_id.id)]
            )
        )
        self.assertTrue(
            self.env["stock.move"].search(
                [("location_id", "=", warehouse_distribution.lot_stock_id.id)]
            )
        )
        self.assertTrue(
            self.env["stock.move"].search(
                [("location_dest_id", "=", warehouse_shop.lot_stock_id.id)]
            )
        )
        self.assertTrue(
            self.env["stock.move"].search(
                [("location_id", "=", warehouse_shop.lot_stock_id.id)]
            )
        )

        self.assertTrue(
            self.env["stock.picking"].search(
                [
                    (
                        "location_id",
                        "=",
                        self.env.company.internal_transit_location_id.id,
                    ),
                    ("partner_id", "=", distribution_partner.id),
                ]
            )
        )
        self.assertTrue(
            self.env["stock.picking"].search(
                [
                    (
                        "location_dest_id",
                        "=",
                        self.env.company.internal_transit_location_id.id,
                    ),
                    ("partner_id", "=", distribution_partner.id),
                ]
            )
        )

    def test_mutiple_resupply_warehouse(self):
        """Simulate the following situation:
        - 2 shops with stock are resupply by 2 distinct warehouses
        - Shop Namur is resupply by the warehouse stock Namur
        - Shop Wavre is resupply by the warehouse stock Wavre
        - Simulate 2 moves for the same product but in different shop.
        This test ensure that the move are supplied by the correct distribution
        warehouse.
        """
        customer_location = self.customer_location

        warehouse_distribution_wavre = self.env["stock.warehouse"].create(
            {
                "name": "Stock Wavre.",
                "code": "WV",
            }
        )

        warehouse_shop_wavre = self.env["stock.warehouse"].create(
            {
                "name": "Shop Wavre",
                "code": "SHWV",
                "resupply_wh_ids": [Command.set([warehouse_distribution_wavre.id])],
            }
        )

        warehouse_distribution_namur = self.env["stock.warehouse"].create(
            {
                "name": "Stock Namur.",
                "code": "NM",
            }
        )

        warehouse_shop_namur = self.env["stock.warehouse"].create(
            {
                "name": "Shop Namur",
                "code": "SHNM",
                "resupply_wh_ids": [Command.set([warehouse_distribution_namur.id])],
            }
        )

        route_shop_namur = warehouse_shop_namur.resupply_route_ids
        route_shop_wavre = warehouse_shop_wavre.resupply_route_ids
        product = self.env["product.product"].create(
            {
                "name": "Fakir",
                "is_storable": True,
                "route_ids": [
                    Command.link(route_id)
                    for route_id in [
                        route_shop_namur.id,
                        route_shop_wavre.id,
                        self.warehouse_1.mto_pull_id.route_id.id,
                    ]
                ],
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            product, warehouse_distribution_wavre.lot_stock_id, 1.0
        )
        self.env["stock.quant"]._update_available_quantity(
            product, warehouse_distribution_namur.lot_stock_id, 1.0
        )

        picking_out_namur = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": warehouse_shop_namur.lot_stock_id.id,
                "location_dest_id": customer_location.id,
                "state": "draft",
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 1,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking_out_namur.id,
                "location_id": warehouse_shop_namur.lot_stock_id.id,
                "location_dest_id": customer_location.id,
                "warehouse_id": warehouse_shop_namur.id,
                "procure_method": "make_to_order",
            }
        )
        picking_out_namur.action_confirm()

        picking_stock_transit = self.env["stock.picking"].search(
            [("location_id", "=", warehouse_distribution_namur.lot_stock_id.id)]
        )
        self.assertTrue(picking_stock_transit)
        picking_stock_transit.action_assign()
        picking_stock_transit.move_ids[0].quantity = 1.0
        picking_stock_transit.move_ids[0].picked = True
        picking_stock_transit._action_done()

        picking_transit_shop_namur = self.env["stock.picking"].search(
            [("location_dest_id", "=", warehouse_shop_namur.lot_stock_id.id)]
        )
        self.assertTrue(picking_transit_shop_namur)
        picking_transit_shop_namur.action_assign()
        picking_transit_shop_namur.move_ids[0].quantity = 1.0
        picking_transit_shop_namur.move_ids[0].picked = True
        picking_transit_shop_namur._action_done()

        picking_out_namur.action_assign()
        picking_out_namur.move_ids[0].picked = True
        picking_out_namur.move_ids[0].quantity = 1.0
        picking_out_namur._action_done()

        self.assertEqual(
            self.env["stock.quant"]._gather(product, customer_location).quantity, 1
        )
        self.assertEqual(
            sum(
                self.env["stock.quant"]
                ._gather(product, warehouse_distribution_namur.lot_stock_id)
                .mapped("quantity")
            ),
            0,
        )

        picking_out_wavre = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": self.picking_type_out.id,
                "location_id": warehouse_shop_wavre.lot_stock_id.id,
                "location_dest_id": customer_location.id,
                "state": "draft",
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 1,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking_out_wavre.id,
                "location_id": warehouse_shop_wavre.lot_stock_id.id,
                "location_dest_id": customer_location.id,
                "warehouse_id": warehouse_shop_wavre.id,
                "procure_method": "make_to_order",
            }
        )
        picking_out_wavre.action_confirm()

        picking_stock_transit = self.env["stock.picking"].search(
            [("location_id", "=", warehouse_distribution_wavre.lot_stock_id.id)]
        )
        self.assertTrue(picking_stock_transit)
        picking_stock_transit.action_assign()
        picking_stock_transit.move_ids[0].quantity = 1.0
        picking_stock_transit.move_ids[0].picked = True
        picking_stock_transit._action_done()

        picking_transit_shop_wavre = self.env["stock.picking"].search(
            [("location_dest_id", "=", warehouse_shop_wavre.lot_stock_id.id)]
        )
        self.assertTrue(picking_transit_shop_wavre)
        picking_transit_shop_wavre.action_assign()
        picking_transit_shop_wavre.move_ids[0].quantity = 1.0
        picking_transit_shop_wavre.move_ids[0].picked = True
        picking_transit_shop_wavre._action_done()

        picking_out_wavre.action_assign()
        picking_out_wavre.move_ids[0].quantity = 1.0
        picking_out_wavre.move_ids[0].picked = True
        picking_out_wavre._action_done()

        self.assertEqual(
            self.env["stock.quant"]._gather(product, customer_location).quantity, 2
        )
        self.assertEqual(
            sum(
                self.env["stock.quant"]
                ._gather(product, warehouse_distribution_wavre.lot_stock_id)
                .mapped("quantity")
            ),
            0,
        )

    def test_add_resupply_warehouse_one_by_one(self):
        """Checks that selecting a warehouse as a resupply warehouse one after another correctly sets the routes as well."""
        warehouse_A, warehouse_B, warehouse_C = self.env["stock.warehouse"].create(
            [
                {
                    "name": code,
                    "code": code,
                }
                for code in ["WH_A", "WH_B", "WH_C"]
            ]
        )
        warehouse_A.resupply_wh_ids = [Command.link(warehouse_B.id)]
        self.assertEqual(len(warehouse_A.resupply_route_ids), 1)
        self.assertEqual(warehouse_A.resupply_route_ids.supplier_wh_id, warehouse_B)
        warehouse_A.resupply_wh_ids = [Command.link(warehouse_C.id)]
        self.assertEqual(len(warehouse_A.resupply_route_ids), 2)
        self.assertRecordValues(
            warehouse_A.resupply_route_ids.sorted("id"),
            [
                {"supplier_wh_id": warehouse_B.id},
                {"supplier_wh_id": warehouse_C.id},
            ],
        )

    def test_toggle_resupply_warehouse(self):
        """Checks that selecting then unselecting a warehouse as resupply correctly archives/unarchives the related route."""
        warehouse_A = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse A",
                "code": "WH_A",
            }
        )
        warehouse_B = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse B",
                "code": "WH_B",
                "resupply_wh_ids": [Command.set(warehouse_A.ids)],
            }
        )
        resupply_route = warehouse_B.resupply_route_ids
        self.assertTrue(resupply_route.active, "Route should be active")
        warehouse_B.resupply_wh_ids = [Command.set([])]
        self.assertFalse(warehouse_B.resupply_route_ids)
        self.assertFalse(resupply_route.active, "Route should now be inactive")
        warehouse_B.resupply_wh_ids = [Command.set(warehouse_A.ids)]
        self.assertEqual(warehouse_B.resupply_route_ids, resupply_route)
        self.assertTrue(resupply_route.active, "Route should now be active")

    def test_muti_step_resupply_warehouse(self):
        """Simulate the following situation:
        - First warehouse has a 3-steps delivery
        - Second warehouse has a 3-steps reception
        - Second warehouse is resupplied by the first warehouse
        - A product has some stock in the first warehouse
        - A reordering rule is set on the product to fill the second warehouse
        Ensure that the product can move all the way from the first to the second warehouse.
        """
        warehouse_A = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse A",
                "code": "WH_A",
                "delivery_steps": "pick_pack_ship",
            }
        )
        warehouse_B = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse B",
                "code": "WH_B",
                "reception_steps": "three_steps",
                "resupply_wh_ids": [Command.link(warehouse_A.id)],
            }
        )
        self.product_3.write(
            {
                "type": "consu",
                "is_storable": True,
                "route_ids": [Command.link(warehouse_B.resupply_route_ids.id)],
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_3, warehouse_A.lot_stock_id, 1.0
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.product_3, warehouse_A.lot_stock_id
            ),
            1,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.product_3, warehouse_B.lot_stock_id
            ),
            0,
        )

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "location_id": warehouse_B.lot_stock_id.id,
                "product_id": self.product_3.id,
                "qty_to_order": 1.0,
            }
        )
        orderpoint.action_replenish()
        move = self.env["stock.move"].search(
            [
                ("location_id", "=", warehouse_A.lot_stock_id.id),
                ("origin", "=", orderpoint.name),
            ]
        )
        self.assertTrue(move, "No move created from WH_A/Stock")

        inter_wh_loc = self.env.company.internal_transit_location_id
        step_location_ids = [
            (
                warehouse_A.lot_stock_id.id,
                warehouse_A.wh_pack_stock_loc_id.id,
            ),
            (
                warehouse_A.wh_pack_stock_loc_id.id,
                warehouse_A.wh_output_stock_loc_id.id,
            ),
            (
                warehouse_A.wh_output_stock_loc_id.id,
                inter_wh_loc.id,
            ),
            (
                inter_wh_loc.id,
                warehouse_B.wh_input_stock_loc_id.id,
            ),
            (
                warehouse_B.wh_input_stock_loc_id.id,
                warehouse_B.wh_qc_stock_loc_id.id,
            ),
            (
                warehouse_B.wh_qc_stock_loc_id.id,
                warehouse_B.lot_stock_id.id,
            ),
        ]
        for loc_src_id, loc_dest_id in step_location_ids:
            self.assertEqual(move.location_id.id, loc_src_id)
            self.assertEqual(move.location_dest_id.id, loc_dest_id)
            move.picked = True
            move._action_done()
            self.assertEqual(move.state, "done")
            move = move.move_dest_ids
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.product_3, warehouse_A.lot_stock_id
            ),
            0,
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.product_3, warehouse_B.lot_stock_id
            ),
            1,
        )

    def test_change_delivery_step_resupply_warehouse(self):
        """Verifies that when changing the delivery steps of a warehouse, it correctly adds/removes the extra rule
        that is required to resupply the Output location.
        """
        warehouse_A = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse X",
                "code": "WH_X",
            }
        )
        warehouse_B = self.env["stock.warehouse"].create(
            {
                "name": "Warehouse Y",
                "code": "WH_Y",
                "resupply_wh_ids": [Command.link(warehouse_A.id)],
            }
        )
        resupply_rules = warehouse_B.resupply_route_ids.rule_ids
        self.assertEqual(len(resupply_rules), 2)
        stock_A_to_transit = resupply_rules.filtered(
            lambda r: (
                r.location_dest_id == self.env.company.internal_transit_location_id
            )
        )
        self.assertEqual(stock_A_to_transit.location_src_id, warehouse_A.lot_stock_id)

        warehouse_A.delivery_steps = "pick_pack_ship"
        new_resupply_rules = warehouse_B.resupply_route_ids.rule_ids
        self.assertEqual(len(new_resupply_rules), 3)
        self.assertEqual(
            stock_A_to_transit.location_src_id, warehouse_A.wh_output_stock_loc_id
        )
        stock_to_output = new_resupply_rules - resupply_rules
        self.assertEqual(stock_to_output.location_src_id, warehouse_A.lot_stock_id)
        self.assertEqual(
            stock_to_output.location_dest_id, warehouse_A.wh_output_stock_loc_id
        )

        warehouse_A.delivery_steps = "pick_ship"
        self.assertEqual(warehouse_B.resupply_route_ids.rule_ids, new_resupply_rules)
        self.assertEqual(
            stock_A_to_transit.location_src_id, warehouse_A.wh_output_stock_loc_id
        )
        self.assertEqual(
            stock_to_output.location_dest_id, warehouse_A.wh_output_stock_loc_id
        )

        warehouse_A.delivery_steps = "ship_only"
        self.assertEqual(warehouse_B.resupply_route_ids.rule_ids, resupply_rules)
        self.assertEqual(stock_A_to_transit.location_src_id, warehouse_A.lot_stock_id)
        self.assertFalse(
            stock_to_output.active, "The intermediate rule should have been archived."
        )

        warehouse_A.delivery_steps = "pick_ship"
        self.assertTrue(
            stock_to_output.active, "The intermediate rule should have been unarchived."
        )
        self.assertEqual(
            warehouse_B.resupply_route_ids.rule_ids,
            new_resupply_rules,
            "No new rule should have been created.",
        )

    def test_noleak(self):
        partner = self.env["res.partner"].create({"name": "Chicago partner"})
        company = self.env["res.company"].create(
            {"name": "My Company (Chicago)1", "currency_id": self.ref("base.USD")}
        )
        self.env["stock.warehouse"].create(
            {
                "name": "Chicago Warehouse2",
                "company_id": company.id,
                "code": "Chic2",
                "partner_id": partner.id,
            }
        )
        wh = self.env["stock.warehouse"].search([])

        assert len(set(wh.mapped("company_id.id"))) > 1

        companies_before = wh.mapped(lambda w: (w.id, w.company_id))
        wh.name = "whatever"
        companies_after = wh.mapped(lambda w: (w.id, w.company_id))

        self.assertEqual(companies_after, companies_before)

    def test_toggle_active_warehouse_1(self):
        """Basic test that create a warehouse with classic configuration.
        Archive it and check that locations, picking types, routes, rules are
        correclty active or archive.
        """
        wh = Form(self.env["stock.warehouse"])
        wh.name = "The attic of Willy"
        wh.code = "WIL"
        warehouse = wh.save()

        custom_location = Form(self.env["stock.location"])
        custom_location.name = "A Trunk"
        custom_location.location_id = warehouse.lot_stock_id
        custom_location = custom_location.save()

        warehouse.action_archive()
        self.assertFalse(warehouse.mto_pull_id.active)

        self.assertFalse(warehouse.reception_route_id.active)
        self.assertFalse(warehouse.delivery_route_id.active)

        self.assertFalse(warehouse.lot_stock_id.active)
        self.assertFalse(warehouse.wh_input_stock_loc_id.active)
        self.assertFalse(warehouse.wh_qc_stock_loc_id.active)
        self.assertFalse(warehouse.wh_output_stock_loc_id.active)
        self.assertFalse(warehouse.wh_pack_stock_loc_id.active)
        self.assertFalse(custom_location.active)

        self.assertFalse(warehouse.in_type_id.active)
        self.assertFalse(warehouse.out_type_id.active)
        self.assertFalse(warehouse.int_type_id.active)
        self.assertFalse(warehouse.pick_type_id.active)
        self.assertFalse(warehouse.pack_type_id.active)

        warehouse.action_unarchive()
        self.assertTrue(warehouse.mto_pull_id.active)

        self.assertTrue(warehouse.reception_route_id.active)
        self.assertTrue(warehouse.delivery_route_id.active)

        self.assertTrue(warehouse.lot_stock_id.active)
        self.assertFalse(warehouse.wh_input_stock_loc_id.active)
        self.assertFalse(warehouse.wh_qc_stock_loc_id.active)
        self.assertFalse(warehouse.wh_output_stock_loc_id.active)
        self.assertFalse(warehouse.wh_pack_stock_loc_id.active)
        self.assertTrue(custom_location.active)

        self.assertTrue(warehouse.in_type_id.active)
        self.assertTrue(warehouse.out_type_id.active)
        self.assertTrue(warehouse.int_type_id.active)
        self.assertFalse(warehouse.pick_type_id.active)
        self.assertFalse(warehouse.pack_type_id.active)

    def test_toggle_active_blocked_by_foreign_picking_type(self):
        """Archiving a warehouse must be refused when a picking type belonging
        to *another* warehouse references one of this warehouse's locations as
        its default source OR destination — otherwise that picking type would be
        left pointing at an archived location. Regression: the guard used to
        require BOTH endpoints inside the warehouse, silently letting a
        src-only / dest-only reference dangle.
        """
        Warehouse = self.env["stock.warehouse"]
        wh_a = Warehouse.create({"name": "Archive Me", "code": "ARM"})
        wh_b = Warehouse.create({"name": "Other WH", "code": "OTH"})
        customer_loc = self.env.ref("stock.stock_location_customers")

        self.env["stock.picking.type"].create(
            {
                "name": "Foreign src-only",
                "code": "outgoing",
                "sequence_code": "FSO",
                "warehouse_id": wh_b.id,
                "default_location_src_id": wh_a.lot_stock_id.id,
                "default_location_dest_id": customer_loc.id,
                "company_id": wh_a.company_id.id,
            }
        )

        with self.assertRaises(UserError):
            wh_a.action_archive()
        self.assertTrue(
            wh_a.lot_stock_id.active,
            "The stock location must stay active since archiving was refused.",
        )

    def test_toggle_active_warehouse_2(self):
        self.env.user.group_ids += self.env.ref("stock.group_adv_location")
        wh = Form(self.env["stock.warehouse"])
        wh.name = "The attic of Willy"
        wh.code = "WIL"
        wh.reception_steps = "two_steps"
        wh.delivery_steps = "pick_pack_ship"
        warehouse = wh.save()

        warehouse.resupply_wh_ids = [Command.set([self.warehouse_1.id])]

        custom_location = Form(self.env["stock.location"])
        custom_location.name = "A Trunk"
        custom_location.location_id = warehouse.lot_stock_id
        custom_location = custom_location.save()

        warehouse.reception_route_id.warehouse_ids = [Command.link(self.warehouse_1.id)]

        route = Form(self.env["stock.route"])
        route.name = "Stair"
        route = route.save()

        route.warehouse_ids = [Command.set([warehouse.id, self.warehouse_1.id])]

        warehouse.delivery_route_id.action_archive()
        warehouse.wh_pack_stock_loc_id.action_archive()

        warehouse.action_archive()
        self.assertFalse(warehouse.mto_pull_id.active)

        self.assertTrue(warehouse.reception_route_id.active)
        self.assertFalse(warehouse.delivery_route_id.active)
        self.assertTrue(route.active)

        self.assertFalse(warehouse.lot_stock_id.active)
        self.assertFalse(warehouse.wh_input_stock_loc_id.active)
        self.assertFalse(warehouse.wh_qc_stock_loc_id.active)
        self.assertFalse(warehouse.wh_output_stock_loc_id.active)
        self.assertFalse(warehouse.wh_pack_stock_loc_id.active)
        self.assertFalse(custom_location.active)

        self.assertFalse(warehouse.in_type_id.active)
        self.assertFalse(warehouse.out_type_id.active)
        self.assertFalse(warehouse.int_type_id.active)
        self.assertFalse(warehouse.pick_type_id.active)
        self.assertFalse(warehouse.pack_type_id.active)

        warehouse.action_unarchive()
        self.assertTrue(warehouse.mto_pull_id.active)

        self.assertTrue(warehouse.reception_route_id.active)
        self.assertTrue(warehouse.delivery_route_id.active)

        self.assertTrue(warehouse.lot_stock_id.active)
        self.assertTrue(warehouse.wh_input_stock_loc_id.active)
        self.assertFalse(warehouse.wh_qc_stock_loc_id.active)
        self.assertTrue(warehouse.wh_output_stock_loc_id.active)
        self.assertTrue(warehouse.wh_pack_stock_loc_id.active)
        self.assertTrue(custom_location.active)

        self.assertTrue(warehouse.in_type_id.active)
        self.assertTrue(warehouse.out_type_id.active)
        self.assertTrue(warehouse.int_type_id.active)
        self.assertTrue(warehouse.pick_type_id.active)
        self.assertTrue(warehouse.pack_type_id.active)

    def test_edit_warehouse_1(self):
        wh = Form(self.env["stock.warehouse"])
        wh.name = "Chicago"
        wh.code = "chic"
        warehouse = wh.save()
        self.assertEqual(warehouse.int_type_id.barcode, "CHICINT")
        self.assertEqual(warehouse.int_type_id.sequence_id.prefix, "chic/INT/")

        wh = Form(warehouse)
        wh.code = "CH"
        wh.save()
        self.assertEqual(warehouse.int_type_id.barcode, "CHINT")
        self.assertEqual(warehouse.int_type_id.sequence_id.prefix, "CH/INT/")

    def test_create_warehouse_without_company_defaults(self):
        """A warehouse created without an explicit company_id (relying on the
        field default) must still get a generated code and a named view
        location, instead of crashing with a NOT NULL violation on
        stock.location.name.
        """
        Warehouse = self.env["stock.warehouse"]
        wh = Warehouse.create({"name": "No Company WH"})
        self.assertTrue(wh.code, "a short name should be auto-generated")
        self.assertEqual(wh.company_id, self.env.company)
        self.assertTrue(wh.view_location_id.name, "the view location must be named")
        self.assertEqual(wh.view_location_id.company_id, self.env.company)
        wh2 = Warehouse.create({})
        self.assertTrue(wh2.code)
        self.assertTrue(wh2.name)

    def test_multiwarehouse_group_implied_on_warehouse_creation(self):
        """Creating a warehouse for a company that then has more than one active
        warehouse must (re)imply the multi-warehouse group — and pull in the
        multi-locations group — on ``base.group_user``. This global side effect
        of warehouse CRUD was previously uncovered.
        """
        group_user = self.env.ref("base.group_user")
        group_multi_wh = self.env.ref("stock.group_stock_multi_warehouses")
        group_multi_loc = self.env.ref("stock.group_stock_multi_locations")
        Warehouse = self.env["stock.warehouse"]

        company = self.env["res.company"].create({"name": "Multi-WH Co"})
        Warehouse.create({"name": "MW A", "code": "MWA", "company_id": company.id})

        group_user.write({"implied_ids": [(3, group_multi_wh.id)]})
        self.assertNotIn(group_multi_wh, group_user.implied_ids)

        Warehouse.create({"name": "MW B", "code": "MWB", "company_id": company.id})
        self.assertIn(
            group_multi_wh,
            group_user.implied_ids,
            "a company with several active warehouses must imply the "
            "multi-warehouse group",
        )
        self.assertIn(
            group_multi_loc,
            group_user.implied_ids,
            "the multi-warehouse group must pull in the multi-locations group",
        )

    def test_location_warehouse(self):
        """Check that the closest warehouse is selected
        in a warehouse within warehouse situation
        """
        wh = self.env["stock.warehouse"].create(
            {
                "name": "Main Test Warehouse",
                "code": "MTWH",
            }
        )
        test_warehouse = self.warehouse_1
        location = test_warehouse.lot_stock_id
        self.assertEqual(location.warehouse_id, test_warehouse)

        test_warehouse.view_location_id.location_id = wh.lot_stock_id.id
        wh.sequence = 100
        test_warehouse.sequence = 1
        location._compute_warehouse_id()
        self.assertEqual(location.warehouse_id, test_warehouse)

        wh.sequence = 1
        test_warehouse.sequence = 100
        location._compute_warehouse_id()
        self.assertEqual(location.warehouse_id, test_warehouse)

    def test_location_updates_wh(self):
        warehouse_A = self.env["stock.warehouse"].create(
            {"name": "Warehouse X", "code": "WH_X", "delivery_steps": "pick_pack_ship"}
        )
        warehouse_B = self.env["stock.warehouse"].create(
            {"name": "Warehouse Y", "code": "WH_Y", "delivery_steps": "pick_pack_ship"}
        )
        picking_out = self.env["stock.picking"].create(
            {
                "partner_id": self.partner.id,
                "picking_type_id": warehouse_A.pick_type_id.id,
                "location_id": warehouse_A.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        customer_move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom_id": self.product.uom_id.id,
                "picking_id": picking_out.id,
                "location_id": warehouse_A.lot_stock_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking_form = Form(picking_out)
        picking_form.picking_type_id = warehouse_B.pick_type_id
        picking_form.save()
        self.assertEqual(customer_move.warehouse_id, warehouse_B)
        self.assertEqual(picking_out.picking_type_id, warehouse_B.pick_type_id)
        picking_out.button_validate()
        self.assertEqual(customer_move.move_dest_ids.warehouse_id, warehouse_B)

    def test_multi_step_routes_multi_company(self):
        """
        Check the pickings of the multi-step routes are correctly generated
        in multi-company set up.
        """
        companies = self.env["res.company"].create(
            [
                {"name": "COMP1"},
                {"name": "COMP2"},
            ]
        )
        warehouses = self.env["stock.warehouse"].create(
            [
                {
                    "name": "Warehouse 1",
                    "company_id": companies.ids[0],
                    "code": "WHC1",
                },
                {
                    "name": "Warehouse 2",
                    "company_id": companies.ids[1],
                    "code": "WHC2",
                },
            ]
        )
        warehouse = warehouses[0]
        warehouse.delivery_steps = "pick_ship"
        user = new_test_user(
            self.env,
            login="bub",
            groups="stock.group_stock_user",
            company_id=companies.ids[1],
            company_ids=[Command.set(companies.ids)],
        )
        pick = (
            self.env["stock.picking"]
            .with_user(user)
            .create(
                {
                    "partner_id": self.partner.id,
                    "picking_type_id": warehouse.pick_type_id.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                    "company_id": companies.ids[0],
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": self.product.id,
                                "product_uom_qty": 1,
                                "product_uom_id": self.product.uom_id.id,
                                "company_id": companies.ids[0],
                                "location_id": warehouse.lot_stock_id.id,
                                "location_dest_id": warehouse.wh_output_stock_loc_id.id,
                            }
                        )
                    ],
                }
            )
        )
        pick.with_user(user).action_confirm()
        pick.with_user(user).button_validate()
        ship = pick.move_ids.move_dest_ids
        self.assertRecordValues(
            ship,
            [
                {
                    "picking_type_id": warehouse.out_type_id.id,
                    "company_id": companies.ids[0],
                    "location_id": warehouse.wh_output_stock_loc_id.id,
                }
            ],
        )

    def test_sequence_preservation_on_step_change(self):
        out_type = self.warehouse_1.out_type_id
        sequence = out_type.sequence_id
        end_of_prefix = "LOREM/"
        sequence.prefix += end_of_prefix
        self.warehouse_1.delivery_steps = "pick_ship"
        self.assertTrue(sequence.prefix.endswith(end_of_prefix))

    def test_modified_global_route(self):
        """Ensure that _find_or_create_global_route, if called multiple time, only creates the route once

        If a global route was renamed, and has a company setup,
          then the system would create multiple duplicates with the new name when creating a new warehouse;
          one duplicate for each call _find_or_create_global_route.
        """
        company_2 = self.env["res.company"].create({"name": "Company 2"})

        mto_route = self.warehouse_1.mto_pull_id.route_id
        mto_route.rule_ids.unlink()
        mto_route.write(
            {"name": "New Name (MTO)", "company_id": self.warehouse_1.company_id.id}
        )

        self.env["stock.warehouse"].with_company(company_2).create(
            {"name": "Warehouse 2", "code": "2"}
        )

        route_sudo = self.env["stock.route"].sudo().with_context(active_test=False)
        renamed_route_count = route_sudo.search_count([("name", "=", "New Name (MTO)")])
        self.assertEqual(renamed_route_count, 1)

        new_mto_route = route_sudo.search([("name", "=", "Replenish on Order (MTO)")])
        self.assertEqual(len(new_mto_route), 1)
        self.assertEqual(new_mto_route.company_id.id, company_2.id)

    def test_search_qty_to_order_of_0(self):
        """
        Test that searching for orderpoints on `qty_to_order` with value = 0 for different operators
        works correctly.

        The test first creates two orderpoints with `qty_to_order_manual = 0`,
        then updates `qty_to_order` to a non-zero value to ensure the search
        properly filters records based on the field value.
        """
        self.env["stock.warehouse.orderpoint"].search([]).write({"active": False})
        orderpoints = self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "location_id": self.warehouse_1.lot_stock_id.id,
                    "product_id": self.product_1.id,
                    "product_min_qty": 0.0,
                    "product_max_qty": 0.0,
                    "trigger": "manual",
                },
                {
                    "location_id": self.warehouse_1.lot_stock_id.id,
                    "product_id": self.product_2.id,
                    "product_min_qty": 3.0,
                    "product_max_qty": 5.0,
                    "trigger": "manual",
                },
            ]
        )

        for op, expected in [
            ("=", orderpoints[0]),
            (">", orderpoints[1]),
            (">=", orderpoints),
            ("<", self.env["stock.warehouse.orderpoint"]),
        ]:
            res = self.env["stock.warehouse.orderpoint"].search(
                [("qty_to_order", op, 0)]
            )
            self.assertEqual(res, expected, "Error with operator %s" % op)

        orderpoints[0].qty_to_order = 3

        for op, expected in [
            ("!=", orderpoints),
            ("=", self.env["stock.warehouse.orderpoint"]),
        ]:
            res = self.env["stock.warehouse.orderpoint"].search(
                [("qty_to_order", op, 0)]
            )
            self.assertEqual(res, expected, "Error with operator %s" % op)

    def test_create_second_warehouse_as_stock_manager(self):
        """`stock.group_stock_manager` holds full CRUD on stock.warehouse and the
        Warehouses menu is gated on that group, so a plain stock manager must be
        able to create their company's second warehouse.

        `_check_multiwarehouse_group` used to imply the multi-warehouse group and
        run the Storage Locations setting as the acting user, so this raised
        AccessError — on res.config.settings when Storage Locations was still
        off, on res.groups when it was already on. Both branches are exercised:
        the first is the shipped state of a fresh database, the second is any
        tenant that turned Storage Locations on by hand. The setup below
        reproduces them explicitly because this class's own fixtures have already
        tripped the group.
        """
        Warehouse = self.env["stock.warehouse"]
        group_user = self.env.ref("base.group_user")
        multi_wh = self.env.ref("stock.group_stock_multi_warehouses")
        multi_loc = self.env.ref("stock.group_stock_multi_locations")
        manager = new_test_user(
            self.env, login="wh_manager", groups="stock.group_stock_manager"
        )
        self.assertFalse(manager.has_group("base.group_system"))

        branches = [
            ("res.config.settings branch", [(3, multi_wh.id), (3, multi_loc.id)]),
            ("res.groups branch", [(3, multi_wh.id), (4, multi_loc.id)]),
        ]
        for index, (label, implied) in enumerate(branches):
            with self.subTest(branch=label):
                Warehouse.search([]).write({"active": False})
                group_user.write({"implied_ids": implied})
                self.assertNotIn(multi_wh, group_user.implied_ids)
                base = Warehouse.create(
                    {"name": "Base WH %d" % index, "code": "BSW%d" % index}
                )
                self.assertNotIn(
                    multi_wh,
                    group_user.implied_ids,
                    "one warehouse must not imply the multi-warehouse group",
                )

                warehouse = Warehouse.with_user(manager).create(
                    {"name": "Manager WH %d" % index, "code": "MGW%d" % index}
                )
                self.assertTrue(warehouse.exists())
                self.assertIn(
                    multi_wh,
                    group_user.implied_ids,
                    "the second warehouse must imply the multi-warehouse group",
                )
                (warehouse | base).write({"active": False})

    def test_multiwarehouse_group_dropped_when_last_archived(self):
        """One active warehouse un-implies the multi-warehouse group; zero must
        too. An empty read_group used to skip the reconciliation entirely.
        """
        Warehouse = self.env["stock.warehouse"]
        group_user = self.env.ref("base.group_user")
        multi_wh = self.env.ref("stock.group_stock_multi_warehouses")
        Warehouse.create({"name": "Second one", "code": "SEC"})
        self.assertIn(multi_wh, group_user.implied_ids)

        Warehouse.search([]).action_archive()
        self.assertEqual(Warehouse.search_count([]), 0)
        self.assertNotIn(
            multi_wh,
            group_user.implied_ids,
            "no active warehouse at all must not leave the multi-warehouse UI on",
        )

    def test_write_active_true_on_active_warehouse_with_open_moves(self):
        """`write({"active": True})` on an already-active warehouse is a no-op and
        must not run the archive guards. It used to raise "You still have ongoing
        operations" for any warehouse holding an open move.
        """
        warehouse = self.env["stock.warehouse"].create({"name": "Busy", "code": "BSY"})
        self.env["stock.move"].create(
            {
                "product_id": self.product_1.id,
                "product_uom_qty": 3,
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "company_id": warehouse.company_id.id,
            }
        )
        warehouse.write({"active": True})
        self.assertTrue(warehouse.active)
        with self.assertRaises(UserError):
            warehouse.action_archive()

    def test_unarchive_with_foreign_picking_type(self):
        """A picking type outside the warehouse pointing at one of its locations
        blocks archiving, but must never block *un*archiving — otherwise the
        warehouse can never be brought back.
        """
        warehouse = self.env["stock.warehouse"].create(
            {"name": "Comes Back", "code": "CMB"}
        )
        warehouse.action_archive()
        self.env["stock.picking.type"].create(
            {
                "name": "Foreign type",
                "code": "internal",
                "sequence_code": "FGN",
                "default_location_src_id": warehouse.lot_stock_id.id,
                "default_location_dest_id": warehouse.lot_stock_id.id,
                "company_id": warehouse.company_id.id,
            }
        )
        warehouse.action_unarchive()
        self.assertTrue(warehouse.active)
        self.assertTrue(warehouse.lot_stock_id.active)

    def test_rule_names_follow_code_change(self):
        """Rule names are built from the warehouse *code* and feed move.origin,
        so a recode has to reach them. Refreshing the routes does not:
        `_find_existing_rule_or_create` matches on routing identity and leaves
        the matched rule, name included, untouched.
        """
        warehouse = self.env["stock.warehouse"].create(
            {"name": "Recode", "code": "RC1", "reception_steps": "two_steps"}
        )
        rules = (
            warehouse.reception_route_id.rule_ids
            | warehouse.delivery_route_id.rule_ids
            | warehouse.mto_pull_id
        )
        self.assertTrue(all(rule.name.startswith("RC1: ") for rule in rules))

        warehouse.write({"code": "RC2"})
        for rule in rules:
            self.assertTrue(
                rule.name.startswith("RC2: "),
                "rule %r still carries the old warehouse code" % rule.name,
            )
        self.assertEqual(warehouse.int_type_id.barcode, "RC2INT")
        self.assertEqual(warehouse.int_type_id.sequence_id.prefix, "RC2/INT/")
        self.assertEqual(warehouse.view_location_id.name, "RC2")

    def test_recode_renames_view_location_when_stock_is_nested(self):
        """The recode renames the warehouse's *view location*. It used to rename
        `lot_stock_id.location_id`, a different record as soon as Stock sits
        below an intermediate zone.
        """
        warehouse = self.env["stock.warehouse"].create(
            {"name": "Nested", "code": "NS1"}
        )
        zone = self.env["stock.location"].create(
            {
                "name": "Zone A",
                "usage": "view",
                "location_id": warehouse.view_location_id.id,
            }
        )
        warehouse.lot_stock_id.location_id = zone
        warehouse.write({"code": "NS2"})
        self.assertEqual(warehouse.view_location_id.name, "NS2")
        self.assertEqual(
            zone.name, "Zone A", "the intermediate zone must be left alone"
        )

    def test_resupply_route_name_follows_rename(self):
        """Resupply routes name both endpoints and belong to neither warehouse's
        `route_ids`, so renaming either side has to rebuild them.
        """
        Warehouse = self.env["stock.warehouse"]
        supplier = Warehouse.create({"name": "Alpha", "code": "ALP"})
        supplied = Warehouse.create({"name": "Beta", "code": "BET"})
        supplied.resupply_wh_ids = [Command.link(supplier.id)]
        route = supplied.resupply_route_ids
        self.assertEqual(route.name, "Beta: Supply Product from Alpha")

        supplier.write({"name": "Alpha Renamed"})
        self.assertEqual(route.name, "Beta: Supply Product from Alpha Renamed")
        supplied.write({"name": "Beta Renamed"})
        self.assertEqual(route.name, "Beta Renamed: Supply Product from Alpha Renamed")

    def test_warehouse_cannot_resupply_itself(self):
        """A self-resupply route is not inert: it resolves into a delivery to
        transit plus a receipt back, moving real quantities for no net effect.
        """
        warehouse = self.env["stock.warehouse"].create({"name": "Solo", "code": "SLO"})
        with self.assertRaises(ValidationError):
            warehouse.resupply_wh_ids = [Command.set([warehouse.id])]

    def test_copy_warehouse_does_not_share_locations(self):
        """`copy_data` carried the source's locations through, and only
        `create()` unconditionally overwriting them kept copies apart. The
        location fields are `copy=False` now, so the isolation is declared.
        """
        source = self.env["stock.warehouse"].create({"name": "Original", "code": "ORG"})
        duplicate = source.copy()
        for field in (
            "view_location_id",
            "lot_stock_id",
            "wh_input_stock_loc_id",
            "wh_qc_stock_loc_id",
            "wh_output_stock_loc_id",
            "wh_pack_stock_loc_id",
        ):
            self.assertTrue(duplicate[field])
            self.assertNotEqual(
                duplicate[field], source[field], "copies must not share %s" % field
            )

    def test_create_honours_explicit_locations(self):
        """An explicit location in `create()` vals is used, instead of being
        silently replaced by a freshly created one.
        """
        Location = self.env["stock.location"]
        view = Location.create({"name": "BYO view", "usage": "view"})
        stock = Location.create(
            {"name": "BYO stock", "usage": "internal", "location_id": view.id}
        )
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": "Bring your own",
                "code": "BYO",
                "view_location_id": view.id,
                "lot_stock_id": stock.id,
            }
        )
        self.assertEqual(warehouse.view_location_id, view)
        self.assertEqual(warehouse.lot_stock_id, stock)
        self.assertTrue(warehouse.wh_input_stock_loc_id)
        self.assertEqual(warehouse.wh_input_stock_loc_id.location_id, view)

    def test_partner_locations_raise_when_either_is_missing(self):
        """`_get_partner_locations` promises "customer or supplier"; it used to
        raise only when *both* were gone and otherwise handed callers an empty
        recordset to build rules from.
        """
        Warehouse = self.env["stock.warehouse"]
        customer_loc, supplier_loc = Warehouse._get_partner_locations()
        self.assertTrue(customer_loc)
        self.assertTrue(supplier_loc)

        self.env["ir.model.data"].search(
            [("module", "=", "stock"), ("name", "=", "stock_location_suppliers")]
        ).unlink()
        self.env.registry.clear_cache()
        self.env["stock.location"].with_context(active_test=False).search(
            [("usage", "=", "supplier")]
        ).usage = "transit"
        with self.assertRaises(UserError):
            Warehouse._get_partner_locations()

    def test_missing_location_rebuilt_for_current_steps(self):
        """A sub-location recreated by `_create_missing_locations` follows the
        warehouse's *own* steps. Resolving them from `default_get` gave a
        three-steps warehouse an archived Quality Control location, and nothing
        downstream repairs it: `_update_location_reception` only runs when
        `reception_steps` is in the write's vals.
        """
        warehouse = self.env["stock.warehouse"].create(
            {"name": "Rebuild", "code": "RBD", "reception_steps": "three_steps"}
        )
        self.assertTrue(warehouse.wh_qc_stock_loc_id.active)
        self.env.cr.execute(
            "UPDATE stock_warehouse SET wh_qc_stock_loc_id = NULL WHERE id = %s",
            (warehouse.id,),
        )
        warehouse.invalidate_recordset(["wh_qc_stock_loc_id"])

        warehouse.write({"sequence": warehouse.sequence + 1})
        rebuilt = warehouse.with_context(active_test=False).wh_qc_stock_loc_id
        self.assertTrue(rebuilt)
        self.assertTrue(
            rebuilt.active,
            "a three-steps warehouse must not get an archived QC location",
        )

    def test_picking_type_sequences_are_unique_per_warehouse(self):
        """Every picking type a warehouse owns gets its own `sequence`, whatever
        modules are installed.

        `sequence` orders the Operations overview. It used to be allocated by a
        `(values, next_max_sequence)` cursor each override had to thread through
        `_get_picking_type_create_values`; three of the seven overrides in the
        tree returned the cursor they were *given* instead of the one `super()`
        handed back, so their types collided with base ones and nothing noticed.
        Allocation now follows the position in `_get_picking_type_codes`.
        """
        warehouse = self.env["stock.warehouse"].create({"name": "Seqs", "code": "SQU"})
        picking_types = (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search([("warehouse_id", "=", warehouse.id)])
        )
        codes = warehouse._get_picking_type_codes()
        self.assertEqual(
            len(picking_types),
            len(codes),
            "every registered picking type must have been created",
        )
        self.assertEqual(
            set(picking_types.mapped("sequence_code")),
            set(codes.values()),
            "the created types must be exactly the registered ones",
        )
        sequences = picking_types.mapped("sequence")
        self.assertEqual(
            len(set(sequences)),
            len(sequences),
            "picking types share a sequence: %s"
            % sorted(
                zip(sequences, picking_types.mapped("sequence_code"), strict=True)
            ),
        )

    def test_picking_type_declarations_agree(self):
        """The four picking-type mappings are one declaration. A module that
        extends only some of them was silently ignored (create-only) or blew up
        with a bare KeyError deep in the create loop (update-only).
        """
        warehouse = self.warehouse_1
        codes = warehouse._get_picking_type_codes()
        self.assertEqual(set(warehouse._get_picking_type_create_values()), set(codes))
        self.assertEqual(set(warehouse._get_picking_type_update_values()), set(codes))
        self.assertEqual(set(warehouse._get_sequence_values()), set(codes))

        with self.assertRaises(ValueError):
            warehouse._check_picking_type_registry(
                {key: {} for key in codes},
                {key: {} for key in codes},
                {key: {} for key in codes},
                dict(codes, unregistered_type_id="ZZZ"),
            )

    def _drop_partner_location_xmlid(self, name):
        self.env["ir.model.data"].search(
            [("module", "=", "stock"), ("name", "=", name)]
        ).unlink()
        self.env.registry.clear_cache()

    def test_incoming_picking_type_survives_a_missing_supplier_xmlid(self):
        """`default_location_src_id` resolves through
        `stock.warehouse._get_partner_location`, which falls back to any
        supplier-usage location when the xml-id is gone.

        It used to be a bare `env.ref`, so a database that had lost the record
        died with `ValueError: External ID not found in the system` three frames
        below anything naming a location — in the middle of picking-type
        creation, which is where warehouse creation trips it.
        """
        supplier_loc = self.env.ref("stock.stock_location_suppliers")
        self._drop_partner_location_xmlid("stock_location_suppliers")

        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Fallback receipt",
                "code": "incoming",
                "sequence_code": "FBR",
                "warehouse_id": self.warehouse_1.id,
                "company_id": self.warehouse_1.company_id.id,
            }
        )
        self.assertEqual(picking_type.default_location_src_id, supplier_loc)

    def test_outgoing_picking_type_survives_a_missing_customer_xmlid(self):
        """Same for the outgoing type's destination."""
        customer_loc = self.env.ref("stock.stock_location_customers")
        self._drop_partner_location_xmlid("stock_location_customers")

        picking_type = self.env["stock.picking.type"].create(
            {
                "name": "Fallback delivery",
                "code": "outgoing",
                "sequence_code": "FBD",
                "warehouse_id": self.warehouse_1.id,
                "company_id": self.warehouse_1.company_id.id,
            }
        )
        self.assertEqual(picking_type.default_location_dest_id, customer_loc)

    def test_missing_supplier_location_is_reported_as_itself(self):
        """With no supplier location at all, creating an incoming type must fail
        with a UserError naming what is missing — not with the ValueError a bare
        `env.ref` raised from wherever the caller happened to stand.
        """
        self._drop_partner_location_xmlid("stock_location_suppliers")
        self.env["stock.location"].with_context(active_test=False).search(
            [("usage", "=", "supplier")]
        ).usage = "transit"

        with self.assertRaises(UserError):
            self.env["stock.picking.type"].create(
                {
                    "name": "Doomed receipt",
                    "code": "incoming",
                    "sequence_code": "DMR",
                    "warehouse_id": self.warehouse_1.id,
                    "company_id": self.warehouse_1.company_id.id,
                }
            )

    def test_partner_location_names_the_missing_side(self):
        """`_get_partner_location` is the one resolver; its error says which of
        the two is gone, where the pair's message could only say "or".
        """
        Warehouse = self.env["stock.warehouse"]
        self.assertTrue(Warehouse._get_partner_location("customer"))
        self.assertTrue(Warehouse._get_partner_location("supplier"))

        self._drop_partner_location_xmlid("stock_location_suppliers")
        self.env["stock.location"].with_context(active_test=False).search(
            [("usage", "=", "supplier")]
        ).usage = "transit"
        self.assertTrue(Warehouse._get_partner_location("customer"))
        with self.assertRaises(UserError) as caught:
            Warehouse._get_partner_location("supplier")
        self.assertIn("supplier", str(caught.exception))
