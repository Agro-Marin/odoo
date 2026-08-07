import unittest

from babel import Locale

from odoo.libs.locale.conversions import posix_to_ldml

EN = Locale.parse("en_US")


class TestPosixToLdml(unittest.TestCase):
    def test_basic_pattern(self):
        self.assertEqual(posix_to_ldml("%Y-%m-%d", EN), "yyyy-MM-dd")

    def test_space_padded_day(self):
        self.assertEqual(posix_to_ldml("%e/%m/%Y", EN), "d/MM/yyyy")

    def test_unknown_directive_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            posix_to_ldml("%q/%Y", EN)
        self.assertIn("%q", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
