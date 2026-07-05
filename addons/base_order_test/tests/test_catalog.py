from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestCatalog(BaseOrderTestCase):
    def test_catalog_domain_includes_ok_field(self):
        order = self._make_order()

        domain = order._get_product_catalog_domain()

        # test model's hook returns "sale_ok"
        self.assertIn(("sale_ok", "=", True), list(domain))

    def test_add_extra_context_has_common_keys(self):
        order = self._make_order()

        ctx = order._get_action_add_from_catalog_extra_context()

        for key in (
            "product_catalog_currency_id",
            "product_catalog_digits",
            "show_sections",
        ):
            self.assertIn(key, ctx)

    def test_update_existing_line_quantity(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=1.0)

        order._update_order_line_info(self.product.id, 4.0)

        self.assertEqual(line.product_qty, 4.0)

    def test_update_zero_quantity_removes_line_in_draft(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=2.0)

        price = order._update_order_line_info(self.product.id, 0.0)

        self.assertFalse(line.exists())
        self.assertEqual(price, self.product.list_price)

    def test_catalog_lines_data_empty_recordset(self):
        data = self.env["base.order.test.line"]._get_product_catalog_lines_data()

        self.assertEqual(data, {"quantity": 0})

    def test_catalog_lines_data_single_line(self):
        line = self._make_line(product_qty=3.0, price_unit=42.0)

        data = line._get_product_catalog_lines_data()

        self.assertEqual(data["quantity"], 3.0)
        self.assertEqual(data["price"], 42.0)
        self.assertFalse(data["readOnly"])

    def test_catalog_lines_data_multi_line_aggregates_quantity(self):
        order = self._make_order()
        lines = self._make_line(order=order, product_qty=2.0) + self._make_line(
            order=order, product_qty=5.0
        )

        data = lines._get_product_catalog_lines_data()

        self.assertEqual(data["quantity"], 7.0)
        self.assertTrue(data["readOnly"])
