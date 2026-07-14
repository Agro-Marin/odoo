"""Tests for the portal extension of the API-key holding policy.

Base policy (``res.users.apikeys._check_generate_access``) is internal users
only; portal widens it to portal users when the ``portal.allow_api_keys``
parameter is enabled — the "Customer API Keys" setting.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestPortalApiKeysPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = mail_new_test_user(
            cls.env,
            "portal_apikeys",
            groups="base.group_portal",
            name="Portal Apikeys",
        )
        cls.Apikeys = cls.env["res.users.apikeys"]
        cls.expiration = fields.Datetime.now() + timedelta(days=1)

    def _set_allow_api_keys(self, value):
        self.env["ir.config_parameter"].sudo().set_param("portal.allow_api_keys", value)

    def test_portal_user_rejected_by_default(self):
        self._set_allow_api_keys(False)
        with self.assertRaises(AccessError):
            self.Apikeys.with_user(self.portal_user)._generate(
                "rpc", "k", self.expiration
            )

    def test_portal_user_allowed_when_opted_in(self):
        self._set_allow_api_keys("True")
        key = self.Apikeys.with_user(self.portal_user)._generate(
            "rpc", "k", self.expiration
        )
        self.assertTrue(key)
        self.assertTrue(self.portal_user.api_key_ids)

    def test_make_key_ui_path_follows_same_policy(self):
        """The description wizard's access check must agree with _generate."""
        Description = self.env["res.users.apikeys.description"]
        self._set_allow_api_keys(False)
        with self.assertRaises(AccessError):
            Description.with_user(self.portal_user).check_access_make_key()
        self._set_allow_api_keys("True")
        # Must not raise anymore.
        Description.with_user(self.portal_user).check_access_make_key()

    def test_public_user_rejected_even_when_opted_in(self):
        self._set_allow_api_keys("True")
        public_user = self.env.ref("base.public_user")
        with self.assertRaisesRegex(AccessError, "internal and portal users"):
            self.Apikeys.with_user(public_user)._generate("rpc", "k", self.expiration)
