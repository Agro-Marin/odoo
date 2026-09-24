"""Revoking a single trusted device from the portal security page.

``revoke_trusted_device.js`` used to select on ``.fa.fa-trash.text-danger``,
the icon set's own classes. The FontAwesome 4 -> 7 upgrade renamed them in the
template (``fa-solid fa-trash-can``) and left the selector alone, so the
per-device revoke button silently stopped binding. Nothing failed, because
nothing covered revoke at all.

Two tests, deliberately at different depths. The first pins the
template/selector contract cheaply and names the class, so a rename shows up
as a failure that says what broke. The second drives the button for real --
which only became possible once portal users could hold a trusted device in
the first place; before that fix the fixture could not be built.
"""

from datetime import datetime, timedelta

from lxml import html

from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal

#: Must equal ``RevokeTrustedDevice.selector`` in
#: ``static/src/interactions/revoke_trusted_device.js``.
REVOKE_DEVICE_HOOK_CLASS = "o_totp_portal_revoke_device"


@tagged("post_install", "-at_install")
class TestRevokeDeviceHook(HttpCaseWithUserPortal):
    def _portal_user_with_a_trusted_device(self):
        """Enable 2FA on the portal user and give it one trusted device."""
        user = self.user_portal
        # auth_totp_mail notifies the user that 2FA went on; the mail itself is
        # not what this checks, so keep it queued rather than sent.
        user.sudo().with_context(mail_notify_force_send=False).write(
            {"totp_secret": "test"}
        )
        self.env["auth_totp.device"].with_user(user).sudo()._generate(
            "browser",
            "test-device",
            datetime.now() + timedelta(days=1),
        )
        return user

    def test_trusted_device_row_carries_the_interaction_hook(self):
        user = self._portal_user_with_a_trusted_device()

        self.authenticate("portal", "portal")
        page = self.url_open("/my/security").text

        self.assertIn("test-device", page, "the trusted device should be listed")
        self.assertIn(
            REVOKE_DEVICE_HOOK_CLASS,
            page,
            "the per-device revoke control lost the class its interaction binds "
            "to; RevokeTrustedDevice will never attach",
        )
        self.assertTrue(user.totp_trusted_device_ids)

    def test_a_device_holding_the_trust_is_badged(self):
        user = self._portal_user_with_a_trusted_device()
        trust = self.env["auth_totp.device"].sudo().search([("user_id", "=", user.id)])
        self.assertEqual(len(trust), 1)
        Device = self.env["res.device"].sudo()
        trusted, plain = Device.create(
            [
                {
                    "user_id": user.id,
                    "key_hash": "trusted",
                    "name": "Trusted laptop",
                    "totp_device_id": trust.id,
                },
                {"user_id": user.id, "key_hash": "plain", "name": "Plain laptop"},
            ]
        )

        self.authenticate("portal", "portal")
        page = html.fromstring(self.url_open("/my/security").content)

        badged = page.xpath(
            "//li[contains(@class, 'o_portal_device')]"
            "[.//span[contains(@class, 'o_portal_device_trusted')]]//span[@class='fw-bold']"
        )
        self.assertEqual([span.text.strip() for span in badged], [trusted.name])
        self.assertTrue(plain.active)

    def test_revoking_one_device_removes_it(self):
        """Click the button, answer the identity check, and lose the device."""
        user = self._portal_user_with_a_trusted_device()

        self.start_tour(
            "/my/security", "auth_portal_revoke_trusted_device", login="portal"
        )

        self.assertFalse(
            user.totp_trusted_device_ids,
            "the tour reported success, so the device must actually be gone",
        )
