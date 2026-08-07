import unittest

from odoo.libs.barcode import check_barcode_encoding, get_barcode_check_digit


class TestRejectsNonDigits(unittest.TestCase):
    def test_letters(self):
        with self.assertRaises(ValueError) as ctx:
            get_barcode_check_digit("abcdefghijklm")
        self.assertIn("abcdefghijklm", str(ctx.exception))

    def test_mixed(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit("12345abc90123")

    def test_punctuation(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit("12-4567890123")

    def test_empty(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit("")

    def test_none(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit(None)

    def test_whitespace(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit(" 1234567")

    def test_non_ascii_digits_rejected(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit("１２３４５６７８")

    def test_superscript_digits_rejected(self):
        with self.assertRaises(ValueError):
            get_barcode_check_digit("¹²³")


class TestCheckDigitStillCorrect(unittest.TestCase):
    def test_known_ean13(self):
        self.assertEqual(get_barcode_check_digit("5449000096241"), 1)

    def test_known_ean8(self):
        self.assertEqual(get_barcode_check_digit("96385074"), 4)

    def test_length_independent(self):
        self.assertEqual(
            get_barcode_check_digit("96385074"),
            get_barcode_check_digit("0" * 5 + "96385074"),
        )

    def test_single_digit(self):
        self.assertEqual(get_barcode_check_digit("7"), 0)


class TestCheckBarcodeEncodingUnaffected(unittest.TestCase):
    def test_letters_return_false(self):
        self.assertFalse(check_barcode_encoding("abcdefgh", "ean8"))

    def test_empty_returns_false(self):
        self.assertFalse(check_barcode_encoding("", "ean13"))

    def test_wrong_length_returns_false(self):
        self.assertFalse(check_barcode_encoding("123", "ean8"))

    def test_valid_ean8(self):
        self.assertTrue(check_barcode_encoding("96385074", "ean8"))

    def test_any_encoding(self):
        self.assertTrue(check_barcode_encoding("whatever", "any"))

    def test_unknown_encoding(self):
        self.assertFalse(check_barcode_encoding("96385074", "gs1-128"))


if __name__ == "__main__":
    unittest.main()
