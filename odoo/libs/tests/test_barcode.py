"""Regression tests for ``odoo.libs.barcode.check_barcode_encoding``."""

import unittest

from odoo.libs.barcode import check_barcode_encoding


class TestCheckBarcodeEncoding(unittest.TestCase):
    def test_empty_value_does_not_raise(self):
        # an empty EAN field reaches this from the report barcode widget; it must
        # return False, not IndexError on barcode[0].
        self.assertFalse(check_barcode_encoding("", "ean13"))
        self.assertFalse(check_barcode_encoding("", "ean8"))

    def test_unknown_encoding_returns_false(self):
        self.assertFalse(check_barcode_encoding("12345", "code128"))

    def test_valid_ean13(self):
        self.assertTrue(check_barcode_encoding("2022071416014", "ean13"))

    def test_wrong_length_returns_false(self):
        self.assertFalse(check_barcode_encoding("123", "ean13"))

    def test_any_encoding(self):
        self.assertTrue(check_barcode_encoding("whatever", "any"))

    def test_returns_bool(self):
        self.assertIsInstance(check_barcode_encoding("abc", "ean13"), bool)


if __name__ == "__main__":
    unittest.main()
