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
    def test_web_create_users_skips_existing_active_user(self):
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        email = "test_idempotent_create@example.com"
        self.env["res.users"].web_create_users([email])
        self.env["res.users"].web_create_users([email])

    def test_web_create_users_dedups_login_with_empty_email_normalized(self):
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        login = "login_only_collide@example.com"
        existing = self.env["res.users"].create({"name": "LoginOnly", "login": login})
        self.assertFalse(
            existing.email_normalized,
            "precondition: the user has an empty email_normalized",
        )
        self.env["res.users"].web_create_users([login])
        matches = (
            self.env["res.users"]
            .with_context(active_test=False)
            .search([("login", "=", login)])
        )
        self.assertEqual(len(matches), 1, "must not create a duplicate user")

    def test_web_create_users_dedups_within_batch(self):
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        email = "batch_dup@example.com"
        self.env["res.users"].web_create_users([email, f"Batch Dup <{email}>"])
        matches = (
            self.env["res.users"]
            .with_context(active_test=False)
            .search([("login", "=", email)])
        )
        self.assertEqual(len(matches), 1, "in-batch duplicate must create one user")

    def test_web_create_users_reactivates_deactivated(self):
        if "email_normalized" not in self.env["res.users"]._fields:
            self.skipTest("email_normalized not available (mail not installed)")
        email = "test_reactivate_create@example.com"
        self.env["res.users"].web_create_users([email])
        user = (
            self.env["res.users"]
            .with_context(active_test=False)
            .search([("login", "=", email)], limit=1)
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
        self.start_tour(
            "/odoo/settings?debug=assets,tests",
            "test_user_group_settings",
            login="admin",
            timeout=120,
        )
