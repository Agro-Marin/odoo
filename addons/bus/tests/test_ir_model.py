import hashlib
import hmac
import time

import odoo
from odoo.http import STORED_SESSION_BYTES
from odoo.tests import HttpCase


@odoo.tests.tagged("-at_install", "post_install")
class TestGetModelDefinitions(HttpCase):
    def test_access_cr(self):
        """Checks that get_model_definitions does not return anything else than models"""
        with self.assertRaises(KeyError):
            self.env["ir.model"]._get_model_definitions(["res.users", "cr"])

    def test_access_all_model_fields(self):
        """
        Check that get_model_definitions return all the models
        and their fields
        """
        model_definitions = self.env["ir.model"]._get_model_definitions(
            ["res.users", "res.partner"]
        )
        # models are retrieved
        self.assertIn("res.users", model_definitions)
        self.assertIn("res.partner", model_definitions)
        # check that model fields are retrieved
        self.assertGreaterEqual(
            model_definitions["res.partner"]["fields"].keys(),
            {"active", "name", "user_ids"},
        )
        self.assertGreaterEqual(
            model_definitions["res.partner"]["fields"].keys(),
            {"active", "name", "user_ids"},
        )

    def _csrf_token(self, session):
        """Forge a CSRF token for ``session`` (same math as
        ``Request.csrf_token``: HMAC of the stored sid prefix + expiry)."""
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        max_ts = int(time.time() + 3600)
        msg = f"{session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()
        return f"{hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()}o{max_ts}"

    def test_route_rejects_unknown_models(self):
        """An unknown model name (client-controlled input) is a 400, not a 500
        with a traceback."""
        session = self.authenticate("admin", "admin")
        response = self.url_open(
            "/bus/get_model_definitions",
            data={
                "model_names_to_fetch": '["res.partner", "no.such.model"]',
                "csrf_token": self._csrf_token(session),
            },
        )
        self.assertEqual(response.status_code, 400)
        # And a valid request still succeeds.
        response = self.url_open(
            "/bus/get_model_definitions",
            data={
                "model_names_to_fetch": '["res.partner"]',
                "csrf_token": self._csrf_token(session),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"res.partner", response.content)

    def test_relational_fields_with_missing_model(self):
        """
        Check that get_model_definitions only returns relational fields
        if the model is requested
        """
        model_definitions = self.env["ir.model"]._get_model_definitions(["res.partner"])
        # since res.country is not requested, country_id shouldn't be in
        # the model definition fields
        self.assertNotIn("country_id", model_definitions["res.partner"]["fields"])

        model_definitions = self.env["ir.model"]._get_model_definitions(
            [
                "res.partner",
                "res.country",
            ]
        )
        # res.country is requested, country_id should be present on res.partner
        self.assertIn("country_id", model_definitions["res.partner"]["fields"])
