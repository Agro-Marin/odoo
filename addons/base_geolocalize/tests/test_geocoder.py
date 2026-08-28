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

    def test_get_provider_falls_back_on_malformed_param(self):
        """A non-numeric `geo_provider` param degrades to the default provider
        instead of raising a bare ValueError."""
        self.env["ir.config_parameter"].sudo().set_param(
            "base_geolocalize.geo_provider", "not-a-number"
        )
        provider = self.Geocoder._get_provider()
        self.assertTrue(provider.exists())


@tagged("post_install", "-at_install")
class TestGeocoderEdges(TransactionCase):
    """Provider-specific query building, error paths and localisation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Geocoder = cls.env["base.geocoder"]

    def test_googlemap_query_reorders_comma_of_countries(self):
        """'X, Republic of'-style countries are flipped for Google queries."""
        query = self.Geocoder._geo_query_address_googlemap(
            city="Kinshasa", country="Congo, Democratic Republic of the"
        )
        self.assertIn("Democratic Republic of the Congo", query)
        self.assertNotIn("Congo,", query)

    def test_network_error_raises_query_error(self):
        """A requests failure surfaces as a UserError, never a raw exception."""
        with (
            patch("requests.get", side_effect=OSError("network down")),
            self.assertRaises(UserError),
        ):
            self.Geocoder._call_openstreetmap("Some address 123")

    def test_reverse_without_coordinates_returns_none(self):
        """Missing latitude/longitude short-circuits to None."""
        self.assertIsNone(self.Geocoder._call_openstreetmap_reverse(0, 0))

    def test_get_localisation_from_geoip(self):
        """A resolvable geoip fills 'city, country' without any HTTP call."""
        mexico = self.env.ref("base.mx")
        fake_request = MagicMock()
        fake_request.geoip.city.name = "Culiacán"
        fake_request.geoip.country_code = "MX"
        with patch(
            "odoo.addons.base_geolocalize.models.base_geocoder.request", fake_request
        ):
            result = self.Geocoder._get_localisation(24.8, -107.4)
        self.assertEqual(result, f"Culiacán, {mexico.name}")


@tagged("post_install", "-at_install")
class TestPartnerCoordinatesReset(TransactionCase):
    """Address edits invalidate stale partner coordinates."""

    def test_address_change_resets_coordinates(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Geo partner",
                "city": "Culiacán",
                "partner_latitude": 24.8,
                "partner_longitude": -107.4,
            },
        )
        partner.write({"city": "Mazatlán"})
        self.assertEqual(partner.partner_latitude, 0.0)
        self.assertEqual(partner.partner_longitude, 0.0)

    def test_geo_localize_returns_false_in_test_mode(self):
        """geo_localize() short-circuits to False under the test-mode guard."""
        partner = self.env["res.partner"].create({"name": "Geo guard partner"})

        result = partner.geo_localize()

        self.assertFalse(result)
        self.assertFalse(partner.date_localization)
