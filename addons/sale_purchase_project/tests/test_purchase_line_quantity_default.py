from odoo.tests import tagged

from odoo.addons.sale_purchase.tests.common import TestSalePurchaseCommon


@tagged("-at_install", "post_install")
class TestPurchaseLineQuantityDefault(TestSalePurchaseCommon):
    def test_omitted_quantity_takes_the_sale_line_quantity(self):
        order = self.env["sale.order"].create({"partner_id": self.partner_a.id})
        line = self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.service_purchase_1.id,
                "product_qty": 4,
                "tax_ids": False,
            }
        )
        purchase_order = self.env["purchase.order"].create(
            {"partner_id": self.partner_vendor_service.id}
        )

        values = line._purchase_service_prepare_line_values(purchase_order)

        self.assertEqual(values["product_qty"], 4)
