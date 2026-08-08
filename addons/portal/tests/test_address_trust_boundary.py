"""The address flow's trust boundary: which of its parameters a request may set.

``/my/address/submit`` splats the whole form into ``_create_or_update_address``,
whose signature also carries parameters that are *not* form fields. Two of them
decide something the customer does not get to decide:

* ``verify_address_values`` — a server-side trust switch. Only in-tree callers
  that have already validated the address themselves pass it
  (``website_event_sale``, ``website_appointment_sale``). Reached from the wire
  as an empty string it is falsy, and every check in ``_validate_address_values``
  was skipped.
* ``callback`` — echoed back as the JSON ``redirectUrl`` and rendered as the
  ``Discard`` link's ``href``. Unconstrained, it made any portal deployment an
  open redirector on an authenticated page (CWE-601).

Both are covered here at the HTTP layer, because both are only reachable there.
"""

from odoo.http import Request
from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestAddressTrustBoundary(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country = cls.env.ref("base.be")
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Trust Boundary Customer",
                "email": "trust.boundary@example.com",
                "phone": "+32 456 00 00 00",
                "street": "Rue du Test 1",
                "city": "Bruxelles",
                "zip": "1000",
                "country_id": cls.country.id,
            }
        )
        cls.user = cls.env["res.users"].create(
            {
                "login": "trust_boundary",
                "password": "trust_boundary",
                "partner_id": cls.partner.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        # A company the customer belongs to, plus a sibling billing address
        # under it. This is the shape that makes the bypass matter: commercial
        # fields (vat, company_name) live on the company and are shared with
        # every contact under it, so a sub-address must not be able to write
        # them -- `_enforce_commercial_field_propagation` pops them precisely
        # for that reason, and it only runs inside the validation the bypass
        # switched off.
        cls.company_partner = cls.env["res.partner"].create(
            {"name": "Trust Boundary Co", "is_company": True, "vat": "BE0477472701"}
        )
        cls.partner.parent_id = cls.company_partner
        cls.sibling_address = cls.env["res.partner"].create(
            {
                "name": "Trust Boundary Billing",
                "parent_id": cls.company_partner.id,
                "type": "invoice",
                "email": "billing@example.com",
                "phone": "+32 456 00 00 01",
                "street": "Rue du Test 2",
                "city": "Bruxelles",
                "zip": "1000",
                "country_id": cls.country.id,
            }
        )

    def _submit(self, **form_data):
        """POST the address form as the portal user, returning the JSON answer."""
        self.authenticate("trust_boundary", "trust_boundary")
        payload = {
            "partner_id": str(self.partner.id),
            "address_type": "billing",
            "use_delivery_as_billing": "true",
            "required_fields": "name,email",
            **form_data,
        }
        response = self.url_open(
            "/my/address/submit",
            data={**payload, "csrf_token": Request.csrf_token(self)},
        )
        response.raise_for_status()
        return response.json()

    def test_validation_runs_by_default(self):
        """Baseline: an empty name/e-mail is refused and nothing is written."""
        feedback = self._submit(name="", email="")

        self.assertNotIn("redirectUrl", feedback)
        self.assertIn("name", feedback["invalid_fields"])
        self.assertIn("email", feedback["invalid_fields"])
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.name, "Trust Boundary Customer")

    def test_verify_address_values_is_not_client_settable(self):
        """A falsy ``verify_address_values`` from the wire must not skip validation.

        The empty string is the payload that mattered: ``"false"`` and any other
        non-empty string are truthy in Python, so a truthiness test only ever let
        *this* value through — which is exactly what makes it easy to miss.
        """
        for hostile_value in ("", "0", "false", "False"):
            with self.subTest(verify_address_values=hostile_value):
                feedback = self._submit(
                    name="", email="", verify_address_values=hostile_value
                )

                self.assertNotIn(
                    "redirectUrl",
                    feedback,
                    "validation was skipped: the address was accepted",
                )
                self.assertIn("name", feedback["invalid_fields"])
                self.partner.invalidate_recordset()
                self.assertEqual(
                    self.partner.name,
                    "Trust Boundary Customer",
                    "an unvalidated write reached the database",
                )

    def test_email_format_still_checked_under_hostile_flag(self):
        """The e-mail syntax check is one of the guards the bypass turned off."""
        feedback = self._submit(
            name="Trust Boundary Customer",
            email="not-an-email",
            phone="+32 456 00 00 00",
            street="Rue du Test 1",
            city="Bruxelles",
            zip="1000",
            country_id=str(self.country.id),
            verify_address_values="",
        )

        self.assertIn("email", feedback["invalid_fields"])
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.email, "trust.boundary@example.com")

    def test_bypass_cannot_reach_the_shared_company_record(self):
        """The blast radius, not just the caller's own row.

        ``_create_or_update_address`` ends with a block that writes
        ``company_name`` straight onto ``commercial_partner_id`` -- the record
        shared by every contact of the company. It is only safe because
        ``_enforce_commercial_field_propagation`` has already popped
        ``company_name`` (and ``vat``) off a sub-address submission, and that
        runs inside the validation ``verify_address_values`` switched off. So
        the bypass was not merely "a customer can mangle their own name": from a
        sibling billing address it reached the company's own name and VAT.
        """
        self.authenticate("trust_boundary", "trust_boundary")
        response = self.url_open(
            "/my/address/submit",
            data={
                "partner_id": str(self.sibling_address.id),
                "address_type": "billing",
                "use_delivery_as_billing": "true",
                "required_fields": "name,email",
                "name": "Trust Boundary Billing",
                "email": "billing@example.com",
                "phone": "+32 456 00 00 01",
                "street": "Rue du Test 2",
                "city": "Bruxelles",
                "zip": "1000",
                "country_id": str(self.country.id),
                "company_name": "PWNED COMPANY",
                "vat": "BE0000000097",
                "verify_address_values": "",
                "csrf_token": Request.csrf_token(self),
            },
        )
        response.raise_for_status()

        self.company_partner.invalidate_recordset()
        self.sibling_address.invalidate_recordset()
        self.assertEqual(
            self.company_partner.name,
            "Trust Boundary Co",
            "a sub-address submission renamed the shared company record",
        )
        self.assertEqual(
            self.company_partner.vat,
            "BE0477472701",
            "a sub-address submission rewrote the company VAT",
        )

    def test_callback_cannot_leave_the_origin(self):
        """``redirectUrl`` is always a local path, whatever the form asked for."""
        valid_address = {
            "name": "Trust Boundary Customer",
            "email": "trust.boundary@example.com",
            "phone": "+32 456 00 00 00",
            "street": "Rue du Test 1",
            "city": "Bruxelles",
            "zip": "1000",
            "country_id": str(self.country.id),
        }
        for hostile_url in (
            "https://evil.example/phish",
            "//evil.example/phish",
            "http://evil.example",
            "/\\evil.example",
            "javascript:alert(1)",
        ):
            with self.subTest(callback=hostile_url):
                feedback = self._submit(**valid_address, callback=hostile_url)

                self.assertEqual(feedback.get("redirectUrl"), "/my/addresses")

    def test_callback_keeps_local_paths(self):
        """A legitimate in-app callback is passed through untouched."""
        feedback = self._submit(
            name="Trust Boundary Customer",
            email="trust.boundary@example.com",
            phone="+32 456 00 00 00",
            street="Rue du Test 1",
            city="Bruxelles",
            zip="1000",
            country_id=str(self.country.id),
            callback="/my/orders?page=2",
        )

        self.assertEqual(feedback.get("redirectUrl"), "/my/orders?page=2")

    def test_account_page_never_renders_an_offsite_discard_link(self):
        """``/my/account?redirect=`` reaches the ``Discard`` link's ``href``.

        The rendered page is served from the customer's own origin, so an
        attacker-chosen target there is a ready-made phishing pretext.
        """
        self.authenticate("trust_boundary", "trust_boundary")
        for hostile_url in ("https://evil.example/phish", "//evil.example/phish"):
            with self.subTest(redirect=hostile_url):
                body = self.url_open(
                    "/my/account", params={"redirect": hostile_url}
                ).text

                self.assertNotIn("evil.example", body)

    def test_account_page_keeps_a_local_discard_link(self):
        self.authenticate("trust_boundary", "trust_boundary")
        body = self.url_open("/my/account", params={"redirect": "/my/addresses"}).text

        self.assertIn('name="callback" value="/my/addresses"', body)
