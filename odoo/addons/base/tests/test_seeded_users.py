from odoo.tests import tagged

from .common import HttpCaseWithUserDemo, HttpCaseWithUserPortal


@tagged("-at_install", "post_install")
class TestSeededUsersCombine(HttpCaseWithUserDemo, HttpCaseWithUserPortal):
    def test_each_seeded_case_seeds_its_own_login(self):
        self.assertEqual(self.user_demo.login, "demo")
        self.assertEqual(self.user_portal.login, "portal")
        self.assertNotEqual(self.user_demo, self.user_portal)

    def test_both_seeded_users_can_authenticate(self):
        for login in ("demo", "portal"):
            with self.subTest(login=login):
                self.assertTrue(
                    self.env["res.users"]
                    .sudo()
                    .search([("login", "=", login)], limit=1),
                    "a tour logging in as this user would get AccessDenied",
                )

    def test_the_portal_user_keeps_its_own_groups(self):
        self.assertTrue(self.user_portal.has_group("base.group_portal"))
        self.assertTrue(self.user_demo.has_group("base.group_user"))
