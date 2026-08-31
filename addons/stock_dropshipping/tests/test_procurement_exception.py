from odoo.tests import Form, common


class TestProcurementException(common.TransactionCase):
    def test_00_procurement_exception(self):
        self.env.user.group_ids += self.env.ref(
            "account.group_delivery_invoice_address"
        )
        self.env.user.group_ids += self.env.ref("stock.group_adv_location")

        res_partner_2 = self.env["res.partner"].create({"name": "My Test Partner"})
        res_partner_address = self.env["res.partner"].create(
            {
                "name": "My Test Partner Address",
                "parent_id": res_partner_2.id,
            }
        )

        product_form = Form(self.env["product.product"])
        product_form.name = "product with no seller"
        product_form.lst_price = 20.00
        product_with_no_seller = product_form.save()

        product_with_no_seller.standard_price = 70.0

        so_form = Form(self.env["sale.order"])
        so_form.partner_id = res_partner_2
        so_form.partner_invoice_id = res_partner_address
        so_form.partner_shipping_id = res_partner_address
        so_form.payment_term_id = self.env.ref(
            "account.account_payment_term_end_following_month"
        )
        with so_form.line_ids.new() as line:
            line.product_id = product_with_no_seller
            line.product_qty = 3
            line.route_ids = self.env.ref("stock_dropshipping.route_drop_shipping")
        sale_order_route_dropship01 = so_form.save()

        sale_order_route_dropship01.action_confirm()
        purchase = (
            self.env["purchase.order.line"]
            .search(
                [("sale_line_id", "=", sale_order_route_dropship01.line_ids.ids[0])]
            )
            .order_id
        )
        self.assertFalse(purchase, "No Purchase Quotation should be created")

        with Form(product_with_no_seller) as f:
            with f.seller_ids.new() as seller:
                seller.delay = 1
                seller.partner_id = res_partner_2
                seller.min_qty = 2.0

        sale_order_route_dropship02 = sale_order_route_dropship01.copy()
        sale_order_route_dropship02.action_confirm()

        purchase = (
            self.env["purchase.order.line"]
            .search(
                [("sale_line_id", "=", sale_order_route_dropship02.line_ids.ids[0])]
            )
            .order_id
        )

        self.assertTrue(purchase, "No Purchase Quotation is created")
