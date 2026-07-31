import os
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


@tagged("web_http", "web_metrics")
class TestWebMetrics(HttpCase):
    """``/web/metrics`` is off unless ``ODOO_METRICS_TOKEN`` arms it.

    The payload names every database this process serves, so an open endpoint
    would hand out exactly the enumeration ``db._rpc_db_exist`` and
    ``common.exp_authenticate`` are built to refuse.
    """

    def test_absent_without_a_token(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODOO_METRICS_TOKEN", None)
            response = self.url_open("/web/metrics")
        self.assertEqual(response.status_code, 404)

    def test_absent_even_when_a_token_is_offered(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODOO_METRICS_TOKEN", None)
            response = self.url_open(
                "/web/metrics", headers={"Authorization": "Bearer anything"}
            )
        self.assertEqual(response.status_code, 404)

    def test_rejects_a_missing_or_wrong_token(self):
        logger = "odoo.addons.web.controllers.home"
        with (
            patch.dict(os.environ, {"ODOO_METRICS_TOKEN": "right"}),
            self.assertLogs(logger, "WARNING") as capture,
        ):
            self.assertEqual(self.url_open("/web/metrics").status_code, 401)
            self.assertEqual(
                self.url_open(
                    "/web/metrics", headers={"Authorization": "Bearer wrong"}
                ).status_code,
                401,
            )
            self.assertEqual(
                self.url_open(
                    "/web/metrics", headers={"Authorization": "Basic right"}
                ).status_code,
                401,
            )
        # The refusal is the audit trail a scrape endpoint exists to leave, so
        # every rejected attempt has to be one record, not just a 401.
        self.assertEqual(len(capture.output), 3)

    def test_serves_the_exposition_with_a_valid_token(self):
        with patch.dict(os.environ, {"ODOO_METRICS_TOKEN": "right"}):
            response = self.url_open(
                "/web/metrics", headers={"Authorization": "Bearer right"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["Content-Type"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = response.text
        self.assertIn("odoo_up 1", body)
        self.assertIn("# TYPE odoo_pool_borrows_total counter", body)
