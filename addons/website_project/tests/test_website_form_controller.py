from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.website_project.controllers.main import WebsiteForm

MAIN_MODULE = "odoo.addons.website_project.controllers.main"
FORM_MODULE = "odoo.addons.website.controllers.form"


@tagged("post_install", "-at_install")
class TestWebsiteFormExtractData(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = WebsiteForm()
        cls.task_model_sudo = cls.env["ir.model"].sudo()._get("project.task")

    @contextmanager
    def _mock_request(self):
        test_env = self.env

        class _RequestStub:
            env = test_env

        stub = _RequestStub()
        with (
            patch(f"{MAIN_MODULE}.request", stub),
            patch(f"{FORM_MODULE}.request", stub),
        ):
            yield

    def _extract(self, values):
        with self._mock_request():
            return self.controller.extract_data(self.task_model_sudo, values)

    def test_extract_data_known_email_links_partner(self):
        partner = self.env["res.partner"].create(
            {"name": "WP known partner", "email": "wp.known@example.com"}
        )
        data = self._extract(
            {
                "name": "Portal task",
                "email_from": "wp.known@example.com",
                "partner_name": "Ignored Name",
                "partner_phone": "555-0000",
            }
        )
        self.assertEqual(data["record"]["partner_id"], partner.id)
        self.assertEqual(data["record"]["email_from"], "wp.known@example.com")
        self.assertNotIn("partner_name", data["record"])
        self.assertNotIn("partner_phone", data["record"])
        self.assertIn("partner_name : Ignored Name", data["custom"])
        self.assertIn("partner_phone : 555-0000", data["custom"])

    def test_extract_data_unknown_email_keeps_contact_fields(self):
        data = self._extract(
            {
                "name": "Portal task",
                "email_from": "wp.unknown@example.com",
                "partner_name": "New Person",
                "partner_phone": "555-1111",
                "partner_company_name": "New Co",
            }
        )
        self.assertNotIn("partner_id", data["record"])
        self.assertEqual(data["record"]["email_cc"], "wp.unknown@example.com")
        self.assertEqual(data["record"]["partner_name"], "New Person")
        self.assertEqual(
            data["record"]["phone_ids"],
            [Command.create({"number": "555-1111", "type": "mobile"})],
        )
        self.assertEqual(data["record"]["partner_company_name"], "New Co")

    def test_extract_data_without_email_is_untouched(self):
        data = self._extract({"name": "Anonymous task"})
        self.assertNotIn("email_cc", data["record"])
        self.assertNotIn("partner_id", data["record"])
