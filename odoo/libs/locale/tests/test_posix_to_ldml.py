"""Regression tests for ``odoo.libs.locale.conversions.posix_to_ldml``."""

import unittest

from babel import Locale

from odoo.libs.locale.conversions import posix_to_ldml

EN = Locale.parse("en_US")


class TestPosixToLdml(unittest.TestCase):
    def test_basic_pattern(self):
        self.assertEqual(posix_to_ldml("%Y-%m-%d", EN), "yyyy-MM-dd")

    def test_space_padded_day(self):
        # %e is a valid glibc directive an admin may enter in res.lang.date_format
        self.assertEqual(posix_to_ldml("%e/%m/%Y", EN), "d/MM/yyyy")

    def test_unknown_directive_raises_value_error(self):
        # user-editable format: a clear ValueError beats a bare KeyError that
        # reads as an internal crash during date rendering.
        with self.assertRaises(ValueError) as cm:
            posix_to_ldml("%q/%Y", EN)
        self.assertIn("%q", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
