from datetime import timedelta

from odoo import Command
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("-at_install", "post_install")
class TestPurchaseStockAdvanced(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create(
            {
                "name": "Test Vendor",
            }
        )

        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Test Customer",
            }
        )

        cls.buy_route = cls.env.ref("purchase_stock.route_warehouse0_buy")
        cls.buy_route.product_selectable = True

        cls.product_storable = cls.env["product.product"].create(
            {
                "name": "Storable Product",
                "is_storable": True,
                "route_ids": [Command.set(cls.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": cls.vendor.id,
                            "min_qty": 1,
                            "price": 100,
                            "delay": 5,
                        }
                    )
                ],
            }
        )

        cls.product_no_vendor = cls.env["product.product"].create(
            {
                "name": "Product Without Vendor",
                "is_storable": True,
                "route_ids": [Command.set(cls.buy_route.ids)],
            }
        )

    def test_dropship_purchase_flow(self):
        dropship_route = self.env["stock.route"].search(
            [
                ("name", "ilike", "dropship"),
            ],
            limit=1,
        )

        if not dropship_route:
            supplier_loc = self.env.ref("stock.stock_location_suppliers")
            customer_loc = self.env.ref("stock.stock_location_customers")
            dropship_route = self.env["stock.route"].create(
                {
                    "name": "Dropship",
                    "product_selectable": True,
                    "rule_ids": [
                        Command.create(
                            {
                                "name": "Dropship Rule",
                                "action": "buy",
                                "location_dest_id": customer_loc.id,
                                "location_src_id": supplier_loc.id,
                                "picking_type_id": self.env.ref(
                                    "stock.picking_type_in"
                                ).id,
                            }
                        )
                    ],
                }
            )

        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "dest_address_id": self.customer.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )

        self.assertEqual(
            po.dest_address_id, self.customer, "Dropship address should be set"
        )

        po.action_confirm()

        if po.picking_ids:
            picking = po.picking_ids[0]
            self.assertTrue(
                self.customer in (picking.partner_id, po.dest_address_id),
                "Dropship should deliver to customer",
            )

    def test_purchase_order_dest_address_changes_picking(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "dest_address_id": self.customer.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 5,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )

        po.action_confirm()

        self.assertEqual(po.dest_address_id, self.customer)

    def test_procurement_without_supplier_creates_notification(self):
        warehouse = self.env["stock.warehouse"].search(
            [
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )

        self.env["stock.warehouse.orderpoint"].create(
            {
                "warehouse_id": warehouse.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": self.product_no_vendor.id,
                "product_min_qty": 10,
                "product_max_qty": 20,
                "route_id": self.buy_route.id,
            }
        )

        self.env["stock.scheduler"].with_context(from_orderpoint=True).run()

        self.env["purchase.order.line"].search(
            [
                ("product_id", "=", self.product_no_vendor.id),
            ]
        )

    def test_procurement_with_invalid_supplier_min_qty(self):
        product_high_min = self.env["product.product"].create(
            {
                "name": "High Min Qty Product",
                "is_storable": True,
                "route_ids": [Command.set(self.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1000,
                            "price": 50,
                        }
                    )
                ],
            }
        )

        warehouse = self.env["stock.warehouse"].search(
            [
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )

        self.env["stock.warehouse.orderpoint"].create(
            {
                "warehouse_id": warehouse.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": product_high_min.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
                "route_id": self.buy_route.id,
            }
        )

        self.env["stock.scheduler"].run()

        self.env["purchase.order.line"].search(
            [
                ("product_id", "=", product_high_min.id),
            ]
        )

    def test_orderpoint_supplier_auto_route(self):
        product_no_route = self.env["product.product"].create(
            {
                "name": "Product No Route",
                "is_storable": True,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1,
                            "price": 75,
                        }
                    )
                ],
            }
        )

        warehouse = self.env["stock.warehouse"].search(
            [
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "warehouse_id": warehouse.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": product_no_route.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
            }
        )

        seller = product_no_route.seller_ids[0]
        orderpoint.supplier_id = seller

        self.assertEqual(
            orderpoint.route_id,
            self.buy_route,
            "Buy route should be auto-assigned when supplier is set",
        )

    def test_orderpoint_effective_vendor_computation(self):
        warehouse = self.env["stock.warehouse"].search(
            [
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "warehouse_id": warehouse.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": self.product_storable.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
                "route_id": self.buy_route.id,
            }
        )

        self.assertTrue(
            orderpoint.effective_vendor_id or orderpoint.supplier_id,
            "Effective vendor should be computed from product sellers",
        )

    def test_orderpoint_clear_supplier_on_route_change(self):
        warehouse = self.env["stock.warehouse"].search(
            [
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )

        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "warehouse_id": warehouse.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_id": self.product_storable.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
                "route_id": self.buy_route.id,
                "supplier_id": self.product_storable.seller_ids[0].id,
            }
        )

        mto_route = self.env["stock.route"].search(
            [
                ("name", "ilike", "make to order"),
            ],
            limit=1,
        )

        if mto_route:
            orderpoint.route_id = mto_route

    def test_transfer_state_no_picking(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )

        self.assertEqual(
            po.transfer_state,
            "no",
            "Transfer state should be 'no' before confirmation",
        )

    def _make_po(self, *quantities):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": qty,
                            "price_unit": 100,
                        }
                    )
                    for qty in quantities
                ],
            }
        )

    def test_transfer_state_over_done(self):
        po = self._make_po(10)
        po.action_confirm()

        picking = po.picking_ids[0]
        picking.move_ids.quantity = 12
        picking.move_ids.picked = True
        picking.button_validate()

        self.assertEqual(po.line_ids.transfer_state, "over done")
        self.assertEqual(po.transfer_state, "over done")

    def test_transfer_state_partial_when_one_line_of_two_is_done(self):
        po = self._make_po(10, 10)
        po.action_confirm()

        picking = po.picking_ids[0]
        first_move = picking.move_ids.filtered(
            lambda m: m.purchase_line_id == po.line_ids[0]
        )
        first_move.quantity = 10
        first_move.picked = True
        picking.with_context(skip_backorder=True).button_validate()

        self.assertEqual(po.line_ids[0].transfer_state, "done")
        self.assertEqual(po.line_ids[1].transfer_state, "to do")
        self.assertEqual(po.transfer_state, "partial")

    def test_transfer_state_forced_and_released(self):
        po = self._make_po(10)
        po.action_confirm()
        self.assertEqual(po.transfer_state, "to do")

        po.action_force_transfer_state()
        self.assertTrue(po.force_fully_delivered)
        self.assertEqual(po.transfer_state, "done")

        po.invalidate_recordset(["transfer_state"])
        self.assertEqual(po.transfer_state, "done")

        po.action_unforce_transfer_state()
        self.assertFalse(po.force_fully_delivered)
        self.assertEqual(po.transfer_state, "to do")

    def test_transfer_state_ignores_section_lines(self):
        po = self._make_po(10)
        po.write(
            {
                "line_ids": [
                    Command.create({"display_type": "line_section", "name": "Section"})
                ]
            }
        )
        po.action_confirm()

        section = po.line_ids.filtered("display_type")
        self.assertEqual(section.transfer_state, "no")
        self.assertEqual(po.transfer_state, "to do")

    def test_transfer_state_to_do(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        self.assertEqual(
            po.transfer_state,
            "to do",
            "Transfer state should be 'to do' after confirmation",
        )

    def test_transfer_state_done(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        for picking in po.picking_ids:
            picking.move_ids.quantity = 10
            picking.move_ids.picked = True
            picking.button_validate()

        self.assertEqual(
            po.transfer_state,
            "done",
            "Transfer state should be 'done' after all pickings complete",
        )

    def test_transfer_state_partial(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        picking = po.picking_ids[0]
        picking.move_ids.quantity = 5
        picking.move_ids.picked = True
        res = picking.button_validate()

        if (
            res
            and isinstance(res, dict)
            and res.get("res_model") == "stock.backorder.confirmation"
        ):
            backorder_wizard = (
                self.env["stock.backorder.confirmation"]
                .with_context(res["context"])
                .create({})
            )
            backorder_wizard.process()

        self.assertEqual(
            po.transfer_state, "partial", "Transfer state should be 'partial'"
        )

    def test_qty_transferred_after_receipt(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        self.assertEqual(
            po.line_ids[0].qty_transferred, 0, "Should be 0 before receipt"
        )

        picking = po.picking_ids[0]
        picking.move_ids.quantity = 10
        picking.move_ids.picked = True
        picking.button_validate()

        self.assertEqual(
            po.line_ids[0].qty_transferred, 10, "Should be 10 after full receipt"
        )

    def test_qty_to_transfer_computation(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        self.assertEqual(
            po.line_ids[0].qty_to_transfer, 10, "Should be 10 before receipt"
        )

        picking = po.picking_ids[0]
        picking.move_ids.quantity = 4
        picking.move_ids.picked = True
        res = picking.button_validate()

        if (
            res
            and isinstance(res, dict)
            and res.get("res_model") == "stock.backorder.confirmation"
        ):
            backorder_wizard = (
                self.env["stock.backorder.confirmation"]
                .with_context(res["context"])
                .create({})
            )
            backorder_wizard.process()

        self.assertEqual(
            po.line_ids[0].qty_to_transfer, 6, "Should be 6 after partial receipt"
        )

    def test_cancel_po_cancels_moves(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        picking = po.picking_ids[0]
        moves = picking.move_ids

        self.assertTrue(all(m.state not in ["done", "cancel"] for m in moves))

        po.action_cancel()

        self.assertTrue(
            all(m.state == "cancel" for m in moves), "All moves should be cancelled"
        )

    def test_partial_move_cancellation_propagation(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_storable.id,
                            "product_qty": 10,
                            "price_unit": 100,
                            "propagate_cancel": True,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        self.assertTrue(po.line_ids[0].propagate_cancel)


@tagged("-at_install", "post_install")
class TestPurchaseStockLeadTime(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create(
            {
                "name": "Lead Time Vendor",
            }
        )
        cls.buy_route = cls.env.ref("purchase_stock.route_warehouse0_buy")

    def test_date_commitment_includes_supplier_delay(self):
        product = self.env["product.product"].create(
            {
                "name": "Product With Delay",
                "is_storable": True,
                "route_ids": [Command.set(self.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1,
                            "price": 100,
                            "delay": 10,
                        }
                    )
                ],
            }
        )

        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": 5,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )

        expected_min_date = po.date_order + timedelta(days=10)
        self.assertGreaterEqual(
            po.line_ids[0].date_commitment,
            expected_min_date,
            "Date planned should include supplier delay",
        )

    def test_date_commitment_with_zero_delay(self):
        product = self.env["product.product"].create(
            {
                "name": "Product No Delay",
                "is_storable": True,
                "route_ids": [Command.set(self.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1,
                            "price": 100,
                            "delay": 0,
                        }
                    )
                ],
            }
        )

        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": 5,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )

        delta = po.line_ids[0].date_commitment - po.date_order
        self.assertLessEqual(
            delta.days, 1, "Date planned should be same day with zero delay"
        )


@tagged("-at_install", "post_install")
class TestPurchaseStockPricing(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create(
            {
                "name": "Pricing Vendor",
            }
        )
        cls.buy_route = cls.env.ref("purchase_stock.route_warehouse0_buy")

    def test_stock_move_price_from_po_line(self):
        product = self.env["product.product"].create(
            {
                "name": "Priced Product",
                "is_storable": True,
                "route_ids": [Command.set(self.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1,
                            "price": 75,
                        }
                    )
                ],
            }
        )

        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": 10,
                            "price_unit": 80,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        move = po.picking_ids.move_ids[0]
        self.assertEqual(
            move.purchase_line_id.price_unit,
            80,
            "Move should reference PO line with correct price",
        )

    def test_qty_transferred_with_returns(self):
        product = self.env["product.product"].create(
            {
                "name": "Return Test Product",
                "is_storable": True,
                "route_ids": [Command.set(self.buy_route.ids)],
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.vendor.id,
                            "min_qty": 1,
                            "price": 100,
                        }
                    )
                ],
            }
        )

        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": 10,
                            "price_unit": 100,
                        }
                    ),
                ],
            }
        )
        po.action_confirm()

        picking = po.picking_ids[0]
        picking.move_ids.quantity = 10
        picking.move_ids.picked = True
        picking.button_validate()

        self.assertEqual(po.line_ids[0].qty_transferred, 10)

        return_wizard = (
            self.env["stock.return.picking"]
            .with_context(
                active_id=picking.id,
                active_model="stock.picking",
            )
            .create({})
        )
        return_wizard.product_return_moves.quantity = 3
        return_result = return_wizard.action_create_returns()

        return_picking = self.env["stock.picking"].browse(return_result["res_id"])
        return_picking.move_ids.quantity = 3
        return_picking.move_ids.picked = True
        return_picking.button_validate()

        self.assertEqual(
            po.line_ids[0].qty_transferred,
            7,
            "qty_transferred should be 7 after returning 3",
        )
