import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

# Path of the thread-local `request` proxy imported into the wizard module.
_REQUEST = "odoo.addons.base.models.res_users_identitycheck.request"


@tagged("post_install", "-at_install")
class TestResUsersIdentityCheck(TransactionCase):
    """Guards for the password-check wizard (RIC-T1): HTTP-only access,
    wrong-password rejection, and the ``__has_check_identity`` allow-list gating
    which method ``run_check`` may execute.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="ric_user", password="ric_password")

    def _new_wizard(self):
        return self.env["res.users.identitycheck"].with_user(self.user).create({})

    def test_run_check_requires_request(self):
        """Without an HTTP request the wizard refuses to run."""
        wizard = self._new_wizard()
        with patch(_REQUEST, None), self.assertRaises(UserError):
            wizard.run_check()

    def test_run_check_wrong_password(self):
        """A wrong password is rejected before any stored method is loaded."""
        wizard = self._new_wizard()
        with patch(_REQUEST, SimpleNamespace(session={})), self.assertRaises(UserError):
            wizard.with_context(password="wrong").run_check()

    def test_run_check_rejects_undecorated_method(self):
        """A correct password still refuses a method not decorated with
        @check_identity (allow-list guard)."""
        wizard = self._new_wizard()
        # `read` is a plain ORM method, not decorated for identity-checked use.
        payload = json.dumps([{}, "res.users", [self.user.id], "read", [["login"]], {}])
        wizard.sudo().request = payload  # `request` field is groups=NO_ACCESS
        fake_request = SimpleNamespace(session={})
        with patch(_REQUEST, fake_request), self.assertRaises(UserError):
            wizard.with_context(password="ric_password").run_check()
        # the anti-replay timestamp is stamped before the allow-list check
        # (RIC-L1: session-global, method-agnostic 10-min sudo window)
        self.assertIn("identity-check-last", fake_request.session)

    def test_run_check_identity_bound_to_env_user(self):
        """RIC-T3: the password is re-verified against ``self.env.user`` (the
        acting user), so another user's password cannot satisfy the check."""
        # Another existing user whose password differs from self.user's.
        new_test_user(self.env, login="ric_other", password="other_password")
        wizard = self._new_wizard()  # acts as self.user (password ric_password)
        with (
            patch(_REQUEST, SimpleNamespace(session={})),
            self.assertRaises(UserError),
        ):
            # ric_other's password must not unlock a wizard acting as self.user.
            wizard.with_context(password="other_password").run_check()

    def test_request_field_is_no_access(self):
        """RIC-T4: the deferred-payload ``request`` field is groups=NO_ACCESS, so
        it cannot be read without sudo, pinning payload confidentiality."""
        wizard = self._new_wizard()
        # groups=NO_ACCESS denies even the owning user a direct read.
        with self.assertRaises(AccessError):
            wizard.read(["request"])
        # sudo can still access it (the decorator/run_check path).
        self.assertEqual(wizard.sudo().request, False)
        self.assertEqual(wizard._fields["request"].groups, fields.NO_ACCESS)
