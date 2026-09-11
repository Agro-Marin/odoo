from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebsitePartner(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Acme"})
        cls.published = cls.env.ref("website_partner.mt_partner_published")
        cls.unpublished = cls.env.ref("website_partner.mt_partner_unpublished")

    def test_website_url_points_to_partner_slug(self):
        expected = "/partners/%s" % self.env["ir.http"]._slug(self.partner)
        self.assertEqual(self.partner.website_url, expected)
        self.assertTrue(self.partner.website_url.endswith(str(self.partner.id)))

    def test_track_subtype_published(self):
        self.partner.is_published = True
        self.assertEqual(
            self.partner._track_subtype({"is_published": False}), self.published
        )

    def test_track_subtype_unpublished(self):
        self.partner.is_published = False
        self.assertEqual(
            self.partner._track_subtype({"is_published": True}), self.unpublished
        )

    def test_track_subtype_falls_back_without_publish_change(self):
        subtype = self.partner._track_subtype({"name": "Renamed"})
        self.assertNotEqual(subtype, self.published)
        self.assertNotEqual(subtype, self.unpublished)
