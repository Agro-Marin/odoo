"""Tests for the geocoder provider dispatch and address handling."""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGeocoder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Geocoder = cls.env["base.geocoder"]
        cls.osm_provider = cls.env["base.geo_provider"].create(
            {"tech_name": "openstreetmap", "name": "OSM test"}
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "base_geolocalize.geo_provider", str(cls.osm_provider.id)
        )

    def test_query_address_joins_non_empty_parts(self):
        """The default query string joins only the provided fields."""
        query = self.Geocoder.geo_query_address(
            street="Av. Reforma 1", city="CDMX", country="Mexico"
        )
        self.assertIn("Av. Reforma 1", query)
        self.assertIn("CDMX", query)
        self.assertIn("Mexico", query)

    def test_unknown_provider_rejected(self):
        """An unimplemented provider raises a UserError (negative)."""
        bogus = self.env["base.geo_provider"].create(
            {"tech_name": "not_a_provider", "name": "Bogus"}
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "base_geolocalize.geo_provider", str(bogus.id)
        )
        with self.assertRaises(UserError):
            self.Geocoder.geo_find("anywhere")

    def test_openstreetmap_parses_coordinates(self):
        """A nominatim payload maps to a (lat, lon) float tuple."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [{"lat": "19.4326", "lon": "-99.1332"}]
        with patch("requests.get", return_value=response):
            coordinates = self.Geocoder.geo_find("CDMX, Mexico")
        self.assertEqual(coordinates, (19.4326, -99.1332))

    def test_openstreetmap_empty_address_returns_none(self):
        """An empty address never calls the provider (boundary)."""
        self.assertIsNone(self.Geocoder._call_openstreetmap(""))

    def test_no_result_degrades_to_none(self):
        """An empty provider result makes geo_find return None (boundary)."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = []
        with patch("requests.get", return_value=response):
            self.assertIsNone(self.Geocoder.geo_find("nowhere at all"))

    def test_reverse_guard_blocks_in_tests(self):
        """The reverse lookup refuses to call OSM in test mode (guard)."""
        with self.assertRaises(UserError):
            self.Geocoder._call_openstreetmap_reverse(19.43, -99.13)
