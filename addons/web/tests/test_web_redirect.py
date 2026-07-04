from urllib.parse import urlsplit

from odoo.tests.common import HttpCase, tagged


@tagged("web_http", "web_redirect")
class TestWebRedirect(HttpCase):
    def setUp(self):
        super().setUp()

    def test_web_route_redirect_param_legacy(self):
        """Legacy ``/web`` route (fragment-based params) redirects to the login page."""
        web_response = self.url_open("/web#cids=1&action=887&menu_id=124")
        web_response.raise_for_status()
        response_url_query = urlsplit(web_response.url).query

        self.assertEqual(response_url_query, "redirect=%2Fweb%3F")

    def test_web_route_redirect_param(self):
        """New ``/odoo/<path>`` route (query-string params) redirects to the login page."""
        web_response = self.url_open("/odoo/action-887?cids=1")
        web_response.raise_for_status()
        response_url_query = urlsplit(web_response.url).query

        self.assertEqual(response_url_query, "redirect=%2Fodoo%2Faction-887%3Fcids%3D1")
