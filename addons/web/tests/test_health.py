from unittest.mock import patch

import psycopg

from odoo.tests import HttpCase, tagged


@tagged("web_http", "web_health")
class TestWebController(HttpCase):
    def test_health(self):
        response = self.url_open("/web/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "pass")
        self.assertFalse(response.cookies.get("session_id"))

    def test_health_db_server_status(self):
        response = self.url_open("/web/health?db_server_status=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["db_server_status"], True)
        self.assertFalse(response.cookies.get("session_id"))

        def _raise_psycopg_error(*args):
            raise psycopg.Error("boom")

        with patch("odoo.db.db_connect", new=_raise_psycopg_error):
            response = self.url_open("/web/health?db_server_status=1")
            self.assertEqual(response.status_code, 500)
            payload = response.json()
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["db_server_status"], False)

    def test_healthz_liveness(self):
        """Liveness probe is always 200 if the worker can respond."""
        response = self.url_open("/web/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "pass"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertFalse(response.cookies.get("session_id"))

    def test_readyz_pass(self):
        """Readiness probe reports per-subsystem status; 200 when all pass."""
        response = self.url_open("/web/readyz")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["checks"]["db"], "pass")
        self.assertEqual(payload["checks"]["data_dir"], "pass")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_readyz_db_fail(self):
        """DB unreachability returns 503 (not 500) per Kubernetes convention."""

        def _raise_psycopg_error(*args):
            raise psycopg.Error("boom")

        with patch("odoo.db.db_connect", new=_raise_psycopg_error):
            response = self.url_open("/web/readyz")
            self.assertEqual(response.status_code, 503)
            payload = response.json()
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["checks"]["db"], "fail")

    def test_readyz_data_dir_fail(self):
        """Unwritable data_dir returns 503 with checks.data_dir = fail."""
        with patch(
            "odoo.addons.web.controllers.home.os.access",
            return_value=False,
        ):
            response = self.url_open("/web/readyz")
            self.assertEqual(response.status_code, 503)
            payload = response.json()
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["checks"]["data_dir"], "fail")
