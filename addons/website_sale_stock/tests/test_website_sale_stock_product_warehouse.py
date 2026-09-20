from odoo.tests import tagged

from odoo.addons.product.tests.test_product_attribute_value_config import (
    TestProductAttributeValueCommon,
)
from odoo.addons.website_sale.tests.common import MockRequest
from odoo.addons.website_sale_stock.tests.common import WebsiteSaleStockCommon


@tagged("post_install", "-at_install")
class TestWebsiteSaleStockProductWarehouse(
    TestProductAttributeValueCommon, WebsiteSaleStockCommon
):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Company C"})
        cls.env.user.company_id = cls.company
        cls.website = cls.env["website"].create({"name": "Website Company C"})
        cls.website.company_id = cls.company

        cls.warehouse_1 = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)]
        )
        cls.warehouse_2 = cls._create_warehouse()
        cls.product_A = cls._create_product()
        cls.product_B = cls._create_product()
        cls.test_env = (
            cls.env["base"]
            .with_context(
                website_id=cls.website.id,
                website_sale_stock_get_quantity=True,
            )
            .env
        )

        cls._add_product_qty_to_wh(
            cls.product_A.id, 10, cls.warehouse_1.lot_stock_id.id
        )
        cls._add_product_qty_to_wh(
            cls.product_A.id, 15, cls.warehouse_2.lot_stock_id.id
        )

        cls._add_product_qty_to_wh(
            cls.product_B.id, 10, cls.warehouse_2.lot_stock_id.id
        )

    def test_get_combination_info_free_qty_when_warehouse_is_set(self):
        self.website.warehouse_id = self.warehouse_2
        test_env = self.test_env
        with MockRequest(test_env, website=self.website.with_env(test_env)):
            combination_info = self.product_A.with_env(
                test_env
            )._get_combination_info_variant()
            self.assertEqual(combination_info["qty_free"], 15)
        with MockRequest(test_env, website=self.website.with_env(test_env)):
            combination_info = self.product_B.with_env(
                test_env
            )._get_combination_info_variant()
            self.assertEqual(combination_info["qty_free"], 10)

    def test_get_combination_info_free_qty_when_no_warehouse_is_set(self):
        self.website.warehouse_id = False
        test_env = self.test_env
        with MockRequest(test_env, website=self.website.with_env(test_env)):
            combination_info = self.product_A.with_env(
                test_env
            )._get_combination_info_variant()
        self.assertEqual(combination_info["qty_free"], 25)
        with MockRequest(test_env, website=self.website.with_env(test_env)):
            combination_info = self.product_B.with_env(
                test_env
            )._get_combination_info_variant()
        self.assertEqual(combination_info["qty_free"], 10)

    def test_02_update_cart_with_multi_warehouses(self):

        so = self.env["sale.order"].create(
            {
                "website_id": self.website.id,
                "partner_id": self.env.user.partner_id.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": self.product_A.name,
                            "product_id": self.product_A.id,
                            "product_qty": 5,
                            "price_unit": self.product_A.list_price,
                        },
                    )
                ],
            }
        )

        with MockRequest(self.env, website=self.website, sale_order_id=so.id) as req:
            website_so = req.cart
            self.assertEqual(website_so, so)
            self.assertEqual(
                website_so.line_ids.product_id.qty_available_virtual,
                25,
                "This quantity should be based on all warehouses.",
            )

            values = so._cart_update_line_quantity(line_id=so.line_ids.id, quantity=30)
            self.assertTrue(values.get("warning", False))
            self.assertEqual(values.get("quantity"), 25)
