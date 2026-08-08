"""Client form/query keys must not become internal keyword arguments.

The address routes forward every unrecognised client key onward as ``**kwargs``
-- the documented extension point that ``_handle_extra_form_data`` and the
l10n ``_validate_address_values`` overrides are built on. Those kwargs reach
``_validate_address_values``, ``_is_commercial_address``,
``_complete_address_values`` and ``res.partner._get_current_partner``, all of
which take ordinary named parameters.

A client key matching one of those names is not extra data: it either duplicates
an argument the caller already passes positionally, or it substitutes a raw
string for a value the callee expects to be a recordset. Both surfaced as HTTP
500 on routes any logged-in customer can reach.

Observed before the fix:
  * ``partner_sudo=x``  -> TypeError: CustomerPortal._create_or_update_address()
                           got multiple values for argument 'partner_sudo'
  * ``order_sudo=x``    -> AttributeError: 'str' object has no attribute
                           '_is_anonymous_cart'   (with website_sale installed)
"""

from odoo import http
from odoo.tests import HttpCase, tagged

from odoo.addons.portal.controllers.portal import CustomerPortal


@tagged("-at_install", "post_install")
class TestAddressParamInjection(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Injection Customer"})
        cls.env["res.users"].create(
            {
                "login": "portal_injection",
                "password": "portal_injection",
                "partner_id": cls.customer.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )

    def setUp(self):
        super().setUp()
        self.authenticate("portal_injection", "portal_injection")

    def _valid_payload(self, **extra):
        country = self.env.ref("base.us")
        # US is state_required, so a submission without one is rejected before
        # it ever reaches the code under test here.
        state = self.env["res.country.state"].search(
            [("country_id", "=", country.id)], limit=1
        )
        return {
            "csrf_token": http.Request.csrf_token(self),
            "name": "Injection Customer",
            "email": "injection.customer@example.com",
            "phone": "+1 555 0100",
            "street": "1 Test Street",
            "city": "Testville",
            "zip": "12345",
            "country_id": country.id,
            "state_id": state.id,
            "address_type": "billing",
            "callback": "/my/addresses",
            **extra,
        }

    # -- the reserved-name mechanism -------------------------------------

    def test_reserved_keys_are_dropped(self):
        """The sanitiser removes reserved names and keeps everything else."""
        controller = CustomerPortal()
        cleaned = controller._sanitize_client_address_params(
            {
                "partner_sudo": "x",
                "invalid_fields": "x",
                "error_messages": "x",
                "address_values": "x",
                "street": "1 Test Street",
                "some_custom_field": "keep me",
            }
        )
        self.assertEqual(
            cleaned, {"street": "1 Test Street", "some_custom_field": "keep me"}
        )

    def test_extension_point_is_preserved(self):
        """Genuine extra form data still reaches ``_handle_extra_form_data``."""
        seen = {}

        def spy(controller_self, extra_form_data, address_values):
            seen.update(extra_form_data)

        self.patch(CustomerPortal, "_handle_extra_form_data", spy)
        res = self.url_open(
            "/my/address/submit", data=self._valid_payload(my_custom_key="kept")
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            seen.get("my_custom_key"),
            "kept",
            "sanitising reserved names must not break the extra-form-data hook",
        )

    # -- the routes ------------------------------------------------------

    def test_submit_rejects_reserved_keys_without_crashing(self):
        """POST /my/address/submit survives every reserved name."""
        for key in sorted(CustomerPortal()._get_reserved_address_form_keys()):
            with self.subTest(key=key):
                res = self.url_open(
                    "/my/address/submit", data=self._valid_payload(**{key: "x"})
                )
                self.assertEqual(
                    res.status_code,
                    200,
                    f"client key {key!r} must not reach the internal kwargs",
                )

    def test_address_form_rejects_reserved_query_params(self):
        """GET /my/address survives every reserved name in the query string."""
        for key in sorted(CustomerPortal()._get_reserved_address_form_keys()):
            with self.subTest(key=key):
                res = self.url_open(f"/my/address?address_type=billing&{key}=x")
                self.assertEqual(
                    res.status_code,
                    200,
                    f"query param {key!r} must not reach the internal kwargs",
                )

    def test_order_sudo_is_never_client_supplied(self):
        """``order_sudo`` specifically -- website_sale's trusted kwarg.

        Named explicitly rather than looped from
        ``_get_reserved_address_form_keys``: that set is read off a bare
        ``CustomerPortal`` instance, whose class does not carry website_sale's
        override, while the *routed* controller does. This is the case that
        produced ``AttributeError: 'str' object has no attribute
        '_is_anonymous_cart'``, so it must be asserted directly.

        Skipped when website_sale is absent -- without it there is no
        ``order_sudo`` parameter to shadow.
        """
        if "website_sale" not in self.env["ir.module.module"]._installed():
            self.skipTest("website_sale not installed")
        res = self.url_open(
            "/my/address/submit", data=self._valid_payload(order_sudo="pwned")
        )
        self.assertEqual(res.status_code, 200)
        res = self.url_open("/my/address?address_type=billing&order_sudo=pwned")
        self.assertEqual(res.status_code, 200)

    def test_address_list_rejects_reserved_query_params(self):
        """GET /my/addresses splats its query string into ``_prepare_address_data``."""
        for key in sorted(CustomerPortal()._get_reserved_address_form_keys()):
            with self.subTest(key=key):
                res = self.url_open(f"/my/addresses?{key}=x")
                self.assertEqual(
                    res.status_code,
                    200,
                    f"query param {key!r} must not rebind an internal argument",
                )

    def test_baseline_submit_still_works(self):
        """Sanity: the same payload without injection is accepted."""
        res = self.url_open("/my/address/submit", data=self._valid_payload())
        self.assertEqual(res.status_code, 200)
        self.assertIn("redirectUrl", res.text)
