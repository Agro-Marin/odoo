"""Regression tests for ``odoo.libs.text.strings`` helpers."""

import unittest

from odoo.libs.text.strings import get_flag


class TestGetFlag(unittest.TestCase):
    def test_uppercase_code(self):
        self.assertEqual(get_flag("US"), "\U0001f1fa\U0001f1f8")

    def test_lowercase_code_does_not_crash(self):
        # a lowercase code used to push chr() past the max codepoint and raise
        self.assertEqual(get_flag("us"), get_flag("US"))
        self.assertEqual(get_flag("mx"), get_flag("MX"))


if __name__ == "__main__":
    unittest.main()
