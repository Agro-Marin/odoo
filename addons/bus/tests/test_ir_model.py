import hashlib
import hmac
import time

import odoo
from odoo.http import STORED_SESSION_BYTES
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@odoo.tests.tagged("-at_install", "post_install")
class TestGetModelDefinitions(HttpCase):
    def test_access_cr(self):
        with self.assertRaises(KeyError):
            self.env["ir.model"]._get_model_definitions(["res.users", "cr"])

    def test_access_all_model_fields(self):
        model_definitions = self.env["ir.model"]._get_model_definitions(
            ["res.users", "res.partner"]
        )
        self.assertIn("res.users", model_definitions)
        self.assertIn("res.partner", model_definitions)
        self.assertGreaterEqual(
            model_definitions["res.partner"]["fields"].keys(),
            {"active", "name", "user_ids"},
        )
        self.assertGreaterEqual(
            model_definitions["res.partner"]["fields"].keys(),
            {"active", "name", "user_ids"},
        )

    def test_inaccessible_models_are_omitted(self):
        portal_user = new_test_user(
            self.env, login="bus_portal_defs", groups="base.group_portal"
        )
        self.assertTrue(
            self.env["res.partner"].with_user(portal_user).has_access("read")
        )
        self.assertFalse(self.env["ir.cron"].with_user(portal_user).has_access("read"))

        model_definitions = (
            self.env["ir.model"]
            .with_user(portal_user)
            ._get_model_definitions(["res.partner", "res.users", "ir.cron"])
        )
        self.assertIn("res.partner", model_definitions)
        self.assertIn("res.users", model_definitions)
        self.assertNotIn(
            "ir.cron",
            model_definitions,
            "restricted models must be omitted, not returned nor raised",
        )
        self.assertIn("name", model_definitions["res.partner"]["fields"])

    def test_admin_can_read_restricted_models(self):
        model_definitions = self.env["ir.model"]._get_model_definitions(["ir.cron"])
        self.assertIn("ir.cron", model_definitions)

    def _csrf_token(self, session):
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        max_ts = int(time.time() + 3600)
        msg = f"{session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()
        return f"{hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()}o{max_ts}"

    def test_route_rejects_unknown_models(self):
        session = self.authenticate("admin", "admin")
        response = self.url_open(
            "/bus/get_model_definitions",
            data={
                "model_names_to_fetch": '["res.partner", "no.such.model"]',
                "csrf_token": self._csrf_token(session),
            },
        )
        self.assertEqual(response.status_code, 400)
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
        model_definitions = self.env["ir.model"]._get_model_definitions(["res.partner"])
        self.assertNotIn("country_id", model_definitions["res.partner"]["fields"])

        model_definitions = self.env["ir.model"]._get_model_definitions(
            [
                "res.partner",
                "res.country",
            ]
        )
        self.assertIn("country_id", model_definitions["res.partner"]["fields"])


@tagged("-at_install", "post_install")
class TestGetModelDefinitionsPayload(TransactionCase):
    def test_duplicate_model_names_are_collapsed(self):
        once = self.env["ir.model"]._get_model_definitions(["res.partner"])
        many = self.env["ir.model"]._get_model_definitions(["res.partner"] * 50)
        self.assertEqual(many, once)

    def test_relational_fields_still_resolved_against_the_request(self):
        both = self.env["ir.model"]._get_model_definitions(
            ["res.partner", "res.users", "res.partner"]
        )
        self.assertIn("res.partner", both)
        self.assertIn("res.users", both)
        self.assertIn("partner_id", both["res.users"]["fields"])
        alone = self.env["ir.model"]._get_model_definitions(["res.users"])
        self.assertNotIn("partner_id", alone["res.users"]["fields"])
