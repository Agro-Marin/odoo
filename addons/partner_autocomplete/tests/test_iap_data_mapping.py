"""Tests for the IAP payload -> Odoo records mapping helpers."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIapDataMapping(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.us = cls.env.ref("base.us")

    def test_location_codes_resolve_country(self):
        """A country_code maps to the matching res.country reference."""
        data = self.Partner._iap_replace_location_codes({"country_code": "US"})
        self.assertEqual(data["country_id"]["id"], self.us.id)
        # the raw code is consumed out of the payload
        self.assertNotIn("country_code", data)

    def test_location_codes_resolve_state_within_country(self):
        """A state code resolves within the resolved country."""
        state = self.env["res.country.state"].search(
            [("country_id", "=", self.us.id)], limit=1
        )
        if not state:
            self.skipTest("no US states in this database")
        data = self.Partner._iap_replace_location_codes(
            {"country_code": "US", "state_code": state.code}
        )
        self.assertEqual(data["state_id"]["id"], state.id)

    def test_location_codes_unknown_country_left_alone(self):
        """An unresolvable country leaves no country_id (boundary)."""
        data = self.Partner._iap_replace_location_codes({"country_code": "ZZ"})
        self.assertNotIn("country_id", data)

    def test_language_code_maps_to_installed_lang(self):
        """A preferred_language maps to an installed res.lang code."""
        data = self.Partner._iap_replace_language_codes({"preferred_language": "en_US"})
        self.assertEqual(data.get("lang"), "en_US")

    def test_language_generic_fallback(self):
        """An unknown regional variant falls back to the generic language."""
        data = self.Partner._iap_replace_language_codes({"preferred_language": "en_ZZ"})
        # falls back to an installed en_* code (en_US in a default database).
        self.assertTrue(data.get("lang", "").startswith("en"))

    def test_format_data_company_chains_transformers(self):
        """_format_data_company applies the location and language mappings."""
        data = self.Partner._format_data_company(
            {"country_code": "US", "preferred_language": "en_US", "name": "ACME"}
        )
        self.assertEqual(data["country_id"]["id"], self.us.id)
        self.assertEqual(data["lang"], "en_US")
        self.assertEqual(data["name"], "ACME")
