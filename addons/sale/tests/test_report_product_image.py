import base64

from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon

# 1x1 red PNG -- the smallest thing `image_1920` accepts.
RED_DOT = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
        "hKmMIQAAAABJRU5ErkJggg=="
    )
)


@tagged("post_install", "-at_install")
class TestSaleReportProductImage(SaleCommon):
    """The order report can print the product image, if the company asks for it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product.image_1920 = RED_DOT

    def _render_order_report(self):
        html, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", self.sale_order.ids
        )
        return html.decode()

    def test_product_image_is_absent_unless_the_company_asked_for_it(self):
        """The switch is off by default, so the report does not change for anybody."""
        self.assertFalse(self.env.company.display_product_images_on_so)

        self.assertNotIn("o_sale_report_product_image", self._render_order_report())

    def test_product_image_is_printed_when_the_company_asked_for_it(self):
        """With the switch on, each line prints its product image."""
        self.env.company.display_product_images_on_so = True

        html = self._render_order_report()

        self.assertIn("o_sale_report_product_image", html)
        self.assertIn("data:image/", html)

    def test_a_product_without_an_image_prints_nothing_extra(self):
        """The image is only printed for the products that carry one.

        `sale_order` sells `product` and `service_product`; only the first was
        given an image, so exactly one `<img>` reaches the report.
        """
        self.env.company.display_product_images_on_so = True
        self.assertFalse(self.service_product.image_128)

        self.assertEqual(
            self._render_order_report().count("o_sale_report_product_image"), 1
        )
