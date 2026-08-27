from http import HTTPStatus

import odoo.tools
from odoo.tests import HttpCase


class TestCustomAuth(HttpCase):
    def _assert_cors_preflight(self, path, expected_allow_methods, methods_message):
        url = f"{self.base_url()}{path}"
        r = self.url_open(
            url,
            method="OPTIONS",
            headers={
                "Origin": "localhost",
                "Access-Control-Request-Method": "QUX",
                "Access-Control-Request-Headers": "XYZ",
            },
        )
        self.assertTrue(r.ok, r.text)
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(
            r.headers["Access-Control-Allow-Methods"],
            expected_allow_methods,
            methods_message,
        )
        self.assertEqual(
            r.headers["Access-Control-Allow-Headers"],
            "XYZ",
            "headers are echoed back, not filtered",
        )

    @odoo.tools.mute_logger("odoo.http")
    def test_json(self):
        r = self.url_open(
            "/test_auth_custom/json",
            headers={"Content-Type": "application/json"},
            data="{}",
        )
        e = r.json()["error"]
        self.assertEqual(e["data"]["name"], "odoo.exceptions.AccessDenied")

        self.env.flush_all()
        self._assert_cors_preflight(
            "/test_auth_custom/json", "POST", "json is always POST"
        )

    @odoo.tools.mute_logger("odoo.http")
    def test_http(self):
        r = self.url_open("/test_auth_custom/http")
        self.assertEqual(r.status_code, HTTPStatus.FORBIDDEN)

        self.env.flush_all()
        self._assert_cors_preflight(
            "/test_auth_custom/http",
            "GET, OPTIONS",
            "http is whatever's on the endpoint",
        )
