"""The trusted-device row must carry the class its interaction selects on.

``revoke_trusted_device.js`` used to select on ``.fa.fa-trash.text-danger``,
the icon set's own classes. The FontAwesome 4 -> 7 upgrade renamed them in the
template (``fa-solid fa-trash-can``) and left the selector alone, so the
per-device revoke button silently stopped binding. Nothing failed: no tour
covers revoke.

This pins the contract from the template's side -- the page a portal user with
a trusted device actually gets must contain the hook class. Keep it in step
with ``static/src/interactions/revoke_trusted_device.js``.
"""

from datetime import datetime, timedelta

from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal

#: Must equal ``RevokeTrustedDevice.selector`` in
#: ``static/src/interactions/revoke_trusted_device.js``.
REVOKE_DEVICE_HOOK_CLASS = "o_totp_portal_revoke_device"


@tagged("post_install", "-at_install")
class TestRevokeDeviceHook(HttpCaseWithUserPortal):
    def test_trusted_device_row_carries_the_interaction_hook(self):
        user = self.user_portal
        # auth_totp_mail notifies the user that 2FA went on; the mail itself is
        # not what this checks, so keep it queued rather than sent.
        user.sudo().with_context(mail_notify_force_send=False).write(
            {"totp_secret": "test"}
        )
        # auth_totp.device is a res.users.apikeys prototype, so minting one runs
        # portal's _check_generate_access, which gates portal users on this flag.
        self.env["ir.config_parameter"].sudo().set_param(
            "portal.allow_api_keys", "True"
        )
        self.env["auth_totp.device"].with_user(user).sudo()._generate(
            "browser",
            "test-device",
            datetime.now() + timedelta(days=1),
        )

        self.authenticate("portal", "portal")
        page = self.url_open("/my/security").text

        self.assertIn("test-device", page, "the trusted device should be listed")
        self.assertIn(
            REVOKE_DEVICE_HOOK_CLASS,
            page,
            "the per-device revoke control lost the class its interaction binds "
            "to; RevokeTrustedDevice will never attach",
        )
