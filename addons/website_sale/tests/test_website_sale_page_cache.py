from unittest.mock import MagicMock, patch

from odoo.tests import tagged

from odoo.addons.website_sale.tests.common import WebsiteSaleCommon


@tagged("post_install", "-at_install")
class TestWebsiteSalePageCache(WebsiteSaleCommon):
    def test_post_process_response_from_cache_without_cart_markup(self):
        # Regression test: cached HTML rendered without the `my_cart_quantity` <sup> markup
        # (e.g. a stripped/custom header) must not crash `_post_process_response_from_cache`
        # even when the session carries a nonzero cart quantity.
        website_page_cls = type(self.env["website.page"])
        base_website_page_cls = next(
            cls
            for cls in website_page_cls.__mro__
            if cls.__module__ == "odoo.addons.website.models.website_page"
        )

        fake_response = MagicMock()
        fake_response.response = ["<html><body>No cart markup here</body></html>"]

        fake_request = MagicMock()
        fake_request.session = {
            "sale_order_id": self.empty_cart.id,
            "website_sale_cart_quantity": 2,
        }

        with patch.object(
            base_website_page_cls,
            "_post_process_response_from_cache",
            return_value=None,
        ):
            # Must not raise, unlike before the `if not cache_quantity: return` guard was added.
            self.env["website.page"]._post_process_response_from_cache(
                fake_request, fake_response
            )

        self.assertEqual(
            fake_response.response,
            ["<html><body>No cart markup here</body></html>"],
            "HTML without the cart-quantity markup must be left untouched",
        )
