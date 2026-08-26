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
        # The course lives on the site the embed is served from, and the slide
        # is previewable: an embed is only counted once the visitor is known to
        # be allowed to see it, so the fixture has to describe a slide they can.
        cls.channel.website_id = cls.env["website"].get_current_website().id
        cls.slide.is_preview = True

    def test_embed_external_no_referer(self):
        """When hitting the external URL without a referer header, the global embed record is
        incremented."""
        self.url_open(f"/slides/embed_external/{self.slide.id}")
        embed_views = self.env["slide.embed"].search([("slide_id", "=", self.slide.id)])
        self.assertEqual(len(embed_views), 1)
        self.assertEqual(embed_views.website_name, "Unknown Website")

    def test_embed_external_referer(self):
        """When hitting the external URL with a referer header, the embed record is incremented
        based on the referer URL."""

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
        """When hitting the non-external URL, we should not add a slide_embed record."""
        self.url_open(f"/slides/embed/{self.slide.id}")
        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.slide.id)]))
        )

    def test_embed_category_slide(self):
        """A category redirects to the course and is never counted.

        `allow_redirects=False`: what is under test is the embed route, not
        whether the course page it points at renders for this visitor.
        """
        self.slide.channel_id.website_id = False
        res = self.url_open(f"/slides/embed/{self.category.id}", allow_redirects=False)
        self.assertIn(res.status_code, (302, 303))
        self.assertIn("/slides/", res.headers["Location"])
        self.assertFalse(
            bool(self.env["slide.embed"].search([("slide_id", "=", self.category.id)]))
        )

    def test_embed_external_not_counted_when_not_readable(self):
        """An embed the visitor may not see is not counted.

        The counter used to be incremented under sudo *before* the access
        check, keyed on the Referer header, so an anonymous client could mint
        unbounded slide.embed rows carrying arbitrary URLs against any slide id
        -- unpublished ones included -- and have them surface in the
        publisher's backend.
        """
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
        """Query strings and fragments do not each get their own row."""
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
        """slide.embed had ACLs and no ir.rule at all, so it was world-readable.

        The URLs it stores are the third-party pages a course was embedded on;
        they belong to the publisher, not to every signed-in visitor.
        """
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
        """A course that is not published on this site is not visible from it."""
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
