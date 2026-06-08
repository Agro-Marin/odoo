from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessDenied, AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged

# Path of the thread-local `request` proxy imported into res_users, which is
# what the @check_identity decorator (used by change.password.own) consults.
_REQUEST = "odoo.addons.base.models.res_users.request"


@tagged("post_install", "-at_install")
class TestChangePasswordWizardAudit(TransactionCase):
    """Security-regression coverage for the change-password wizards (audit CPW).

    Pins the access-control invariants the audit verified: cross-user password
    setting via ``change.password.user`` is gated by the
    ``base.group_erp_manager`` ACL (privilege-based, not a blanket block), and
    ``change.password.own`` is structurally hard-bound to ``self.env.user``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A plain internal user (group_user) -- NOT an erp manager.
        cls.internal = new_test_user(
            cls.env, login="cpw_internal", password="cpw_internal_pw"
        )
        # An erp manager, allowed to operate the change.password.user wizard.
        cls.manager = new_test_user(
            cls.env,
            login="cpw_manager",
            password="cpw_manager_pw",
            groups="base.group_user,base.group_erp_manager",
        )
        # The target whose password the others try to change.
        cls.target = new_test_user(
            cls.env, login="cpw_target", password="cpw_target_pw"
        )

    def _build_wizard(self, acting_user):
        """Create a change.password.wizard the way the UI does (active_ids on
        res.users seed a change.password.user line per target), acting as
        ``acting_user``.

        :param recordset acting_user: the session user creating the wizard.
        :return: the wizard recordset bound to ``acting_user``.
        :rtype: recordset
        """
        return (
            self.env["change.password.wizard"]
            .with_user(acting_user)
            .with_context(active_model="res.users", active_ids=self.target.ids)
            .create({})
        )

    def test_non_manager_cannot_change_other_user_password(self):
        """A non-erp-manager internal user is denied use of the
        change.password.user wizard to set another user's password (the
        change.password.* ACLs are group_erp_manager only)."""
        with self.assertRaises(AccessError):
            wizard = self._build_wizard(self.internal)
            wizard.change_password_button()
        # The target's original password must still authenticate.
        self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_target_pw")

    def test_manager_can_change_other_user_password(self):
        """Positive control: an erp manager CAN set another user's password,
        proving the block above is privilege-based and not a total block."""
        wizard = self._build_wizard(self.manager)
        self.assertTrue(wizard.user_ids, "the target should seed a wizard line")
        wizard.user_ids.new_passwd = "cpw_manager_set_pw"
        wizard.change_password_button()
        # The new password authenticates; the old one no longer does.
        self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_manager_set_pw")
        with self.assertRaises(AccessDenied):
            self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_target_pw")

    def test_change_password_own_has_no_user_id_field(self):
        """change.password.own defines no ``user_id`` field: it cannot target
        another user's record, only the acting session user."""
        self.assertNotIn(
            "user_id",
            self.env["change.password.own"]._fields,
            "change.password.own must not expose a user_id field",
        )

    def test_change_password_own_operates_on_env_user(self):
        """change.password.own.change_password applies the new password to
        self.env.user only. Bypasses the @check_identity re-auth by stamping a
        fresh ``identity-check-last`` in a patched HTTP request session (same
        idiom as test_res_users_identitycheck)."""
        Users = self.env["res.users"]
        # A recent (now) identity check satisfies the @check_identity window.
        fake_request = SimpleNamespace(
            session={"identity-check-last": 9_999_999_999.0},
            httprequest=SimpleNamespace(environ={"REMOTE_ADDR": "127.0.0.1"}),
        )
        wizard = (
            self.env["change.password.own"]
            .with_user(self.internal)
            .create(
                {
                    "new_password": "cpw_own_new_pw",
                    "confirm_password": "cpw_own_new_pw",
                }
            )
        )
        with patch(_REQUEST, fake_request):
            result = wizard.change_password()
        # The acting user's (self.internal) password was changed -- nobody else.
        self.assertEqual(result.get("tag"), "reload")
        Users._check_uid_passwd(self.internal.id, "cpw_own_new_pw")
        with self.assertRaises(AccessDenied):
            Users._check_uid_passwd(self.internal.id, "cpw_internal_pw")
        # The target user is untouched by an own-password change.
        Users._check_uid_passwd(self.target.id, "cpw_target_pw")
