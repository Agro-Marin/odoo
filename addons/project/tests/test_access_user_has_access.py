from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestUserHasAccessIsPerUser(TransactionCase):
    # user_has_access reads the user in its search, and rows name it as a
    # fixed filter: one user's verdict must never answer for another
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = new_test_user(cls.env, "uha-member", "base.group_user")
        cls.outsider = new_test_user(cls.env, "uha-outsider", "base.group_user")
        cls.project = cls.env["project.project"].create(
            {
                "name": "Invited only",
                "privacy_visibility": "followers",
                "member_user_ids": [Command.link(cls.member.id)],
            }
        )
        cls.milestone = cls.env["project.milestone"].create(
            {"name": "Launch", "project_id": cls.project.id}
        )

    def reached(self, user, records):
        return records.with_user(user).search([("id", "in", records.ids)])

    def assert_each_user_reads_their_own(self, first, second):
        for user in (first, second, first):
            for records in (self.project, self.milestone):
                expected = records if user == self.member else records.browse()
                self.assertEqual(self.reached(user, records), expected)
        with self.assertRaises(AccessError):
            self.milestone.with_user(self.outsider).read(["name"])
        self.assertEqual(
            self.milestone.with_user(self.member).read(["name"])[0]["name"], "Launch"
        )

    def test_the_member_first_then_the_outsider(self):
        self.assert_each_user_reads_their_own(self.member, self.outsider)

    def test_the_outsider_first_then_the_member(self):
        self.assert_each_user_reads_their_own(self.outsider, self.member)

    def test_again_after_every_cache_is_cleared(self):
        self.assert_each_user_reads_their_own(self.member, self.outsider)
        self.env.registry.clear_cache()
        self.env.invalidate_all()
        self.assert_each_user_reads_their_own(self.outsider, self.member)
