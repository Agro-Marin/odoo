import unittest

from odoo.libs.documents.formats import (
    _BY_EXTENSION,
    Format,
    canonical_mimetypes,
    extension_for,
    get_format,
    get_format_of_extension,
    known_formats,
    mimetype_for,
    mimetypes_for,
    register_extension,
    register_format,
)


class TestLookup(unittest.TestCase):
    def test_extension_to_mimetype(self):
        self.assertEqual(mimetype_for("csv"), "text/csv")
        self.assertEqual(mimetype_for(".csv"), "text/csv")
        self.assertEqual(mimetype_for("XML"), "application/xml")

    def test_mimetype_to_extension(self):
        self.assertEqual(extension_for("text/csv"), "csv")
        self.assertEqual(extension_for("application/json"), "json")

    def test_they_round_trip(self):
        for fmt in known_formats():
            self.assertEqual(mimetype_for(fmt.extension), fmt.mimetype)
            self.assertEqual(extension_for(fmt.mimetype), fmt.extension)

    def test_an_unregistered_name_answers_empty_rather_than_guessing(self):
        self.assertEqual(mimetype_for("zzz"), "")
        self.assertEqual(extension_for("application/x-nothing"), "")

    def test_mimetypes_for_is_the_canonical_name_and_its_aliases(self):
        self.assertEqual(
            mimetypes_for("xml"),
            {"application/xml", "text/xml", "application/xhtml+xml"},
        )
        self.assertEqual(
            mimetypes_for("vtt", "srt"), mimetypes_for("vtt") | mimetypes_for("srt")
        )

    def test_mimetypes_for_refuses_a_name_nobody_registered(self):
        # An empty set would register a reader that reads nothing, silently.
        with self.assertRaises(ValueError):
            mimetypes_for("zzz")

    def test_canonical_mimetypes_leaves_the_aliases_out(self):
        self.assertEqual(
            canonical_mimetypes("csv", "xml"), {"text/csv", "application/xml"}
        )
        with self.assertRaises(ValueError):
            canonical_mimetypes("zzz")

    def test_jpeg_is_a_second_spelling_of_the_jpg_extension(self):
        self.assertEqual(mimetype_for("jpeg"), "image/jpeg")
        self.assertEqual(extension_for("image/jpeg"), "jpg")

    def test_a_format_lists_its_own_spellings(self):
        self.assertEqual(
            self._format("image/jpeg").mimetypes,
            {"image/jpeg", "image/jpg", "image/jpe"},
        )

    def test_an_alias_finds_the_format(self):
        self.assertIs(get_format("text/xml"), get_format("application/xml"))

    def test_an_alias_does_not_name_the_extension(self):
        # `text/plain` is read as rows, and is not what a `.csv` means -- the
        # asymmetry is the point of keeping `accepts` out of `extension_for`.
        self.assertIsNotNone(get_format("text/plain"))
        self.assertEqual(extension_for("text/plain"), "")

    def test_the_representation_is_declared(self):
        self.assertEqual(self._format("text/csv").representation, "rows")
        self.assertEqual(self._format("application/xml").representation, "tree")
        self.assertEqual(self._format("application/json").representation, "data")

    def _format(self, mimetype):
        fmt = get_format(mimetype)
        if fmt is None:
            raise AssertionError(f"{mimetype!r} is registered by nothing")
        return fmt


class TestRegistration(unittest.TestCase):
    def test_a_format_needs_a_mimetype(self):
        with self.assertRaises(ValueError):
            register_format(Format("", "zzz", "rows"))

    def test_a_format_needs_an_extension(self):
        with self.assertRaises(ValueError):
            register_format(Format("application/x-zzz", "", "rows"))

    def test_a_format_needs_a_known_representation(self):
        with self.assertRaises(ValueError):
            register_format(Format("application/x-zzz", "zzz", "spreadsheet"))

    def test_a_mimetype_is_claimed_once(self):
        with self.assertRaises(ValueError):
            register_format(Format("text/csv", "csv2", "rows"))

    def test_an_extension_is_claimed_once(self):
        with self.assertRaises(ValueError):
            register_format(Format("application/x-csv2", "csv", "rows"))


class TestRegisterExtension(unittest.TestCase):
    def setUp(self):
        register_extension("xaf", "application/xml")
        self.addCleanup(_BY_EXTENSION.pop, "xaf", None)

    def test_a_second_extension_resolves_to_the_same_format(self):
        self.assertEqual(mimetype_for("xaf"), "application/xml")
        self.assertIs(get_format_of_extension("xaf"), get_format_of_extension("xml"))

    def test_the_canonical_extension_is_unchanged(self):
        self.assertEqual(extension_for("application/xml"), "xml")

    def test_registering_it_twice_is_harmless(self):
        register_extension("xaf", "application/xml")
        self.assertEqual(mimetype_for("xaf"), "application/xml")

    def test_it_cannot_be_stolen_from_another_format(self):
        with self.assertRaises(ValueError) as caught:
            register_extension("csv", "application/xml")
        self.assertIn("already means", str(caught.exception))

    def test_an_unregistered_mimetype_is_refused(self):
        with self.assertRaises(ValueError):
            register_extension("zzz", "application/x-nothing")

    def test_an_empty_extension_is_refused(self):
        with self.assertRaises(ValueError):
            register_extension("", "application/xml")
