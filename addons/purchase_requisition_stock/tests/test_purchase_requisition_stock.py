from odoo import Command
from odoo.tests import Form

from odoo.addons.purchase_requisition.tests.common import TestPurchaseRequisitionCommon


class TestPurchaseRequisitionStock(TestPurchaseRequisitionCommon):
    def test_02_purchase_requisition_stock(self):
        unit = self.ref("uom.product_uom_unit")
        warehouse1 = self.env.ref("stock.warehouse0")
        route_buy = self.ref("purchase_stock.route_warehouse0_buy")
        route_mto = warehouse1.mto_pull_id.route_id.id
        vendor1 = self.env["res.partner"].create(
            {"name": "AAA", "email": "from.test@example.com"}
        )
        vendor2 = self.env["res.partner"].create(
            {"name": "BBB", "email": "from.test2@example.com"}
        )
        product_test = self.env["product.product"].create(
            {
                "name": "Usb Keyboard",
                "is_storable": True,
                "uom_id": unit,
                "route_ids": [(6, 0, [route_buy, route_mto])],
            }
        )
        supplier_info1 = self.env["product.supplierinfo"].create(
            {
                "product_id": product_test.id,
                "partner_id": vendor1.id,
                "price": 50,
            }
        )

        stock_location = self.env.ref("stock.stock_location_stock")
        customer_location = self.env.ref("stock.stock_location_customers")
        move1 = self.env["stock.move"].create(
            {
                "procure_method": "make_to_order",
                "location_id": stock_location.id,
                "location_dest_id": customer_location.id,
                "product_id": product_test.id,
                "product_uom_id": unit,
                "product_uom_qty": 10.0,
                "price_unit": 10,
            }
        )
        move1._action_confirm()

        purchase1 = self.env["purchase.order"].search([("partner_id", "=", vendor1.id)])
        self.assertEqual(
            purchase1.line_ids.price_unit,
            50,
            "The price on the purchase order is not the supplierinfo one",
        )

        line1 = (
            0,
            0,
            {
                "product_id": product_test.id,
                "product_qty": 18,
                "product_uom_id": product_test.uom_id.id,
                "price_unit": 50,
            },
        )
        requisition_blanket = self.env["purchase.requisition"].create(
            {
                "line_ids": [line1],
                "requisition_type": "blanket_order",
                "vendor_id": vendor2.id,
                "currency_id": self.env.user.company_id.currency_id.id,
            }
        )
        requisition_blanket.action_confirm()

        move2 = self.env["stock.move"].create(
            {
                "procure_method": "make_to_order",
                "location_id": stock_location.id,
                "location_dest_id": customer_location.id,
                "product_id": product_test.id,
                "product_uom_id": unit,
                "product_uom_qty": 10.0,
                "price_unit": 10,
            }
        )
        move2._action_confirm()

        self.assertEqual(purchase1.line_ids.product_qty, 20)

        supplier_info1.sequence = 2
        requisition_blanket.line_ids.supplier_info_ids.sequence = 1

        move3 = self.env["stock.move"].create(
            {
                "procure_method": "make_to_order",
                "location_id": stock_location.id,
                "location_dest_id": customer_location.id,
                "product_id": product_test.id,
                "product_uom_id": unit,
                "product_uom_qty": 10.0,
                "price_unit": 10,
            }
        )
        move3._action_confirm()

        purchase2 = self.env["purchase.order"].search(
            [
                ("partner_id", "=", vendor2.id),
                ("requisition_id", "=", requisition_blanket.id),
            ]
        )
        self.assertEqual(len(purchase2), 1)
        self.assertEqual(
            purchase2.line_ids.price_unit,
            50,
            "The price on the purchase order is not the blanquet order one",
        )

    def test_03_purchase_requisition_stock(self):

        unit = self.ref("uom.product_uom_unit")
        warehouse1 = self.env.ref("stock.warehouse0")
        route_buy = self.ref("purchase_stock.route_warehouse0_buy")
        route_mto = warehouse1.mto_pull_id.route_id.id
        vendor1 = self.env["res.partner"].create(
            {"name": "AAA", "email": "from.test@example.com"}
        )
        product_1 = self.env["product.product"].create(
            {
                "name": "product1",
                "is_storable": True,
                "uom_id": unit,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": vendor1.id,
                            "price": 50,
                        }
                    )
                ],
                "route_ids": [(6, 0, [route_buy, route_mto])],
            }
        )
        product_2 = self.env["product.product"].create(
            {
                "name": "product2",
                "is_storable": True,
                "uom_id": unit,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": vendor1.id,
                            "price": 50,
                        }
                    )
                ],
                "route_ids": [(6, 0, [route_buy, route_mto])],
            }
        )

        line1 = (
            0,
            0,
            {
                "product_id": product_1.id,
                "product_qty": 18,
                "product_uom_id": product_1.uom_id.id,
                "price_unit": 41,
            },
        )
        line2 = (
            0,
            0,
            {
                "product_id": product_2.id,
                "product_qty": 18,
                "product_uom_id": product_2.uom_id.id,
                "price_unit": 42,
            },
        )
        requisition_1 = self.env["purchase.requisition"].create(
            {
                "line_ids": [line1],
                "requisition_type": "blanket_order",
                "vendor_id": vendor1.id,
                "currency_id": self.env.user.company_id.currency_id.id,
            }
        )
        requisition_2 = self.env["purchase.requisition"].create(
            {
                "line_ids": [line2],
                "requisition_type": "blanket_order",
                "vendor_id": vendor1.id,
                "currency_id": self.env.user.company_id.currency_id.id,
            }
        )
        requisition_1.action_confirm()
        requisition_2.action_confirm()
        stock_location = self.env.ref("stock.stock_location_stock")
        customer_location = self.env.ref("stock.stock_location_customers")
        move1 = self.env["stock.move"].create(
            {
                "procure_method": "make_to_order",
                "location_id": stock_location.id,
                "location_dest_id": customer_location.id,
                "product_id": product_1.id,
                "product_uom_id": unit,
                "product_uom_qty": 10.0,
                "price_unit": 100,
            }
        )
        move2 = self.env["stock.move"].create(
            {
                "procure_method": "make_to_order",
                "location_id": stock_location.id,
                "location_dest_id": customer_location.id,
                "product_id": product_2.id,
                "product_uom_id": unit,
                "product_uom_qty": 10.0,
                "price_unit": 100,
            }
        )
        move1._action_confirm()
        move2._action_confirm()
        POL1 = (
            self.env["purchase.order.line"]
            .search([("product_id", "=", product_1.id)])
            .order_id
        )
        POL2 = (
            self.env["purchase.order.line"]
            .search([("product_id", "=", product_2.id)])
            .order_id
        )
        self.assertFalse(
            POL1 == POL2,
            "The two blanket orders should generate two purchase different purchase orders",
        )
        POL1.write(
            {
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": product_2.name,
                            "product_id": product_2.id,
                            "product_qty": 5.0,
                            "product_uom_id": product_2.uom_id.id,
                        },
                    )
                ]
            }
        )
        order_line = self.env["purchase.order.line"].search(
            [
                ("product_id", "=", product_2.id),
                ("product_qty", "=", 5.0),
            ]
        )
        self.assertEqual(
            order_line.price_unit,
            50,
            "The supplier info chosen should be the one without requisition id",
        )

    def test_04_purchase_requisition_stock(self):
        orig_po = self.env["purchase.order"].create(
            {
                "partner_id": self.res_partner_1.id,
                "picking_type_id": self.env["stock.picking.type"]
                .search([["code", "=", "outgoing"]], limit=1)
                .id,
                "dest_address_id": self.env["res.partner"]
                .create({"name": "delivery_partner"})
                .id,
            }
        )
        unit_price = 50
        po_form = Form(orig_po)
        with po_form.line_ids.new() as line:
            line.product_id = self.product_09
            line.product_qty = 5.0
            line.price_unit = unit_price
        po_form.save()

        action = orig_po.action_create_alternative()
        alt_po_wiz = Form(
            self.env["purchase.requisition.create.alternative"].with_context(
                **action["context"]
            )
        )
        alt_po_wiz.partner_ids = self.res_partner_1
        alt_po_wiz.copy_products = True
        alt_po_wiz = alt_po_wiz.save()
        alt_po_wiz.action_create_alternative()

        alt_po = orig_po.alternative_po_ids.filtered(lambda po: po.id != orig_po.id)
        self.assertEqual(
            orig_po.picking_type_id,
            alt_po.picking_type_id,
            "Alternative PO should have copied the picking type from original PO",
        )
        self.assertEqual(
            orig_po.dest_address_id,
            alt_po.dest_address_id,
            "Alternative PO should have copied the destination address from original PO",
        )
        self.assertEqual(
            orig_po.line_ids.product_id,
            alt_po.line_ids.product_id,
            "Alternative PO should have copied the product to purchase from original PO",
        )
        self.assertEqual(
            orig_po.line_ids.product_qty,
            alt_po.line_ids.product_qty,
            "Alternative PO should have copied the qty to purchase from original PO",
        )
        self.assertEqual(
            len(alt_po.alternative_po_ids),
            2,
            "Newly created PO should be auto-linked to itself and original PO",
        )

        action = alt_po.action_confirm()
        warning_wiz = Form(
            self.env["purchase.requisition.alternative.warning"].with_context(
                **action["context"]
            )
        )
        warning_wiz = warning_wiz.save()
        self.assertEqual(
            len(warning_wiz.alternative_po_ids),
            1,
            "POs not in a RFQ status should not be listed as possible to cancel",
        )
        warning_wiz.action_cancel_alternatives()
        self.assertEqual(
            orig_po.state, "cancel", "Original PO should have been cancelled"
        )

    def test_05_move_dest_links_alternatives(self):
        wh = self.env.ref("stock.warehouse0")
        buy_route_id = self.ref("purchase_stock.route_warehouse0_buy")
        vendor_1 = self.env["res.partner"].create({"name": "Vendor 1"})
        vendor_2 = self.env["res.partner"].create({"name": "Vendor 2"})
        product = self.env["product.product"].create(
            {
                "name": "Test product",
                "is_storable": True,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": vendor_1.id,
                            "price": 10.0,
                            "delay": 0,
                        }
                    )
                ],
                "route_ids": [Command.set([buy_route_id])],
            }
        )

        grp_multi_loc = self.env.ref("stock.group_stock_multi_locations")
        grp_multi_step_rule = self.env.ref("stock.group_adv_location")
        self.env.user.write({"group_ids": [(3, grp_multi_loc.id)]})
        self.env.user.write({"group_ids": [(3, grp_multi_step_rule.id)]})
        wh.reception_steps = "two_steps"

        self.env["stock.warehouse.orderpoint"].create(
            {
                "name": "RR for %s" % product.name,
                "warehouse_id": wh.id,
                "location_id": wh.lot_stock_id.id,
                "product_id": product.id,
                "product_min_qty": 1,
                "product_max_qty": 10,
            }
        )
        self.env["stock.scheduler"].run()
        int_move = self.env["stock.move"].search([("product_id", "=", product.id)])
        self.assertFalse(int_move)
        orig_po = self.env["purchase.order"].search([("partner_id", "=", vendor_1.id)])
        self.assertEqual(len(orig_po.ids), 1, "Only one PO should have been generated.")
        action = orig_po.action_create_alternative()
        alt_po_wizard = Form(
            self.env["purchase.requisition.create.alternative"].with_context(
                **action["context"]
            )
        )
        alt_po_wizard.partner_ids = vendor_2
        alt_po_wizard.copy_products = True
        alt_po_wizard = alt_po_wizard.save()
        alt_po_wizard.action_create_alternative()
        alt_po = orig_po.alternative_po_ids.filtered(lambda po: po.id != orig_po.id)
        self.assertEqual(
            len(orig_po.alternative_po_ids),
            2,
            "Base PO should be linked with the alternative PO.",
        )
        warning_wizard = Form.from_action(self.env, alt_po.action_confirm()).save()
        warning_wizard.action_cancel_alternatives()
        self.assertEqual(
            orig_po.state, "cancel", "Original PO should have been cancelled."
        )
        self.assertEqual(
            alt_po.state, "done", "Alternative PO should have been confirmed."
        )
        in_picking = alt_po.picking_ids
        self.assertEqual(
            in_picking.picking_type_id.code,
            "incoming",
            "Must be the reception picking.",
        )
        in_picking.move_ids.quantity = 10
        in_picking.move_ids.picked = True
        in_picking.button_validate()
        int_move = self.env["stock.move"].search(
            [
                ("product_id", "=", product.id),
                ("location_dest_id", "=", wh.lot_stock_id.id),
            ]
        )
        self.assertEqual(
            int_move.quantity,
            10,
            "Quantity should be reserved in the original internal move.",
        )
        self.assertEqual(
            int_move.move_orig_ids.id,
            in_picking.move_ids.id,
            "Both moves should be correctly chained together.",
        )

    def test_group_id_alternative_po(self):
        orig_po = self.env["purchase.order"].create(
            {
                "partner_id": self.res_partner_1.id,
            }
        )
        action = orig_po.action_create_alternative()
        alt_po_wizard_form = Form(
            self.env["purchase.requisition.create.alternative"].with_context(
                **action["context"]
            )
        )
        alt_po_wizard_form.partner_ids = self.res_partner_1
        alt_po_wizard_form.copy_products = True
        alt_po_wizard = alt_po_wizard_form.save()
        alt_po_id = alt_po_wizard.action_create_alternative()["res_id"]
        alt_po = self.env["purchase.order"].browse(alt_po_id)
        self.assertEqual(alt_po.reference_ids, orig_po.reference_ids)
