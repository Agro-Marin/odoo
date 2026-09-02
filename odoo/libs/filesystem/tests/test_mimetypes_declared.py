import io
import struct
import unittest
import zipfile

from odoo.libs.filesystem.mimetypes import guess_mimetype


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


class TestGuessMimetypeWithADeclaration(unittest.TestCase):
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

    def test_prose_that_opens_like_a_tag_stays_text(self):
        self.assertEqual(
            guess_mimetype(b"<note> this is prose, not a tree"), "text/plain"
        )

    def test_json(self):
        self.assertEqual(guess_mimetype(b'{"total": 12.5}'), "application/json")
        self.assertEqual(guess_mimetype(b"  \n[{}]"), "application/json")

    def test_spreadsheet_is_placed_not_left_unknown(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
        self.assertEqual(
            guess_mimetype(buf.getvalue()),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_a_declaration_that_says_something_wins(self):
        self.assertEqual(guess_mimetype(b"%PDF-1.4\n", declared="text/csv"), "text/csv")

    def test_a_declaration_is_normalised_to_lower_case(self):
        self.assertEqual(guess_mimetype(b"%PDF-1.4\n", declared="Text/CSV"), "text/csv")

    def test_a_declaration_that_says_nothing_does_not(self):
        for declared in ("", "application/octet-stream", "text/plain"):
            with self.subTest(declared=declared):
                self.assertEqual(
                    guess_mimetype(b"%PDF-1.4\n", declared=declared), "application/pdf"
                )

    def test_the_default_still_names_what_nothing_placed(self):
        self.assertEqual(guess_mimetype(b"\x00\x01\x02", default="x/y"), "x/y")

    def test_empty(self):
        self.assertEqual(guess_mimetype(b""), "application/x-empty")
