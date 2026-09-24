import json
import time

from lxml import html

import odoo.http
from odoo import fields
from odoo.http import Request
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal


@tagged("post_install", "-at_install")
class TestPortalDevices(HttpCaseWithUserPortal):
    def setUp(self):
        super().setUp()
        # a real login, where `authenticate` would skip the device bookkeeping
        anonymous = self.authenticate(None, None)
        del anonymous["_trace_disable"]
        odoo.http.root.session_store.save(anonymous)
        response = self.url_open(
            "/web/login",
            data={
                "login": "portal",
                "password": "portal",
                "csrf_token": Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.session = odoo.http.root.session_store.get(
            self.opener.cookies["session_id"]
        )
        self.phone = self._device(self.user_portal, "phone", name="Old phone")
        self.foreign = self._device(
            self.env.ref("base.user_admin"), "admin", name="Admin laptop"
        )

    def _device(self, user, tag, **vals):
        device = (
            self.env["res.device"]
            .sudo()
            .create(
                {
                    "user_id": user.id,
                    "key_hash": f"key_{tag}",
                    "platform": "android",
                    "browser": "chrome",
                    "device_type": "mobile",
                    "ip_address": "203.0.113.7",
                    "last_activity": fields.Datetime.now(),
                    **vals,
                }
            )
        )
        self.env["res.device.session"].sudo().create(
            {
                "device_id": device.id,
                "session_identifier": f"sid_{tag}".ljust(42, "x"),
                "last_activity": fields.Datetime.now(),
            }
        )
        return device

    def _rows(self):
        page = html.fromstring(self.url_open("/my/security").content)
        return {
            row.findtext(".//span[@class='fw-bold']").strip(): row
            for row in page.xpath("//li[contains(@class, 'o_portal_device')]")
        }

    def _confirm_identity(self):
        self.session["identity-check-last"] = time.time()
        odoo.http.root.session_store.save(self.session)

    def _revoke(self, device):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "res.device",
                "method": "revoke",
                "args": [device.ids],
                "kwargs": {},
            },
        }
        return self.url_open(
            "/web/dataset/call_kw/res.device/revoke",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        ).json()

    def test_the_page_lists_the_users_own_devices(self):
        rows = self._rows()
        self.assertIn("Old phone", rows)
        self.assertNotIn("Admin laptop", rows)
        current = [
            name
            for name, row in rows.items()
            if row.xpath(".//span[contains(@class, 'o_portal_device_current')]")
        ]
        self.assertEqual(len(current), 1, "the browser showing the page is marked")
        self.assertNotEqual(current, ["Old phone"])

    def test_logging_out_another_device_keeps_this_session(self):
        self._confirm_identity()
        response = self._revoke(self.phone)
        self.assertIsNone(response.get("error"), response.get("error"))
        self.assertIsNone(response["result"], "no reload: this browser stays in")
        self.assertFalse(self.phone.active)
        self.assertNotIn("Old phone", self._rows())
        self.assertTrue(self.url_open("/my/security").url.endswith("/my/security"))

    def test_logging_out_asks_for_the_password_first(self):
        response = self._revoke(self.phone)
        self.assertEqual(response["result"]["res_model"], "res.users.identitycheck")
        self.assertTrue(self.phone.active)

    def test_another_users_device_cannot_be_logged_out(self):
        self._confirm_identity()
        response = self._revoke(self.foreign)
        self.assertEqual(
            response["error"]["data"]["name"], "odoo.exceptions.AccessError"
        )
        self.assertTrue(self.foreign.active)

    def test_logging_out_from_the_page(self):
        self.start_tour("/my/security", "portal_log_out_a_device", login="portal")
        self.assertFalse(self.phone.active)
