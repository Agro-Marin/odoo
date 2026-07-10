from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestResUsersSettingsOwnership(TransactionCase):
    """Cross-user access denial for res.users.settings (RUSET-T1).

    Ownership rests on the ``res_users_settings_rule_user`` record rule
    [('user_id','=',user.id)]: a group_user cannot read or write another user's
    settings, and ``user_id`` (in _PROTECTED_SETTINGS_FIELDS) cannot be
    rewritten via set_res_users_settings to hijack a row.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_a = new_test_user(cls.env, login="ruset_a", groups="base.group_user")
        cls.user_b = new_test_user(cls.env, login="ruset_b", groups="base.group_user")
        Settings = cls.env["res.users.settings"]
        cls.settings_a = Settings._find_or_create_for_user(cls.user_a)
        cls.settings_b = Settings._find_or_create_for_user(cls.user_b)
        # Pick any non-protected, writable, stored scalar field on the model
        # (base declares none beyond user_id; modules such as `web` add
        # `density`). None found -> tests fall back to id-less vals.
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
        # A writing B's record is blocked by the record rule at write() (not in
        # A's domain). Direct write so the test does not depend on
        # set_res_users_settings filtering out unknown fields.
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


class TestResUsersSettingsChangeDetection(TransactionCase):
    """Per-field-type change detection of set_res_users_settings (RUSET-P1).

    Detection branches on field type: many2one compares ids, x2many compares
    the id-set resulting from the incoming commands (normalized by
    ``_x2many_command_target_ids``). Guards the old bug where every relational
    value was reduced to ``.id`` — raising "Expected singleton" on multi-record
    x2many values.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_a = new_test_user(cls.env, login="rusetcd_a", groups="base.group_user")
        cls.user_b = new_test_user(cls.env, login="rusetcd_b", groups="base.group_user")
        cls.settings_a = cls.env["res.users.settings"]._find_or_create_for_user(
            cls.user_a
        )

    def test_x2many_command_target_ids_static_commands(self):
        normalize = self.env["res.users.settings"]._x2many_command_target_ids
        current = {1, 2}
        self.assertEqual(normalize(current, [Command.set([2, 1])]), {1, 2})
        self.assertEqual(normalize(current, [Command.set([3])]), {3})
        self.assertEqual(normalize(current, [Command.set([])]), set())
        self.assertEqual(normalize(current, [Command.link(2)]), {1, 2})
        self.assertEqual(normalize(current, [Command.link(3)]), {1, 2, 3})
        self.assertEqual(normalize(current, [Command.unlink(2)]), {1})
        self.assertEqual(normalize(current, [Command.delete(2)]), {1})
        self.assertEqual(normalize(current, [Command.clear()]), set())
        self.assertEqual(normalize(current, [Command.clear(), Command.link(5)]), {5})
        self.assertEqual(normalize(current, [3, 4]), {1, 2, 3, 4})
        self.assertEqual(normalize(current, []), {1, 2})
        # The input id-set must never be mutated in place.
        self.assertEqual(current, {1, 2})

    def test_x2many_command_target_ids_dynamic_or_malformed(self):
        normalize = self.env["res.users.settings"]._x2many_command_target_ids
        current = {1, 2}
        # create/update payloads cannot be resolved statically
        self.assertIsNone(normalize(current, [Command.create({"name": "x"})]))
        self.assertIsNone(normalize(current, [Command.update(1, {"name": "x"})]))
        # non-command values / malformed commands must fall back to "changed"
        self.assertIsNone(normalize(current, "nope"))
        self.assertIsNone(normalize(current, 5))
        self.assertIsNone(normalize(current, {1, 2}))
        self.assertIsNone(normalize(current, [("bogus",)]))
        self.assertIsNone(normalize(current, [(9, 1, 2)]))
        self.assertIsNone(normalize(current, [True]))

    def test_is_setting_changed_many2one_compares_ids(self):
        settings = self.settings_a
        self.assertFalse(settings._is_setting_changed("user_id", self.user_a.id))
        self.assertTrue(settings._is_setting_changed("user_id", self.user_b.id))
        self.assertTrue(settings._is_setting_changed("user_id", False))
        # empty m2o: False and None both mean "no record" -> not a change
        empty = self.env["res.users.settings"].new({})
        self.assertFalse(empty._is_setting_changed("user_id", False))
        self.assertFalse(empty._is_setting_changed("user_id", None))

    def test_is_setting_changed_scalar(self):
        settings = self.settings_a
        self.assertFalse(
            settings._is_setting_changed("display_name", settings.display_name)
        )
        self.assertTrue(settings._is_setting_changed("display_name", "something else"))


@tagged("post_install", "-at_install")
class TestResUsersSettingsWriteOnlyChanges(TransactionCase):
    """Integration check of the "only write actual changes" contract on real
    fields contributed by installed modules (base itself only declares the
    protected ``user_id``): re-submitting the current value of a writable
    x2many (resp. many2one) field must not report it as changed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="rusetwoc", groups="base.group_user")
        cls.settings = cls.env["res.users.settings"]._find_or_create_for_user(cls.user)

    def _find_writable_field(self, types):
        Settings = self.env["res.users.settings"]
        return next(
            (
                name
                for name, field in Settings._fields.items()
                if name not in Settings._PROTECTED_SETTINGS_FIELDS
                and field.type in types
                and field.store
                and not (field.compute and not field.inverse)
            ),
            None,
        )

    def test_unchanged_x2many_is_not_written(self):
        fname = self._find_writable_field(("many2many", "one2many"))
        if not fname:
            self.skipTest("no writable x2many field on res.users.settings")
        settings = self.settings.with_user(self.user)
        current_ids = settings[fname].ids
        # a same-ids SET command must be detected as "no change" (old code
        # compared the command payload to a scalar id, raising "Expected
        # singleton" on multi-record values)
        res = settings.set_res_users_settings({fname: [Command.set(current_ids)]})
        self.assertEqual(
            set(res.keys()),
            {"id"},
            f"re-submitting the current value of {fname} must not be a change",
        )

    def test_unchanged_many2one_is_not_written(self):
        fname = self._find_writable_field(("many2one",))
        if not fname:
            self.skipTest("no writable many2one field on res.users.settings")
        settings = self.settings.with_user(self.user)
        res = settings.set_res_users_settings({fname: settings[fname].id})
        self.assertEqual(
            set(res.keys()),
            {"id"},
            f"re-submitting the current value of {fname} must not be a change",
        )
