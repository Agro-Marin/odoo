from odoo.exceptions import AccessError
from odoo.tests import HttpCase

from odoo.addons.website_slides.tests import common


class TestEmbedDetection(HttpCase, common.SlidesCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.other_website = cls.env["website"].create(
            {"name": "Other Website", "domain": "https://testwebsite.com"}
        )
        cls.channel.website_id = cls.env["website"].get_current_website().id
        cls.slide.is_preview = True

    def test_embed_external_no_referer(self):
        self.url_open(f"/slides/embed_external/{self.slide.id}")
        embed_views = self.env["slide.embed"].search([("slide_id", "=", self.slide.id)])
        self.assertEqual(len(embed_views), 1)
        self.assertEqual(embed_views.website_name, "Unknown Website")

    def test_embed_external_referer(self):

        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.slide.id)]))
        )

        self.url_open(
            f"/slides/embed_external/{self.slide.id}",
            headers={"Referer": "https://someexternalwebsite.com"},
        )

        embed_views = self.env["slide.embed"].search([("slide_id", "=", self.slide.id)])
        self.assertEqual(len(embed_views), 1)
        self.assertEqual(embed_views.count_views, 1)
        self.assertEqual(embed_views.website_name, "https://someexternalwebsite.com")

    def test_embed_not_external(self):
        self.url_open(f"/slides/embed/{self.slide.id}")
        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.slide.id)]))
        )

    def test_embed_category_slide(self):
        self.slide.channel_id.website_id = False
        res = self.url_open(f"/slides/embed/{self.category.id}", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
        self.assertIn("/slides/", res.headers["Location"])
        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.category.id)]))
        )

    def test_embed_external_not_counted_when_not_readable(self):
        hidden = self.env["slide.slide"].create(
            {
                "name": "Not for the public",
                "channel_id": self.channel.id,
                "slide_category": "document",
                "is_published": False,
            }
        )
        for referer in (
            "https://attacker-1.example.com/a",
            "https://attacker-2.example.com/b",
        ):
            self.url_open(
                f"/slides/embed_external/{hidden.id}", headers={"Referer": referer}
            )
        self.assertFalse(
            self.env["slide.embed"].search([("slide_id", "=", hidden.id)]),
            "no row may be created for a slide the caller cannot read",
        )

    def test_embed_external_url_is_normalized(self):
        for suffix in ("", "?utm=1", "?utm=2", "#anchor"):
            self.url_open(
                f"/slides/embed_external/{self.slide.id}",
                headers={"Referer": f"https://someexternalwebsite.com/page{suffix}"},
            )
        embed_views = self.env["slide.embed"].search([("slide_id", "=", self.slide.id)])
        self.assertEqual(len(embed_views), 1)
        self.assertEqual(embed_views.count_views, 4)
        self.assertEqual(embed_views.url, "https://someexternalwebsite.com/page")

    def test_embed_is_not_readable_by_attendees(self):
        self.env["slide.embed"].create(
            {"slide_id": self.slide.id, "url": "https://x.example.com"}
        )
        for user in (self.user_portal, self.user_emp):
            with self.assertRaises(AccessError, msg=f"{user.login} reads embeds"):
                self.env["slide.embed"].with_user(user).search([])
        self.assertTrue(
            self.env["slide.embed"].with_user(self.user_officer).search([]),
            "the course responsible must still see their own statistics",
        )

    def test_embed_on_another_website_is_not_counted(self):
        self.channel.website_id = self.other_website.id
        self.url_open(
            f"/slides/embed_external/{self.slide.id}",
            headers={"Referer": "https://someexternalwebsite.com"},
        )
        self.assertFalse(
            self.env["slide.embed"].search([("slide_id", "=", self.slide.id)])
        )

    def test_embed_if_no_website_id(self):
        self.slide.channel_id.website_id = False
        res = self.url_open(f"/slides/embed/{self.slide.id}")
        res.raise_for_status()
        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.slide.id)]))
        )
