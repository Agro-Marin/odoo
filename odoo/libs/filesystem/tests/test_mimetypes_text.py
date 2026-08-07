import unittest

from odoo.libs.filesystem.mimetypes import UNKNOWN_MIMETYPE, _odoo_guess_mimetype


class TestMultibyteAtTheCut(unittest.TestCase):
    def test_char_straddling_the_boundary(self):
        data = ("a" * 1022 + "\N{EURO SIGN}" + "b" * 3000).encode()
        self.assertEqual(_odoo_guess_mimetype(data), "text/plain")

    def test_char_starting_one_byte_before_the_boundary(self):
        data = ("a" * 1023 + "\N{EURO SIGN}" + "b" * 3000).encode()
        self.assertEqual(_odoo_guess_mimetype(data), "text/plain")

    def test_four_byte_char_at_every_offset_near_the_cut(self):
        for pad in range(1018, 1026):
            with self.subTest(pad=pad):
                data = ("a" * pad + "\N{PARTY POPPER}" + "b" * 2000).encode()
                self.assertEqual(_odoo_guess_mimetype(data), "text/plain")

    def test_multibyte_well_inside_the_window(self):
        data = ("a" * 500 + "\N{EURO SIGN}" + "b" * 3000).encode()
        self.assertEqual(_odoo_guess_mimetype(data), "text/plain")


class TestStillRejectsBinary(unittest.TestCase):
    def test_invalid_utf8_in_the_body(self):
        self.assertEqual(
            _odoo_guess_mimetype(b"hello" + b"\xff\xfe" + b"world"), UNKNOWN_MIMETYPE
        )

    def test_latin1_bytes(self):
        self.assertEqual(
            _odoo_guess_mimetype("caf\xe9".encode("latin-1") * 300), UNKNOWN_MIMETYPE
        )

    def test_nul_byte(self):
        self.assertEqual(_odoo_guess_mimetype(b"text\x00text"), UNKNOWN_MIMETYPE)

    def test_control_characters(self):
        self.assertEqual(_odoo_guess_mimetype(b"text\x07bell"), UNKNOWN_MIMETYPE)

    def test_empty(self):
        self.assertEqual(_odoo_guess_mimetype(b""), UNKNOWN_MIMETYPE)

    def test_custom_default_is_honoured(self):
        self.assertEqual(_odoo_guess_mimetype(b"\x00\x01", default="x/y"), "x/y")


class TestPlainText(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(_odoo_guess_mimetype(b"plain text"), "text/plain")

    def test_tabs_and_newlines_allowed(self):
        self.assertEqual(_odoo_guess_mimetype(b"a\tb\r\nc\n"), "text/plain")

    def test_utf8_astral_plane(self):
        self.assertEqual(
            _odoo_guess_mimetype("hi \N{PARTY POPPER} there".encode()), "text/plain"
        )

    def test_signature_detection_still_wins(self):
        self.assertEqual(_odoo_guess_mimetype(b"%PDF-1.4 rest"), "application/pdf")


class TestNoStateLeakBetweenCalls(unittest.TestCase):
    def test_truncated_then_binary(self):
        truncated = ("a" * 1023 + "\N{EURO SIGN}").encode()
        self.assertEqual(_odoo_guess_mimetype(truncated), "text/plain")
        self.assertEqual(_odoo_guess_mimetype(b"\xff\xfe\x00"), UNKNOWN_MIMETYPE)

    def test_repeated_truncated_calls_are_stable(self):
        data = ("a" * 1022 + "\N{EURO SIGN}" + "b" * 100).encode()
        self.assertEqual(
            [_odoo_guess_mimetype(data) for _ in range(3)], ["text/plain"] * 3
        )


if __name__ == "__main__":
    unittest.main()
