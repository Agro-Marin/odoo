"""The portal security page must actually get the password meter.

This module renders `password_meter`, a public component registered by
auth_password_policy_signup, and reached the frontend bundle only through
that module's asset declaration -- while depending on neither. It worked
because portal implies auth_signup, so the bridge was always installed
alongside; nothing said so, and nothing would have caught it stopping.
"""

from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal


@tagged("post_install", "-at_install")
class TestPortalPasswordMeter(HttpCaseWithUserPortal):
    def test_security_page_carries_the_meter_and_the_minimum(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "auth_password_policy.minlength", "12"
        )

        self.authenticate("portal", "portal")
        page = self.url_open("/my/security").text

        self.assertIn(
            "password_meter",
            page,
            "the meter component is missing from the portal security page",
        )
        self.assertIn(
            'minlength="12"',
            page,
            "the configured minimum length did not reach the new-password input",
        )
