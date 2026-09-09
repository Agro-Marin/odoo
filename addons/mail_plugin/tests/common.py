import json
from contextlib import contextmanager
from unittest.mock import patch

from odoo import SUPERUSER_ID
from odoo.http import request
from odoo.tests.common import HttpCase

from odoo.addons.mail.tests.common import mail_new_test_user


@contextmanager
def mock_auth_method_outlook(login):

    def patched_auth_method_outlook(*args, **kwargs):
        request.update_env(
            user=request.env["res.users"]
            .with_user(SUPERUSER_ID)
            .search([("login", "=", login)], limit=1)
        )

    with patch(
        "odoo.addons.mail_plugin.models.ir_http.IrHttp._auth_method_outlook",
        new=patched_auth_method_outlook,
    ):
        yield


class TestMailPluginControllerCommon(HttpCase):
    def setUp(self):
        super().setUp()
        self.user_test = mail_new_test_user(
            self.env,
            login="employee",
            groups="base.group_user,base.group_partner_manager",
        )

    @mock_auth_method_outlook("employee")
    def mock_plugin_partner_get(self, name, email, patched_iap_enrich):
        data = {
            "id": 0,
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"email": email, "name": name},
        }

        with patch(
            "odoo.addons.mail_plugin.controllers.mail_plugin.MailPluginController"
            "._iap_enrich",
            new=patched_iap_enrich,
        ):
            result = self.url_open(
                "/mail_plugin/partner/get",
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )

        if not result.ok:
            return {}

        return result.json().get("result", {})

    @mock_auth_method_outlook("employee")
    def mock_enrich_and_create_company(self, partner_id, patched_iap_enrich):
        data = {
            "id": 0,
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"partner_id": partner_id},
        }

        with patch(
            "odoo.addons.mail_plugin.controllers.mail_plugin.MailPluginController"
            "._iap_enrich",
            new=patched_iap_enrich,
        ):
            result = self.url_open(
                "/mail_plugin/partner/enrich_and_create_company",
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )

        if not result.ok:
            return {}

        return result.json().get("result", {})
