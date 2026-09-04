import unittest
from unittest import mock

import odoo.libs.barcode as barcode_module
from odoo.libs.barcode import (
    check_barcode_encoding,
    createBarcodeDrawing,
    get_barcode_font,
)


class TestBarcodeFontInitFallback(unittest.TestCase):
    def setUp(self):
        self._saved_init = barcode_module._barcode_init
        barcode_module._barcode_init = None
        self.addCleanup(self._restore)

    def _restore(self):
        barcode_module._barcode_init = self._saved_init

    def test_falls_back_to_courier_when_font_lookup_raises(self):
        with mock.patch(
            "reportlab.pdfbase.pdfmetrics.TypeFace.findT1File",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(get_barcode_font(), "Courier")

    def test_falls_back_to_courier_when_drawing_render_raises(self):
        with mock.patch(
            "reportlab.graphics.barcode.createBarcodeDrawing",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(get_barcode_font(), "Courier")

    def test_createBarcodeDrawing_delegates_after_init(self):
        drawing = createBarcodeDrawing(
            "Code128", value="foo", format="png", width=10, height=10
        )
        self.assertIsNotNone(drawing)


class TestCheckBarcodeEncoding(unittest.TestCase):
    def test_empty_value_does_not_raise(self):
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
