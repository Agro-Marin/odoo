# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

import odoo.tests
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


@odoo.tests.tagged('external', '-standard')
class TestGeoLocalize(TransactionCase):

    def test_default_openstreetmap(self):
        """ Test that openstreetmap localize service works. """
        test_partner = self.env.ref('base.res_partner_2')
        test_partner.geo_localize()
        self.assertTrue(test_partner.partner_longitude)
        self.assertTrue(test_partner.partner_latitude)
        self.assertTrue(test_partner.date_localization)

        # we don't check here that the localization is at right place
        # but just that result is realistic float coordonates
        self.assertTrue(float(test_partner.partner_longitude) != 0.0)
        self.assertTrue(float(test_partner.partner_latitude) != 0.0)

    def test_googlemap_without_api_key(self):
        """ Without providing API key to google maps,
        the service doesn't work."""
        test_partner = self.env.ref('base.res_partner_address_4')
        google_map = self.env.ref('base_geolocalize.geoprovider_google_map').id
        self.env['ir.config_parameter'].set_param('base_geolocalize.geo_provider', google_map)
        with self.assertRaises(UserError):
            test_partner.geo_localize()
        self.assertFalse(test_partner.partner_longitude)
        self.assertFalse(test_partner.partner_latitude)
        self.assertFalse(test_partner.date_localization)


@odoo.tests.tagged('-at_install', 'post_install')
class TestPartnerGeoLocalization(TransactionCase):

    def test_geo_localization_notification(self):
        """ Warning message is sent to the user when geolocation fails. """
        partner = self.env['res.partner']
        user_partner = self.env.user.partner_id

        with patch.object(self.env.registry['bus.bus'], '_sendone') as mock_send:
            partner1 = partner.create({'name': 'Test A'})
            partner1.with_context(force_geo_localize=True).geo_localize()
            mock_send.assert_called_with(user_partner, 'simple_notification', {
                'type': 'danger',
                'title': "Warning",
                'message': "No match found for Test A address(es).",
            })
            mock_send.reset_mock()

            partner2 = partner.create({'name': "", 'parent_id': partner1.id, 'type': 'other'})
            partner2.with_context(force_geo_localize=True).geo_localize()
            mock_send.assert_called_with(user_partner, 'simple_notification', {
                'type': 'danger',
                'title': "Warning",
                'message': "No match found for Test A, Other address(es).",
            })
            mock_send.reset_mock()


class TestGeocoderRequestsTimeout(TransactionCase):
    """Outbound geocoding HTTP calls must bind an explicit timeout."""

    def test_call_openstreetmap_sets_timeout(self):
        """A stalled nominatim.openstreetmap.org must not hang the worker forever."""
        geocoder = self.env['base.geocoder']
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [{'lat': '10.0', 'lon': '20.0'}]
            geocoder._call_openstreetmap('1600 Amphitheatre Parkway')
        self.assertIn('timeout', mock_get.call_args.kwargs,
                       "requests.get() with no timeout can hang a worker forever on a stalled endpoint")

    def test_call_googlemap_sets_timeout(self):
        """A stalled maps.googleapis.com must not hang the worker forever."""
        self.env['ir.config_parameter'].sudo().set_param('base_geolocalize.google_map_api_key', 'fake-key')
        geocoder = self.env['base.geocoder']
        with patch('requests.get') as mock_get:
            mock_get.return_value.json.return_value = {
                'status': 'OK',
                'results': [{'geometry': {'location': {'lat': 10.0, 'lng': 20.0}}}],
            }
            geocoder._call_googlemap('1600 Amphitheatre Parkway')
        self.assertIn('timeout', mock_get.call_args.kwargs,
                       "requests.get() with no timeout can hang a worker forever on a stalled endpoint")
