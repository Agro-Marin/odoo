import odoo.tests
from odoo.tests import HttpCase


@odoo.tests.common.tagged("post_install", "-at_install")
class TestSitemap(HttpCase):
    def setUp(self):
        super().setUp()

        self.website = self.env.ref("website.default_website")
        self.lang_fr = self.env["res.lang"]._activate_lang("fr_FR")
        self.website.language_ids = self.env.ref("base.lang_en") + self.lang_fr
        self.website.default_lang_id = self.env.ref("base.lang_en")

        self.env["ir.module.module"].search(
            [("name", "=", "website_blog")]
        )._update_translations(["fr_FR"])

        self.blog_post = self.env["blog.post"].search([], limit=1)

    def test_01_sitemap_language(self):

        response = self.url_open("/fr_FR")
        self.assertIn("/fr/contactus", response.text)

        response = self.url_open("/sitemap.xml")

        if self.blog_post:
            self.assertIn(self.blog_post.website_url, response.text)

    def test_02_sitemap_language(self):

        self.website.default_lang_id = (
            self.env["res.lang"].sudo()._activate_lang("fr_FR")
        )

        response = self.url_open("/sitemap.xml")

        if self.blog_post:
            translated_url = self.blog_post.with_context(lang="fr_FR").website_url
            self.assertIn(translated_url, response.text)
