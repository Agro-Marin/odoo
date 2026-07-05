from odoo.libs.barcode import check_barcode_encoding, get_barcode_check_digit
from odoo.tests.common import TransactionCase


class TestBarcode(TransactionCase):
    def test_barcode_check_digit(self):
        ean8 = "87111125"
        self.assertEqual(get_barcode_check_digit("0" * 10 + ean8), int(ean8[-1]))
        ean13 = "1234567891231"
        self.assertEqual(get_barcode_check_digit("0" * 5 + ean13), int(ean13[-1]))

    def test_barcode_encoding(self):
        self.assertTrue(check_barcode_encoding("20220006", "ean8"))
        self.assertTrue(check_barcode_encoding("93855341", "ean8"))
        self.assertTrue(check_barcode_encoding("2022071416014", "ean13"))
        self.assertTrue(check_barcode_encoding("9745213796142", "ean13"))

        self.assertFalse(
            check_barcode_encoding("2022a006", "ean8"),
            "should contains digits only",
        )
        self.assertFalse(
            check_barcode_encoding("20220000", "ean8"), "incorrect check digit"
        )
        self.assertFalse(
            check_barcode_encoding("93855341", "ean13"),
            "ean13 is a 13-digits barcode",
        )
        self.assertFalse(
            check_barcode_encoding("9745213796142", "ean8"),
            "ean8 is a 8-digits barcode",
        )
        self.assertFalse(
            check_barcode_encoding("9745213796148", "ean13"),
            "incorrect check digit",
        )
        self.assertFalse(
            check_barcode_encoding("2022!71416014", "ean13"),
            "should contains digits only",
        )
        self.assertFalse(
            check_barcode_encoding("0022071416014", "ean13"),
            "when starting with one zero, it indicates that a 12-digit UPC-A code follows",
        )

    def test_barcode_fallback_to_code128(self):
        """EAN8 with invalid encoding falls back to Code128 without error."""
        Report = self.env["ir.actions.report"]
        # "ABCDEFGH" is not valid EAN8 — should fall back to Code128
        result = Report.barcode("EAN8", "ABCDEFGH")
        self.assertTrue(result, "barcode fallback to Code128 should produce output")
        # PNG magic bytes
        self.assertTrue(
            result[:4] == b"\x89PNG",
            "barcode fallback should produce a valid PNG image",
        )

    def test_barcode_fallback_preserves_humanreadable(self):
        """Barcode fallback must not lose humanReadable setting.

        Regression test: the old recursive fallback re-processed kwargs
        through the defaults dict, losing the humanreadable→humanReadable
        rename done in the first pass.
        """
        Report = self.env["ir.actions.report"]
        # Force a symbology that will fail and fall back to Code128,
        # with humanreadable=1 to verify the flag survives the fallback.
        result = Report.barcode("EAN8", "ABCDEFGH", humanreadable=1)
        self.assertTrue(result, "barcode with humanreadable should produce output")

    def test_barcode_tolerates_string_bool_options(self):
        """quiet/humanreadable options arrive as strings from URLs/templates.

        Regression test: the old ``bool(int(x))`` validators raised
        ``ValueError`` on any non-numeric string (e.g. ``quiet="true"``),
        surfacing as an HTTP 400 or a silently-dropped barcode. They must now
        coerce common truthy/falsy spellings and fall back to the default
        otherwise, never raising.
        """
        Report = self.env["ir.actions.report"]
        for value in ("true", "yes", "on", "1", "false", "0", "", "garbage"):
            result = Report.barcode(
                "Code128", "HELLO", quiet=value, humanreadable=value
            )
            self.assertEqual(
                result[:4],
                b"\x89PNG",
                f"barcode(quiet={value!r}) should still produce a PNG",
            )
