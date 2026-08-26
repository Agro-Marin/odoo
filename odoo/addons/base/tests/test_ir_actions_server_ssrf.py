from odoo.tests.common import BaseCase

from odoo.addons.base.models.ir_actions_server import _get_webhook_blocked_reason


# No `post_install`: that phase exists for tests that need the FINAL registry,
# and every assertion below is a pure function over IP literals. Tagging it
# `post_install` only delayed it to the slowest phase and made its result depend
# on what else happened to be installed.
class TestWebhookSsrfGuard(BaseCase):
    def test_non_global_literals_are_blocked(self):
        for host in (
            "127.0.0.1",
            "169.254.169.254",
            "10.0.0.1",
            "192.168.1.1",
            "100.64.0.1",
            "0.0.0.0",
            "255.255.255.255",
            "224.0.0.1",
            "239.255.255.250",
            "[::1]",
            "[::ffff:127.0.0.1]",
            "[::ffff:169.254.169.254]",
            "[fd00::1]",
            "[fe80::1]",
            "[ff02::1]",
            "[ff00::1]",
            "[5f00::1]",
            "[2001:db8::1]",
        ):
            with self.subTest(host=host):
                self.assertIsNotNone(_get_webhook_blocked_reason(f"http://{host}/hook"))

    def test_public_literals_are_allowed(self):
        for host in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "[2606:4700::1111]"):
            with self.subTest(host=host):
                self.assertIsNone(_get_webhook_blocked_reason(f"https://{host}/hook"))

    def test_non_http_schemes_and_malformed_urls_are_blocked(self):
        for url in (
            "file:///etc/passwd",
            "gopher://x/",
            "ftp://example.com/",
            "http://",
        ):
            with self.subTest(url=url):
                self.assertIsNotNone(_get_webhook_blocked_reason(url))
