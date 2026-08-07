from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessDenied, AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged

_REQUEST = "odoo.addons.base.models.res_users.request"


@tagged("post_install", "-at_install")
class TestChangePasswordWizardAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = new_test_user(
            cls.env, login="cpw_internal", password="cpw_internal_pw"
        )
        cls.manager = new_test_user(
            cls.env,
            login="cpw_manager",
            password="cpw_manager_pw",
            groups="base.group_user,base.group_erp_manager",
        )
        cls.target = new_test_user(
            cls.env, login="cpw_target", password="cpw_target_pw"
        )

    def _build_wizard(self, acting_user):
        return (
            self.env["change.password.wizard"]
            .with_user(acting_user)
            .with_context(active_model="res.users", active_ids=self.target.ids)
            .create({})
        )

    def test_non_manager_cannot_change_other_user_password(self):
        with self.assertRaises(AccessError):
            wizard = self._build_wizard(self.internal)
            wizard.change_password_button()
        self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_target_pw")

    def test_manager_can_change_other_user_password(self):
        wizard = self._build_wizard(self.manager)
        self.assertTrue(wizard.user_ids, "the target should seed a wizard line")
        wizard.user_ids.new_passwd = "cpw_manager_set_pw"
        wizard.change_password_button()
        self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_manager_set_pw")
        with self.assertRaises(AccessDenied):
            self.env["res.users"]._check_uid_passwd(self.target.id, "cpw_target_pw")

    def test_change_password_own_has_no_user_id_field(self):
        self.assertNotIn(
            "user_id",
            self.env["change.password.own"]._fields,
            "change.password.own must not expose a user_id field",
        )

    def test_change_password_own_operates_on_env_user(self):
        Users = self.env["res.users"]
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
        self.assertEqual(result.get("tag"), "reload")
        Users._check_uid_passwd(self.internal.id, "cpw_own_new_pw")
        with self.assertRaises(AccessDenied):
            Users._check_uid_passwd(self.internal.id, "cpw_internal_pw")
        Users._check_uid_passwd(self.target.id, "cpw_target_pw")
