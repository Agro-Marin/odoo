import struct
import unittest

from odoo.libs.documents.guess import decode, guess_encoding, guess_mimetype


def _bmp() -> bytes:
    pixel = b"\x00\x00\xff\x00"
    header = struct.pack(
        "<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, len(pixel), 2835, 2835, 0, 0
    )
    return (
        b"BM"
        + struct.pack("<IHHI", 14 + len(header) + len(pixel), 0, 0, 14 + len(header))
        + header
        + pixel
    )


class TestGuessEncoding(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(guess_encoding("Café Ñoño".encode()), "utf-8")

    def test_latin1_is_not_utf8(self):
        self.assertNotEqual(guess_encoding("Café".encode("latin-1")), "utf-8")

    def test_undetectable_answers_none(self):
        self.assertIsNone(guess_encoding(bytes([0x81, 0x8D, 0x8F, 0x90, 0x9D])))

    def test_bom_marked_utf16_loses_its_endianness_suffix(self):
        # The suffixed name tells Python to keep the BOM as content; the
        # unmarked one strips it, which is what a document reader wants.
        data = "name,total\n".encode("utf-16")
        self.assertEqual(guess_encoding(data), "utf-16")
        self.assertFalse(decode(data).startswith("﻿"))

    def test_a_codec_python_cannot_load_is_not_a_guess(self):
        from unittest import mock

        from odoo.libs.documents import guess as module

        detector = mock.Mock()
        detector.done = True
        detector.result = {"encoding": "EUC-TW"}
        with mock.patch.object(
            module.chardet, "UniversalDetector", return_value=detector
        ):
            self.assertIsNone(guess_encoding(b"whatever"))

    def test_non_ascii_past_the_first_chunk(self):
        # The window-based implementations this replaced answered "ascii" here.
        data = b"a" * (1 << 17) + "é".encode("latin-1")
        self.assertNotIn(guess_encoding(data), (None, "ascii"))


class TestDecode(unittest.TestCase):
    def test_latin1_round_trips_without_replacement_characters(self):
        self.assertEqual(decode("Café".encode("latin-1")), "Café")

    def test_declared_encoding_is_used(self):
        self.assertEqual(decode("Café".encode("cp1252"), "cp1252"), "Café")

    def test_undetectable_raises_rather_than_substituting(self):
        with self.assertRaises(UnicodeDecodeError):
            decode(bytes([0x81, 0x8D, 0x8F, 0x90, 0x9D]))

    def test_wrong_declared_encoding_raises(self):
        with self.assertRaises(UnicodeDecodeError):
            decode("Café".encode("latin-1"), "utf-8")


class TestGuessMimetype(unittest.TestCase):
    def test_binary_formats(self):
        for data, expected in (
            (b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", "application/pdf"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png"),
            (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32, "image/jpeg"),
            (b"GIF89a" + b"\x00" * 32, "image/gif"),
            (b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32, "image/webp"),
            (_bmp(), "image/bmp"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(guess_mimetype(data), expected)

    def test_xml_without_a_prolog(self):
        # libmagic places structured text by its declaration alone, so this is
        # text/plain to it -- and plenty of EDI payloads arrive this way.
        self.assertEqual(
            guess_mimetype(b"<Invoice><Total/></Invoice>"), "application/xml"
        )

    def test_xml_with_a_prolog(self):
        self.assertTrue(guess_mimetype(b'<?xml version="1.0"?><a/>').endswith("/xml"))

    def test_html_is_not_reported_as_xml(self):
        self.assertEqual(guess_mimetype(b"<html><body>x</body></html>"), "text/html")

    def test_json(self):
        self.assertEqual(guess_mimetype(b'{"total": 12.5}'), "application/json")
        self.assertEqual(guess_mimetype(b"  \n[{}]"), "application/json")

    def test_spreadsheet_is_placed_not_left_unknown(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
        self.assertEqual(
            guess_mimetype(buf.getvalue()),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_a_declaration_that_says_something_wins(self):
        self.assertEqual(guess_mimetype(b"%PDF-1.4\n", "text/csv"), "text/csv")

    def test_a_declaration_that_says_nothing_does_not(self):
        for declared in ("", "application/octet-stream", "text/plain"):
            with self.subTest(declared=declared):
                self.assertEqual(
                    guess_mimetype(b"%PDF-1.4\n", declared), "application/pdf"
                )

    def test_empty(self):
        self.assertEqual(guess_mimetype(b""), "application/x-empty")
