from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestResUsersSettingsOwnership(TransactionCase):
    """Cross-user access denial for res.users.settings (audit RUSET-T1).

    Ownership rests entirely on the `res_users_settings_rule_user` record rule
    [('user_id','=',user.id)]; this pins that a group_user cannot read or write
    another user's settings, and that `user_id` (in _PROTECTED_SETTINGS_FIELDS)
    cannot be rewritten via set_res_users_settings to hijack a row.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_a = new_test_user(cls.env, login="ruset_a", groups="base.group_user")
        cls.user_b = new_test_user(cls.env, login="ruset_b", groups="base.group_user")
        Settings = cls.env["res.users.settings"]
        cls.settings_a = Settings._find_or_create_for_user(cls.user_a)
        cls.settings_b = Settings._find_or_create_for_user(cls.user_b)
        # Pick any non-protected, writable, stored scalar field present on the
        # model (base alone declares none beyond user_id; post_install modules
        # such as `web` add `density`). Falls back to a direct write of `id`-less
        # vals if none exists.
        cls._writable_field = next(
            (
                name
                for name, field in Settings._fields.items()
                if name not in Settings._PROTECTED_SETTINGS_FIELDS
                and field.store
                and not (field.compute and not field.inverse)
                and not field.relational
            ),
            None,
        )

    def test_user_cannot_write_other_users_settings(self):
        # User A tries to write B's settings record -> blocked by the record rule
        # at write() (record not in A's domain). Use a direct write so the test
        # does not depend on set_res_users_settings filtering out unknown fields.
        settings_b_as_a = self.settings_b.with_user(self.user_a)
        vals = {self._writable_field: False} if self._writable_field else {}
        with self.assertRaises(AccessError):
            settings_b_as_a.write(vals)

    def test_user_cannot_read_other_users_settings(self):
        settings_b_as_a = self.settings_b.with_user(self.user_a)
        with self.assertRaises(AccessError):
            settings_b_as_a._res_users_settings_format()

    def test_protected_user_id_cannot_be_rewritten(self):
        # A user setting user_id on their OWN record is silently ignored
        # (user_id is in _PROTECTED_SETTINGS_FIELDS), so the row stays theirs.
        settings_a_as_a = self.settings_a.with_user(self.user_a)
        settings_a_as_a.set_res_users_settings({"user_id": self.user_b.id})
        self.assertEqual(
            self.settings_a.user_id,
            self.user_a,
            "user_id must not be rewritable via set_res_users_settings (RUSET-L2)",
        )
