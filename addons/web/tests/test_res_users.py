from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("web_unit", "web_users")
class TestResUsers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users = cls.env["res.users"].create(
            [
                {
                    "name": "Jean",
                    "login": "jean@mail.com",
                    "password": "jean@mail.com",
                },
                {
                    "name": "Jean-Paul",
                    "login": "jean-paul@mail.com",
                    "password": "jean-paul@mail.com",
                },
                {
                    "name": "Jean-Jacques",
                    "login": "jean-jacques@mail.com",
                    "password": "jean-jacques@mail.com",
                },
                {
                    "name": "Georges",
                    "login": "georges@mail.com",
                    "password": "georges@mail.com",
                },
                {
                    "name": "Claude",
                    "login": "claude@mail.com",
                    "password": "claude@mail.com",
                },
                {
                    "name": "Pascal",
                    "login": "pascal@mail.com",
                    "password": "pascal@mail.com",
                },
            ]
        )

    def test_name_search(self):
        """
        Test name search with self assign feature
        The self assign feature is present only when a limit is present,
        which is the case with the public name_search by default
        """
        ResUsers = self.env["res.users"]
        jean = self.users[0]
        user_ids = [id_ for id_, __ in ResUsers.with_user(jean).name_search("")]
        self.assertEqual(
            jean.id,
            user_ids[0],
            "The current user, Jean, should be the first in the result.",
        )
        user_ids = [id_ for id_, __ in ResUsers.with_user(jean).name_search("Claude")]
        self.assertNotIn(
            jean.id,
            user_ids,
            "The current user, Jean, should not be in the result because his name does not fit the condition.",
        )
        pascal = self.users[-1]
        user_ids = [id_ for id_, __ in ResUsers.with_user(pascal).name_search("")]
        self.assertEqual(
            pascal.id,
            user_ids[0],
            "The current user, Pascal, should be the first in the result.",
        )
        user_ids = [
            id_ for id_, __ in ResUsers.with_user(pascal).name_search("", limit=3)
        ]
        self.assertEqual(
            pascal.id,
            user_ids[0],
            "The current user, Pascal, should be the first in the result.",
        )
        self.assertEqual(
            len(user_ids),
            3,
            "The number of results found should still respect the limit set.",
        )
        jean_paul = self.users[1]
        user_ids = [
            id_ for id_, __ in ResUsers.with_user(jean_paul).name_search("Jean")
        ]
        self.assertEqual(
            jean_paul.id,
            user_ids[0],
            "The current user, Jean-Paul, should be the first in the result",
        )
        claude = self.users[4]
        user_ids = [
            id_ for id_, __ in ResUsers.with_user(claude).name_search("", limit=2)
        ]
        self.assertEqual(
            claude.id,
            user_ids[0],
            "The current user, Claude, should be the first in the result.",
        )
        self.assertNotEqual(
            claude.id,
            user_ids[1],
            "The current user, Claude, should not appear twice in the result",
        )
        user_ids = [
            id_ for id_, __ in ResUsers.with_user(claude).name_search("", limit=5)
        ]
        self.assertEqual(
            len(user_ids),
            len(set(user_ids)),
            "Some user(s), appear multiple times in the result",
        )

    def test_change_password(self):
        """
        We should be able to change user password without any issue
        """
        user_internal = self.env["res.users"].create(
            {
                "name": "Internal",
                "login": "user_internal",
                "password": "password",
                "group_ids": [self.env.ref("base.group_user").id],
            }
        )
        with Form(
            self.env["change.password.wizard"].with_context(
                active_model="res.users", active_ids=user_internal.ids
            ),
            view="base.change_password_wizard_view",
        ) as form:
            with form.user_ids.edit(0) as line:
                line.new_passwd = "bla"
        rec = form.save()
        rec.change_password_button()


@tagged("post_install", "-at_install", "web_unit", "web_users")
class TestWebCreateUsers(TransactionCase):
    """Tests for ``res.users.web_create_users``."""

    def test_web_create_users_skips_existing_active_user(self):
        """Calling ``web_create_users`` twice for the same email must not raise.

        Before fix: ``done`` only included reactivated-inactive users, missing
        already-active ones. The second call reached ``create()`` for an active
        user and hit the UNIQUE constraint on ``login``.
        After fix: ``all_matching`` covers both active and inactive users, so
        ``done`` correctly excludes the already-active login.
        """
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        email = "test_idempotent_create@example.com"
        self.env["res.users"].web_create_users([email])
        # Second call: user is now active — must be silently skipped.
        self.env["res.users"].web_create_users([email])  # must not raise IntegrityError

    def test_web_create_users_reactivates_deactivated(self):
        """``web_create_users`` must reactivate a previously deactivated user."""
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        email = "test_reactivate_create@example.com"
        self.env["res.users"].web_create_users([email])
        user = self.env["res.users"].with_context(active_test=False).search(
            [("login", "=", email)], limit=1
        )
        self.assertTrue(user, "User must have been created")
        user.active = False
        self.assertFalse(user.active)
        self.env["res.users"].web_create_users([email])
        user.invalidate_recordset()
        self.assertTrue(user.active, "Previously deactivated user must be reactivated")


@tagged("post_install", "-at_install", "web_tour", "web_users")
class TestUserSettings(HttpCaseWithUserDemo):
    def test_user_group_settings(self):
        self.start_tour("/odoo?debug=1", "test_user_group_settings", login="admin")
