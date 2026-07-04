from odoo.tests.common import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("-at_install", "post_install", "web_http", "web_manifest")
class WebManifestRoutesTest(HttpCaseWithUserDemo):
    """Exercises the routes serving the PWA backend manifest, service worker, and icons."""

    def test_webmanifest(self):
        """An authenticated request gets the full manifest, including shortcuts."""
        self.authenticate("admin", "admin")
        response = self.url_open("/web/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "Odoo")
        self.assertEqual(data["scope"], "/odoo")
        self.assertEqual(data["start_url"], "/odoo")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["background_color"], "#714B67")
        self.assertEqual(data["theme_color"], "#714B67")
        self.assertEqual(data["prefer_related_applications"], False)
        self.assertCountEqual(
            data["icons"],
            [
                {
                    "src": "/web/static/img/odoo-icon-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": "/web/static/img/odoo-icon-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
        )
        self.assertIsInstance(data["shortcuts"], list)
        for shortcut in data["shortcuts"]:
            self.assertGreater(len(shortcut["name"]), 0)
            self.assertGreater(len(shortcut["description"]), 0)
            self.assertGreater(len(shortcut["icons"]), 0)
            self.assertTrue(shortcut["url"].startswith("/odoo?menu_id="))

    def test_webmanifest_unauthenticated(self):
        """An unauthenticated request still gets a well-formed manifest, but with no shortcuts."""
        response = self.url_open("/web/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "Odoo")
        self.assertEqual(data["scope"], "/odoo")
        self.assertEqual(data["start_url"], "/odoo")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["background_color"], "#714B67")
        self.assertEqual(data["theme_color"], "#714B67")
        self.assertEqual(data["prefer_related_applications"], False)
        self.assertCountEqual(
            data["icons"],
            [
                {
                    "src": "/web/static/img/odoo-icon-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": "/web/static/img/odoo-icon-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
        )
        self.assertEqual(len(data["shortcuts"]), 0)

    def test_webmanifest_scoped(self):
        response = self.url_open(
            "/web/manifest.scoped_app_manifest?app_id=test&path=/test&app_name=Test"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "Test")
        self.assertEqual(data["scope"], "/test")
        self.assertEqual(data["start_url"], "/test")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["background_color"], "#714B67")
        self.assertEqual(data["theme_color"], "#714B67")
        self.assertEqual(data["prefer_related_applications"], False)
        self.assertCountEqual(
            data["icons"],
            [
                {
                    "src": "/web/static/img/odoo-icon-192x192.png",
                    "sizes": "any",
                    "type": "image/png",
                }
            ],
        )
        self.assertEqual(len(data["shortcuts"]), 0)

    def test_serviceworker(self):
        """The service worker script is scoped to /odoo via the Service-Worker-Allowed header."""
        response = self.url_open("/web/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/javascript")
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/odoo")

    def test_offline_url(self):
        """Serves the offline fallback page."""
        response = self.url_open("/odoo/offline")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")

    def test_apple_touch_icon(self):
        """The apple-touch-icon image is served and referenced in the page's <head>."""
        self.authenticate("demo", "demo")
        response = self.url_open("/web/static/img/odoo-icon-ios.png")
        self.assertEqual(response.status_code, 200)

        document = self.url_open("/odoo")
        self.assertIn(
            '<link rel="apple-touch-icon" href="/web/static/img/odoo-icon-ios.png"/>',
            document.text,
            "Icon for iOS is present in the head of the document.",
        )
