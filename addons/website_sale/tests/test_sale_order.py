from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon
from odoo.addons.website_sale.tests.common import WebsiteSaleCommon


@tagged("post_install", "-at_install")
class TestSaleOrder(SaleCommon):
    def test_delivery_methods_match_order_company(self):
        company_1 = self.env["res.company"].create({"name": "Test Company 1"})
        company_2 = self.env["res.company"].create({"name": "Test Company 2"})
        product_delivery_1 = self.env["product.product"].create(
            {
                "name": "Delivery Product 1",
                "type": "service",
                "company_id": company_1.id,
            }
        )
        product_delivery_2 = self.env["product.product"].create(
            {
                "name": "Delivery Product 2",
                "type": "service",
                "company_id": company_2.id,
            }
        )
        delivery_1 = self.env["delivery.carrier"].create(
            {
                "name": "Delivery 1",
                "delivery_type": "fixed",
                "product_id": product_delivery_1.id,
                "is_published": True,
            }
        )
        delivery_2 = self.env["delivery.carrier"].create(
            {
                "name": "Delivery 2",
                "delivery_type": "fixed",
                "product_id": product_delivery_2.id,
                "is_published": True,
            }
        )
        sale_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "company_id": company_1.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                        }
                    )
                ],
            }
        )
        available_dms = sale_order._get_delivery_methods()
        self.assertIn(delivery_1, available_dms)
        self.assertNotIn(delivery_2, available_dms)


@tagged("post_install", "-at_install")
class TestSaleOrderCheckComboQuantities(WebsiteSaleCommon):
    def test_check_combo_quantities_clamps_and_warns_without_website_sale_stock(self):
        # Regression test: `_check_combo_quantities` must work with only `website_sale`
        # installed. It previously called `_set_shop_warning_stock`, a method that existed
        # only in the (uninstalled here) `website_sale_stock` module, and would raise
        # AttributeError as soon as a combo's item quantities went out of sync.
        combo_item_1 = self._create_product(name="Combo Item 1")
        combo_item_2 = self._create_product(name="Combo Item 2")
        combo_main_line = self.empty_cart.line_ids.create(
            {
                "order_id": self.empty_cart.id,
                "product_id": self.product.id,
                "product_qty": 3,
            }
        )
        combo_item_line_1 = self.empty_cart.line_ids.create(
            {
                "order_id": self.empty_cart.id,
                "product_id": combo_item_1.id,
                "product_qty": 1,
                "linked_line_id": combo_main_line.id,
            }
        )
        combo_item_line_2 = self.empty_cart.line_ids.create(
            {
                "order_id": self.empty_cart.id,
                "product_id": combo_item_2.id,
                "product_qty": 1,
                "linked_line_id": combo_main_line.id,
            }
        )

        updated = self.empty_cart._check_combo_quantities(combo_main_line)

        self.assertTrue(
            updated, "Mismatched combo item quantities must be reported as updated"
        )
        self.assertEqual(combo_main_line.product_qty, 1)
        self.assertEqual(combo_item_line_1.product_qty, 1)
        self.assertEqual(combo_item_line_2.product_qty, 1)
        self.assertTrue(
            combo_main_line.shop_warning,
            "A shop warning must be set on the clamped combo line",
        )


@tagged("post_install", "-at_install")
class TestSaleOrderCartHelpers(WebsiteSaleCommon):
    def test_is_cart_ready(self):
        self.assertTrue(self.cart._is_cart_ready())
        self.assertFalse(self.env["sale.order"]._is_cart_ready())

    def test_needs_customer_address_is_always_true(self):
        # Pinning regression test: per the method's own TODO, the address step cannot be
        # skipped today even when a product's tax doesn't otherwise require it.
        self.assertTrue(self.cart._needs_customer_address())

    def test_remove_invalid_cart_lines_drops_archived_products(self):
        line = self.cart.line_ids.filtered(lambda sol: sol.product_id == self.product)
        self.assertTrue(line)
        self.product.active = False

        self.cart._remove_invalid_cart_lines()

        self.assertFalse(
            self.cart.line_ids.filtered(lambda sol: sol.product_id == self.product),
            "The line referencing the archived product must be removed",
        )

    def test_sync_cart_after_update_removes_delivery_for_services_only_cart(self):
        service_cart = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "website_id": self.website.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.service_product.id, "product_qty": 1}
                    )
                ],
            }
        )
        service_cart.set_delivery_line(self.carrier, 5.0)
        self.assertTrue(service_cart.line_ids.filtered("is_delivery"))

        service_cart._sync_cart_after_update()

        self.assertFalse(
            service_cart.line_ids.filtered("is_delivery"),
            "A services-only cart must not keep a delivery line",
        )

    def test_sync_cart_after_update_recomputes_rate_for_mixed_cart(self):
        self.cart.set_delivery_line(self.carrier, 5.0)
        with patch.object(
            type(self.carrier),
            "rate_shipment",
            return_value={"success": True, "price": 42.0},
        ):
            self.cart._sync_cart_after_update()

        delivery_line = self.cart.line_ids.filtered("is_delivery")
        self.assertTrue(delivery_line)
        self.assertEqual(delivery_line.price_unit, 42.0)
