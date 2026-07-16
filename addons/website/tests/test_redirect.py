# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.http_routing.tests.common import MockRequest


@tagged("-at_install", "post_install")
class TestWebsiteRedirect(TransactionCase):
    def test_01_website_redirect_validation(self):
        with self.assertRaises(ValidationError) as error:
            self.env["website.rewrite"].create(
                {
                    "name": "Test Website Redirect",
                    "redirect_type": "308",
                    "url_from": "/website/info",
                    "url_to": "/",
                }
            )
        self.assertIn("homepage", str(error.exception))

        with self.assertRaises(ValidationError) as error:
            self.env["website.rewrite"].create(
                {
                    "name": "Test Website Redirect",
                    "redirect_type": "308",
                    "url_from": "/website/info",
                    "url_to": "/favicon.ico",
                }
            )
        self.assertIn("existing page", str(error.exception))

        with self.assertRaises(ValidationError) as error:
            self.env["website.rewrite"].create(
                {
                    "name": "Test Website Redirect",
                    "redirect_type": "308",
                    "url_from": "/website/info",
                    "url_to": "/favicon.ico/",  # trailing slash on purpose
                }
            )
        self.assertIn("existing page", str(error.exception))

        with self.assertRaises(ValidationError) as error:
            self.env["website.rewrite"].create(
                {
                    "name": "Test Website Redirect",
                    "redirect_type": "301",
                    "url_from": "/website/info",
                    "url_to": "#",
                }
            )
        self.assertIn("must not start with '#'", str(error.exception))

        with self.assertRaises(ValidationError) as error:
            self.env["website.rewrite"].create(
                {
                    "name": "Test Website Redirect",
                    "redirect_type": "301",
                    "url_from": "/website/info",
                    "url_to": "/website/info",
                }
            )
        self.assertIn("should not be same", str(error.exception))

    def test_sitemap_with_redirect(self):
        self.env["website.rewrite"].create(
            {
                "name": "Test Website Redirect",
                "redirect_type": "308",
                "url_from": "/website/info",
                "url_to": "/test",
            }
        )
        website = self.env.ref("website.default_website")
        with MockRequest(self.env, website=website):
            self.env["website.rewrite"].refresh_routes()
            pages = self.env.ref("website.default_website")._enumerate_pages()
            urls = [url["loc"] for url in pages]
            self.assertIn("/website/info", urls)
            self.assertNotIn("/test", urls)


@tagged("-at_install", "post_install")
class TestWebsiteRedirectServe(HttpCase):
    def test_specific_website_redirect_wins_over_generic(self):
        """With the same ``url_from``, a rewrite specific to the current website
        must take precedence over a generic (website-less) one. Ordering only by
        ``url_from`` let the generic rule (usually a lower id) shadow the
        per-website override."""
        Rewrite = self.env["website.rewrite"]
        website = self.env["website"].browse(1)
        # Generic rule created first (lower id), then a website-specific override.
        Rewrite.create(
            {
                "name": "generic",
                "redirect_type": "301",
                "url_from": "/promo-priority",
                "url_to": "/generic-target",
                "website_id": False,
            }
        )
        Rewrite.create(
            {
                "name": "specific",
                "redirect_type": "301",
                "url_from": "/promo-priority",
                "url_to": "/specific-target",
                "website_id": website.id,
            }
        )
        res = self.url_open("/promo-priority", allow_redirects=False)
        self.assertEqual(res.status_code, 301)
        self.assertTrue(
            res.headers.get("Location", "").endswith("/specific-target"),
            "website-specific 301 must win over the generic one, got %r"
            % res.headers.get("Location"),
        )
