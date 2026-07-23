"""Regression tests for ``odoo.libs.email.parsing.formataddr`` header safety."""

import unittest

from odoo.libs.email.parsing import formataddr


class TestFormataddr(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            formataddr(("John Doe", "john@example.com")),
            '"John Doe" <john@example.com>',
        )

    def test_address_only(self):
        self.assertEqual(formataddr(("", "john@example.com")), "john@example.com")

    def test_strips_crlf_from_name(self):
        # an injected CR/LF must not survive into the header (header splitting).
        out = formataddr(("Foo\r\nBcc: attacker@evil.com", "user@example.com"))
        self.assertNotIn("\r", out)
        self.assertNotIn("\n", out)

    def test_strips_control_chars_from_address(self):
        out = formataddr(("Name", "user\r\n@example.com"))
        self.assertNotIn("\r", out)
        self.assertNotIn("\n", out)


if __name__ == "__main__":
    unittest.main()
