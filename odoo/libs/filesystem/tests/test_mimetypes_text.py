import unittest

from odoo.libs.filesystem.mimetypes import (
    MIMETYPE_HEAD_SIZE,
    UNKNOWN_MIMETYPE,
    _check_olecf,
    _odoo_guess_mimetype,
    guess_mimetype,
)


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


class TestBytearrayMatchesBytes(unittest.TestCase):
    """A bytearray must classify exactly as the same bytes do.

    guess_mimetype truncated the bytearray branch to MIMETYPE_HEAD_SIZE and
    rebound the name, so the signature fallback -- which runs on the FULL buffer
    for a bytes input -- saw only a 2048-byte head. A zip's central directory is
    at the end of the file, so every OOXML/ODF buffer handed in as a bytearray
    degraded to application/zip.
    """

    @staticmethod
    def _minimal_xlsx() -> bytes:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/workbook.xml", "<workbook/>")
            # Pad past MIMETYPE_HEAD_SIZE so the truncation is what decides it,
            # not the file simply being small enough to survive the cut.
            z.writestr("xl/pad.bin", b"\0" * (MIMETYPE_HEAD_SIZE * 4))
        return buf.getvalue()

    def test_ooxml_survives_the_bytearray_branch(self):
        raw = self._minimal_xlsx()
        self.assertGreater(len(raw), MIMETYPE_HEAD_SIZE)
        expected = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        self.assertEqual(_odoo_guess_mimetype(raw), expected)
        self.assertEqual(guess_mimetype(raw), expected)
        self.assertEqual(guess_mimetype(bytearray(raw)), expected)

    def test_bytes_and_bytearray_agree_across_kinds(self):
        for name, raw in (
            ("xlsx", self._minimal_xlsx()),
            ("png", b"\x89PNG\r\n\x1a\n" + b"\0" * 4000),
            ("pdf", b"%PDF-1.7\n" + b"x" * 4000),
            ("text", b"hello world\n" * 400),
            ("binary", b"\xff\xfe\x00\x01" + b"\xab" * 4000),
        ):
            with self.subTest(kind=name):
                self.assertEqual(
                    guess_mimetype(bytearray(raw)),
                    guess_mimetype(raw),
                    msg=f"{name}: bytearray and bytes must not disagree",
                )

    def test_rejects_other_types(self):
        with self.assertRaises(TypeError):
            # The wrong type is the point of the test; odoo/libs/ is inside the
            # mypy gate's scope, tests included, so the call needs the waiver.
            guess_mimetype("not bytes")  # type: ignore[arg-type]


class TestOlecfStreamNames(unittest.TestCase):
    """OLE subtype detection must not depend on which sector a stream landed in.

    _check_olecf read three fixed offsets: the Word FIB signature at 0x200, a
    "Microsoft Excel" substring, and the PowerPoint pattern at 0x200. 0x200 is
    the first sector after the 512-byte header, which holds the stream only when
    the FAT happened to allocate it first. A real Word 97 document that did not
    fall that way returned False and was served as application/x-ole-storage --
    the container type, and not an IANA-registered mimetype at all.
    """

    OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def _olecf(self, stream_name: str, sector: int = 3) -> bytes:
        """An OLE header plus a directory entry name at a NON-first sector."""
        buf = bytearray(self.OLE_MAGIC + b"\0" * (0x200 * sector))
        buf += stream_name.encode("utf-16-le")
        buf += b"\0" * 512
        return bytes(buf)

    def test_word_stream_away_from_the_first_sector(self):
        data = self._olecf("WordDocument")
        self.assertFalse(data.startswith(b"\xec\xa5\xc1\x00", 0x200))
        self.assertEqual(_check_olecf(data), "application/msword")
        self.assertEqual(_odoo_guess_mimetype(data), "application/msword")

    def test_excel_and_powerpoint_streams(self):
        for stream, expected in (
            ("Workbook", "application/vnd.ms-excel"),
            ("Book", "application/vnd.ms-excel"),
            ("PowerPoint Document", "application/vnd.ms-powerpoint"),
        ):
            with self.subTest(stream=stream):
                self.assertEqual(_check_olecf(self._olecf(stream)), expected)

    def test_first_sector_signature_still_wins(self):
        # The original fast path must keep working where it did apply.
        data = self.OLE_MAGIC + b"\0" * (0x200 - 8) + b"\xec\xa5\xc1\x00" + b"\0" * 512
        self.assertEqual(_check_olecf(data), "application/msword")

    def test_unknown_olecf_is_still_rejected(self):
        data = self.OLE_MAGIC + b"\0" * 2048
        self.assertIs(_check_olecf(data), False)


if __name__ == "__main__":
    unittest.main()
