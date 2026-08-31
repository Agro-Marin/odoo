from unittest import skip

from odoo import fields
from odoo.tests import Form, tagged

from odoo.addons.stock_account.tests.test_anglo_saxon_valuation_reconciliation_common import (
    ValuationReconciliationTestCommon,
)


@tagged("-at_install", "post_install")
@skip("Temporary to fast merge new valuation")
class TestLifoPrice(ValuationReconciliationTestCommon):
    def test_lifoprice(self):
        self.env.user.group_ids += self.env.ref("uom.group_uom")

        product_category_001 = self.env["product.category"].create(
            {
                "name": "Lifo Category",
                "removal_strategy_id": self.env.ref("stock.removal_lifo").id,
                "property_valuation": "real_time",
                "property_cost_method": "fifo",
            }
        )
        res_partner_3 = self.env["res.partner"].create({"name": "My Test Partner"})

        product_form = Form(self.env["product.product"])
        product_form.default_code = "LIFO"
        product_form.name = "LIFO Ice Cream"
        product_form.is_storable = True
        product_form.categ_id = product_category_001
        product_form.lst_price = 100.0
        product_form.uom_id = self.env.ref("uom.product_uom_kgm")
        product_lifo_icecream = product_form.save()

        product_lifo_icecream.standard_price = 70.0

        order_form = Form(self.env["purchase.order"])
        order_form.partner_id = res_partner_3
        with order_form.line_ids.new() as line:
            line.product_id = product_lifo_icecream
            line.product_qty = 10.0
            line.price_unit = 60.0
        purchase_order_lifo1 = order_form.save()

        order2_form = Form(self.env["purchase.order"])
        order2_form.partner_id = res_partner_3
        with order2_form.line_ids.new() as line:
            line.product_id = product_lifo_icecream
            line.product_qty = 30.0
            line.price_unit = 80.0
        purchase_order_lifo2 = order2_form.save()

        purchase_order_lifo1.action_confirm()

        self.assertEqual(purchase_order_lifo1.state, "done")

        purchase_order_lifo1.picking_ids[
            0
        ].move_ids.quantity = purchase_order_lifo1.picking_ids[0].move_ids.product_qty
        purchase_order_lifo1.picking_ids[0].move_ids.picked = True
        purchase_order_lifo1.picking_ids[0].button_validate()

        purchase_order_lifo2.action_confirm()

        purchase_order_lifo2.picking_ids[
            0
        ].move_ids.quantity = purchase_order_lifo2.picking_ids[0].move_ids.product_qty
        purchase_order_lifo2.picking_ids[0].move_ids.picked = True
        purchase_order_lifo2.picking_ids[0].button_validate()

        out_form = Form(self.env["stock.picking"])
        out_form.picking_type_id = self.company_data["default_warehouse"].out_type_id
        with out_form.move_ids.new() as move:
            move.product_id = product_lifo_icecream
            move.quantity = 20.0
            move.picked = True
            move.date = fields.Datetime.now()
        outgoing_lifo_shipment = out_form.save()

        outgoing_lifo_shipment.action_assign()

        outgoing_lifo_shipment.button_validate()

        self.assertEqual(
            outgoing_lifo_shipment.move_ids.mapped("value"),
            1400.0,
            "Stock move value should have been 1400 euro",
        )
