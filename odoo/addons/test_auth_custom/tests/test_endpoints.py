from http import HTTPStatus

import odoo.tools
from odoo.tests import HttpCase


class TestCustomAuth(HttpCase):
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
        url = f"{self.base_url()}/test_auth_custom/json"
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
            "POST",
            "json is always POST",
        )
        self.assertEqual(
            r.headers["Access-Control-Allow-Headers"],
            "XYZ",
            "headers are echoed back, not filtered",
        )

    @odoo.tools.mute_logger("odoo.http")
    def test_http(self):
        r = self.url_open("/test_auth_custom/http")
        self.assertEqual(r.status_code, HTTPStatus.FORBIDDEN)

        self.env.flush_all()
        url = f"{self.base_url()}/test_auth_custom/http"
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
            "GET, OPTIONS",
            "http is whatever's on the endpoint",
        )
        self.assertEqual(
            r.headers["Access-Control-Allow-Headers"],
            "XYZ",
            "headers are echoed back, not filtered",
        )
