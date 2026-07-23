"""Regression tests for ``odoo.libs.web.urls.urljoin``."""

import unittest

from odoo.libs.web.urls import urljoin


class TestUrljoin(unittest.TestCase):
    def test_basic_join(self):
        self.assertEqual(
            urljoin("https://api.example.com/v1/?bar=fiz", "/users/42?bar=bob"),
            "https://api.example.com/v1/users/42?bar=bob",
        )

    def test_non_utf8_percent_encoding_does_not_crash(self):
        # %ff is a valid percent-encoding of a non-UTF-8 byte; the dot-segment
        # check must not raise UnicodeDecodeError on it.
        self.assertEqual(urljoin("https://x.com/a/", "/b%ff"), "https://x.com/a/b%ff")

    def test_dot_segments_still_rejected(self):
        with self.assertRaises(ValueError):
            urljoin("https://x.com/a/", "/../etc")
        # even encoded dot segments are caught after decoding
        with self.assertRaises(ValueError):
            urljoin("https://x.com/a/", "/%2e%2e/etc")

    def test_foreign_host_rejected(self):
        with self.assertRaises(ValueError):
            urljoin("https://example.com/foo", "http://8.8.8.8/foo")

    def test_backslash_absolute_is_neutralized(self):
        # "\\example.com" must not become a protocol-relative redirect.
        out = urljoin("https://x.com/", "\\\\evil.com/")
        self.assertTrue(out.startswith("https://x.com/"))


if __name__ == "__main__":
    unittest.main()
