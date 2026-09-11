from odoo import Command
from odoo.http import root
from odoo.tests import HttpCase, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.tests.common import WebsiteSaleCommon


@tagged("post_install", "-at_install")
class TestShopAddressInputCoercion(HttpCase, WebsiteSaleCommon):
    @mute_logger("odoo.http")
    def test_shop_address_non_numeric_partner_id(self):
        response = self.url_open("/shop/address?partner_id=abc")
        self.assertNotEqual(response.status_code, 500)

    @mute_logger("odoo.http")
    def test_shop_address_junk_use_delivery_as_billing(self):
        for value in ("xyz", "2", " true", "True%20"):
            with self.subTest(value=value):
                response = self.url_open(
                    f"/shop/address?use_delivery_as_billing={value}"
                )
                self.assertNotEqual(response.status_code, 500)

    @mute_logger("odoo.http")
    def test_shop_checkout_junk_try_skip_step(self):
        response = self.url_open("/shop/checkout?try_skip_step=xyz")
        self.assertNotEqual(response.status_code, 500)

    def test_shop_address_recognised_flag_still_honoured(self):
        for value in ("true", "1", "on"):
            with self.subTest(value=value):
                response = self.url_open(
                    f"/shop/address?use_delivery_as_billing={value}"
                )
                self.assertNotEqual(response.status_code, 500)


@tagged("post_install", "-at_install")
class TestShopListingInputCoercion(HttpCase, WebsiteSaleCommon):
    @mute_logger("odoo.http")
    def test_shop_junk_attribute_values(self):
        for value in ("5", "abc-1", "1-xyz", "1-", "-", "a-b"):
            with self.subTest(value=value):
                response = self.url_open(f"/shop?attribute_values={value}")
                self.assertNotEqual(response.status_code, 500)

    @mute_logger("odoo.http")
    def test_shop_well_formed_attribute_values_still_parse(self):
        parsed = WebsiteSale._get_attribute_value_dict(["1-2,3", "4-5"])
        self.assertEqual(parsed, {1: [2, 3], 4: [5]})

    def test_valid_entries_survive_a_malformed_sibling(self):
        parsed = WebsiteSale._get_attribute_value_dict(["1-2", "garbage", "4-5"])
        self.assertEqual(parsed, {1: [2], 4: [5]})

    @mute_logger("odoo.http")
    def test_recently_viewed_routes_survive_non_numeric_ids(self):
        for route, params in (
            ("/shop/products/recently_viewed_update", {"product_id": "abc"}),
            ("/shop/products/recently_viewed_delete", {"product_id": "abc"}),
            ("/shop/products/recently_viewed_delete", {"product_template_id": "abc"}),
        ):
            with self.subTest(route=route, params=params):
                try:
                    self.call_jsonrpc(route, params=params)
                except JsonRpcException as exc:
                    self.assertNotIn("ValueError", str(exc))


@tagged("post_install", "-at_install")
class TestShopAddressReservedParams(HttpCase, WebsiteSaleCommon):
    def setUp(self):
        super().setUp()
        self.cart.partner_id.write(
            {
                "street": "1 Test Street",
                "city": "Testville",
                "zip": "1000",
                "country_id": self.country_be.id,
                "email": "reserved.params@example.com",
                "phone_ids": [
                    Command.create({"number": "+32 2 000 00 00", "type": "landline"})
                ],
            }
        )
        self.cart.write(
            {
                "partner_invoice_id": self.cart.partner_id.id,
                "partner_shipping_id": self.cart.partner_id.id,
            }
        )
        session = self.authenticate(None, None)
        session["sale_order_id"] = self.cart.id
        root.session_store.save(session)

    def _reserved_keys(self):
        return sorted(WebsiteSale()._get_reserved_address_form_keys() | {"order_sudo"})

    def _assert_reaches_the_route(self, url):
        response = self.url_open(url, allow_redirects=False)
        self.assertEqual(
            response.status_code,
            200,
            f"{url} must render the page, else this test proves nothing "
            f"(got {response.status_code})",
        )

    @mute_logger("odoo.http")
    def test_shop_address_get_ignores_reserved_query_params(self):
        self._assert_reaches_the_route("/shop/address")
        for key in self._reserved_keys():
            with self.subTest(key=key):
                response = self.url_open(
                    f"/shop/address?{key}=x", allow_redirects=False
                )
                self.assertEqual(
                    response.status_code,
                    200,
                    f"query param {key!r} must not rebind an internal argument",
                )

    @mute_logger("odoo.http")
    def test_shop_checkout_ignores_reserved_query_params(self):
        self._assert_reaches_the_route("/shop/checkout")
        for key in self._reserved_keys():
            with self.subTest(key=key):
                response = self.url_open(
                    f"/shop/checkout?{key}=x", allow_redirects=False
                )
                self.assertEqual(
                    response.status_code,
                    200,
                    f"query param {key!r} must not rebind an internal argument",
                )

    def test_order_sudo_is_in_the_reserved_set(self):
        self.assertIn("order_sudo", WebsiteSale()._get_reserved_address_form_keys())
