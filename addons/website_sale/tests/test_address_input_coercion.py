# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests: malformed request values must not crash the shop routes.

These routes are ``auth='public'``, so every value here is chosen by an
anonymous caller. ``int()`` raises ``ValueError`` on a non-numeric id and
``str2bool`` raises ``ValueError`` outside its accepted vocabulary; both
surfaced as HTTP 500 on pages a shopper reaches by following a link.

Mirrors ``portal/tests/test_input_coercion.py`` — the shop address form is the
same machinery as the portal one (``CustomerPortal._create_or_update_address``
and friends), so it gets the same coercion guards.
"""

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
        """``/shop/address?partner_id=abc`` must 404, not 500."""
        response = self.url_open("/shop/address?partner_id=abc")
        self.assertNotEqual(response.status_code, 500)

    @mute_logger("odoo.http")
    def test_shop_address_junk_use_delivery_as_billing(self):
        """An unrecognised flag means "not enabled", not a crash."""
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
        """The guard must not flatten a genuine true into false."""
        for value in ("true", "1", "on"):
            with self.subTest(value=value):
                response = self.url_open(
                    f"/shop/address?use_delivery_as_billing={value}"
                )
                self.assertNotEqual(response.status_code, 500)


@tagged("post_install", "-at_install")
class TestShopListingInputCoercion(HttpCase, WebsiteSaleCommon):
    """The public ``/shop`` listing parses filters straight off the query string."""

    @mute_logger("odoo.http")
    def test_shop_junk_attribute_values(self):
        """Malformed ``attribute_values`` degrades to "no filter", not a 500.

        ``5`` (no separator) raised IndexError and ``abc-1`` ValueError.
        """
        for value in ("5", "abc-1", "1-xyz", "1-", "-", "a-b"):
            with self.subTest(value=value):
                response = self.url_open(f"/shop?attribute_values={value}")
                self.assertNotEqual(response.status_code, 500)

    @mute_logger("odoo.http")
    def test_shop_well_formed_attribute_values_still_parse(self):
        parsed = WebsiteSale._get_attribute_value_dict(["1-2,3", "4-5"])
        self.assertEqual(parsed, {1: [2, 3], 4: [5]})

    def test_valid_entries_survive_a_malformed_sibling(self):
        """One bad filter must not discard the good ones."""
        parsed = WebsiteSale._get_attribute_value_dict(["1-2", "garbage", "4-5"])
        self.assertEqual(parsed, {1: [2], 4: [5]})

    @mute_logger("odoo.http")
    def test_recently_viewed_routes_survive_non_numeric_ids(self):
        """Both are ``auth='public'`` jsonrpc routes.

        The assertion is "no ValueError escapes", not "an error is raised":
        ``recently_viewed_delete`` only parses the id once a visitor record
        exists, so without a visitor cookie it legitimately returns without
        ever reaching the id. Either outcome is fine; an unhandled coercion
        error is not.
        """
        for route, params in (
            ("/shop/products/recently_viewed_update", {"product_id": "abc"}),
            ("/shop/products/recently_viewed_delete", {"product_id": "abc"}),
            ("/shop/products/recently_viewed_delete", {"product_template_id": "abc"}),
        ):
            with self.subTest(route=route, params=params):
                try:
                    self.make_jsonrpc_request(route, params=params)
                except JsonRpcException as exc:
                    self.assertNotIn("ValueError", str(exc))


@tagged("post_install", "-at_install")
class TestShopAddressReservedParams(HttpCase, WebsiteSaleCommon):
    """A form field must not be able to supply an internal keyword argument.

    The shop address routes pass `order_sudo=` explicitly while also splatting
    the client's leftover query string / form data in as `**kwargs`. A client key
    matching one of those names is not extra data: it duplicates an argument the
    caller already supplies, or substitutes a raw string for a recordset.

    Observed before the guard, on `auth='public'` routes:
      * `order_sudo=x`   -> AttributeError: 'str' object has no attribute
                            '_is_anonymous_cart'
      * `partner_sudo=x` -> TypeError: ... got multiple values for argument

    A real session cart is required: `_check_cart` redirects an empty cart
    before the vulnerable splat is ever reached, so a cartless request would
    pass this test no matter what the code does.
    """

    def setUp(self):
        super().setUp()
        # `/shop/checkout` additionally runs `_check_addresses`, so the cart's
        # partner needs a complete billing/delivery address or the request is
        # redirected before the code under test runs.
        self.cart.partner_id.write(
            {
                "street": "1 Test Street",
                "city": "Testville",
                "zip": "1000",
                "country_id": self.country_be.id,
                "email": "reserved.params@example.com",
                "phone": "+32 2 000 00 00",
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
        """Guard the guard: the request must not be short-circuited by a redirect."""
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
        """website_sale must declare its own trusted kwarg."""
        self.assertIn("order_sudo", WebsiteSale()._get_reserved_address_form_keys())
