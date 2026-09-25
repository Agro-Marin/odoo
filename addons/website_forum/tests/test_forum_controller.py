from lxml import html

from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.website_forum.controllers.website_forum import WebsiteForum
from odoo.addons.website_forum.tests.common import KARMA, TestForumCommon


class TestForumController(TestForumCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_multi_website()
        cls.minimum_karma_allowing_to_post = KARMA["ask"]
        cls.forums = cls.env["forum.forum"].create(
            [
                {
                    "name": f"Forum {idx + 2}",
                    "karma_ask": cls.minimum_karma_allowing_to_post,
                    "website_id": website.id,
                }
                for idx, website in enumerate(
                    (
                        cls.base_website,
                        cls.base_website,
                        cls.base_website,
                        cls.website_2,
                        cls.website_2,
                    )
                )
            ]
        )
        (
            cls.forum_1,
            cls.forum_2,
            cls.forum_3,
            cls.forum_1_website_2,
            cls.forum_2_website_2,
        ) = cls.forums
        cls.controller = WebsiteForum()

    def _get_my_other_forums(self, forum):
        return self.forums & self.controller._prepare_user_values(forum=forum).get(
            "my_other_forums"
        )

    def forum_post(self, user, forum):
        return (
            self.env["forum.post"]
            .with_user(user)
            .create(
                {
                    "content": "A post ...",
                    "forum_id": forum.id,
                    "name": "Post...",
                }
            )
        )

    def test_prepare_user_values_my_other_forum(self):
        employee_2_forum_2_post = self.forum_post(self.user_employee_2, self.forum_2)
        employee_2_website_2_forum_2_post = self.forum_post(
            self.user_employee_2, self.forum_2_website_2
        )
        for user in (
            self.user_admin,
            self.user_employee,
            self.user_portal,
            self.user_public,
        ):
            with (
                self.with_user(user.login),
                MockRequest(self.env, website=self.base_website),
            ):
                self.assertFalse(self._get_my_other_forums(self.forum_1))
                self.assertFalse(self._get_my_other_forums(None))
                self.assertFalse(self._get_my_other_forums(True))
                if user != self.user_public:
                    self.env.user.karma = self.minimum_karma_allowing_to_post
                    employee_2_forum_2_post.favorite_user_ids += self.env.user
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_1), self.forum_2
                    )
                    self.assertFalse(self._get_my_other_forums(self.forum_2))
                    self.forum_post(self.env.user, self.forum_3)
                    self.forum_post(self.env.user, self.forum_1_website_2)
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_1),
                        self.forum_2 + self.forum_3,
                    )
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_2), self.forum_3
                    )
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_3), self.forum_2
                    )
            with (
                self.with_user(user.login),
                MockRequest(self.env, website=self.website_2),
            ):
                self.assertFalse(self._get_my_other_forums(None))
                self.assertFalse(self._get_my_other_forums(True))
                if user != self.user_public:
                    self.assertFalse(self._get_my_other_forums(self.forum_1_website_2))
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_2_website_2),
                        self.forum_1_website_2,
                    )
                    employee_2_website_2_forum_2_post.favorite_user_ids += self.env.user
                    self.assertEqual(
                        self._get_my_other_forums(self.forum_1_website_2),
                        self.forum_2_website_2,
                    )


@tagged("post_install", "-at_install")
class TestForumZeroKarmaForm(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.forum = cls.env["forum.forum"].create(
            {
                "name": "Open forum",
                "karma_ask": 0,
                "karma_tag_create": 0,
                "karma_edit_retag": 0,
                "karma_comment_all": 7,
            }
        )
        new_test_user(cls.env, login="zero_karma", groups="base.group_user", karma=0)

    def test_a_zero_karma_reaches_the_ask_form(self):
        forum = self.forum
        self.authenticate("zero_karma", "zero_karma")

        response = self.url_open(f"/forum/{self.env['ir.http']._slug(forum)}/ask")

        self.assertEqual(response.status_code, 200)
        page = html.fromstring(response.content)
        for input_id in ("karma", "karma_tag_create", "karma_edit_retag"):
            with self.subTest(input_id=input_id):
                [input_el] = page.xpath(f"//input[@id='{input_id}']")
                self.assertEqual(input_el.get("value"), "0")

    def test_the_comment_link_carries_the_karma_it_requires(self):
        question = self.env["forum.post"].create(
            {"forum_id": self.forum.id, "name": "Question", "content": "Body"}
        )
        self.authenticate("zero_karma", "zero_karma")
        slug = self.env["ir.http"]._slug

        response = self.url_open(f"/forum/{slug(self.forum)}/{slug(question)}")

        self.assertEqual(response.status_code, 200)
        links = html.fromstring(response.content).xpath(
            "//a[contains(@class, 'karma_required')][.//i[contains(@class, 'fa-comment')]]"
        )
        self.assertTrue(links)
        self.assertEqual({link.get("data-karma") for link in links}, {"7"})
