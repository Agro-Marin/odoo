"""Tests for minting a trusted device from the 2FA login form.

Both cases here are reached by ticking "remember this device" on
``/web/login/totp``, and both used to fail the whole login POST after the
session had already been finalized.
"""

import base64
import hmac
import os
import re
import struct
import time

from lxml import html

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user

#: A User-Agent odoo/libs/_vendor/useragents.py classifies as neither browser
#: nor platform. The Odoo mobile app's own agent is the realistic case --
#: ``Odoo/x CFNetwork/y Darwin/z`` parses a platform but no browser.
UNRECOGNIZED_UA = "Odoo/19.0 CFNetwork/1494.0.7 Darwin/23.4.0"
CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _totp_token(secret_b32):
    """Return the current 6-digit TOTP code for a base32 secret (RFC 6238)."""
    key = base64.b32decode(re.sub(r"\s", "", secret_b32).upper())
    mac = hmac.new(key, struct.pack(">Q", int(time.time() / 30)), "sha1").digest()
    offset = mac[-1] & 0xF
    code = struct.unpack_from(">I", mac, offset)[0] & 0x7FFFFFFF
    return str(code % 10**6).zfill(6)


@tagged("post_install", "-at_install")
class TestTrustedDevice(HttpCase):
    def _new_2fa_user(self, login, groups):
        secret = base64.b32encode(os.urandom(20)).decode()
        user = mail_new_test_user(
            self.env, login, password=login, groups=groups, tz="UTC"
        )
        user.sudo().with_context(mail_notify_force_send=False).write(
            {"totp_secret": secret}
        )
        self.env.flush_all()
        return user, secret

    def _csrf(self, response):
        return (
            html.fromstring(response.content)
            .xpath('//input[@name="csrf_token"]')[0]
            .get("value")
        )

    def _login_remembering_device(self, login, secret, user_agent):
        """Run the real two-step login with "remember this device" ticked."""
        self.opener.headers["User-Agent"] = user_agent
        login_page = self.url_open("/web/login")
        totp_form = self.url_open(
            "/web/login",
            data={
                "login": login,
                "password": login,
                "csrf_token": self._csrf(login_page),
            },
        )
        self.assertIn("totp_token", totp_form.text, "expected the 2FA form")
        return self.url_open(
            "/web/login/totp",
            data={
                "totp_token": _totp_token(secret),
                "remember": "on",
                "csrf_token": self._csrf(totp_form),
            },
            allow_redirects=False,
        )

    def test_unrecognized_user_agent_still_registers_the_device(self):
        """An unparseable User-Agent must not fail the login (was a 500)."""
        user, secret = self._new_2fa_user("td_ua", "base.group_user")

        response = self._login_remembering_device("td_ua", secret, UNRECOGNIZED_UA)

        self.assertEqual(response.status_code, 303, "login should have succeeded")
        self.assertEqual(len(user.totp_trusted_device_ids), 1)
        self.assertIn("Unknown browser", user.totp_trusted_device_ids.name)

    def test_recognized_user_agent_names_the_device(self):
        """The naming path a real browser takes is unchanged (boundary)."""
        user, secret = self._new_2fa_user("td_chrome", "base.group_user")

        response = self._login_remembering_device("td_chrome", secret, CHROME_UA)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(user.totp_trusted_device_ids.name, "Chrome on Linux")

    def test_portal_user_may_remember_a_device(self):
        """A trusted device is not an API key: no portal.allow_api_keys needed.

        This used to be an HTTP 403, because auth_totp.device inherited
        res.users.apikeys' internal-users-only policy and portal's widening
        of it.
        """
        self.assertFalse(
            self.env["ir.config_parameter"].sudo().get_param("portal.allow_api_keys"),
            "the point of this test is the setting being at its default",
        )
        user, secret = self._new_2fa_user("td_portal", "base.group_portal")

        response = self._login_remembering_device("td_portal", secret, CHROME_UA)

        self.assertEqual(response.status_code, 303, "login should have succeeded")
        self.assertEqual(len(user.totp_trusted_device_ids), 1)

    def test_public_user_may_not_register_a_device(self):
        """The one caller authenticates first, but the floor stays explicit."""
        public_user = self.env.ref("base.public_user")
        with self.assertRaises(AccessError):
            self.env["auth_totp.device"].with_user(public_user)._generate(
                "browser", "nope", None
            )
