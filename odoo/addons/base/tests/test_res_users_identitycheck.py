import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

_REQUEST = "odoo.addons.base.models.res_users_identitycheck.request"


@tagged("post_install", "-at_install")
class TestResUsersIdentityCheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="ric_user", password="ric_password")

    def _new_wizard(self):
        return self.env["res.users.identitycheck"].with_user(self.user).create({})

    def test_run_check_requires_request(self):
        wizard = self._new_wizard()
        with patch(_REQUEST, None), self.assertRaises(UserError):
            wizard.run_check()

    def test_run_check_wrong_password(self):
        wizard = self._new_wizard()
        with patch(_REQUEST, SimpleNamespace(session={})), self.assertRaises(UserError):
            wizard.with_context(password="wrong").run_check()

    def test_run_check_rejects_undecorated_method(self):
        wizard = self._new_wizard()
        payload = json.dumps([{}, "res.users", [self.user.id], "read", [["login"]], {}])
        wizard.sudo().request = payload
        fake_request = SimpleNamespace(session={})
        with patch(_REQUEST, fake_request), self.assertRaises(UserError):
            wizard.with_context(password="ric_password").run_check()
        self.assertNotIn("identity-check-last", fake_request.session)

    def test_run_check_identity_bound_to_env_user(self):
        new_test_user(self.env, login="ric_other", password="other_password")
        wizard = self._new_wizard()
        with (
            patch(_REQUEST, SimpleNamespace(session={})),
            self.assertRaises(UserError),
        ):
            wizard.with_context(password="other_password").run_check()

    def test_request_field_is_no_access(self):
        wizard = self._new_wizard()
        with self.assertRaises(AccessError):
            wizard.read(["request"])
        self.assertEqual(wizard.sudo().request, False)
        self.assertEqual(wizard._fields["request"].groups, fields.NO_ACCESS)
