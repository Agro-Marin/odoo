import builtins
import io
import zipfile
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.base_import.models import zip_guard

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook_of(rows):
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _archive_of(size):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * size)
    return buffer.getvalue()


class TestZipMemberCap(TransactionCase):
    """The oversized-member guard writes for the person who uploaded the file.

    Twice now the message has been read as a developer diagnostic -- it raises
    from a helper, out of a module whose other errors are internal -- and the
    gettext call stripped off it on the way past. It is neither: both callers
    are import readers, and `_get_preview_error` reports it verbatim into the
    import UI. These tests say so from the outside, where the next reader of
    `gettext-developer-error` will trip over them.
    """

    def _import_record(self, data):
        return self.env["base_import.import"].create(
            {
                "res_model": "res.partner",
                "file": data,
                "file_type": XLSX_TYPE,
                "file_name": "big.xlsx",
            }
        )

    def _preview(self, data):
        record = self._import_record(data)
        with patch.object(zip_guard, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024):
            return record.parse_preview({"has_headers": True})

    def test_the_cap_message_reaches_the_import_ui(self):
        result = self._preview(_archive_of(4096))
        self.assertIn("error", result)
        self.assertIn(
            "would expand to more than",
            result["error"],
            "the uploader is told what is wrong with their file, not a generic "
            "sentence -- so this string is UI and belongs in the catalogue",
        )

    def test_the_guard_raises_a_user_error_and_not_a_builtin(self):
        with (
            patch.object(zip_guard, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024),
            self.assertRaises(UserError),
        ):
            zip_guard.check_zip_member_sizes(io.BytesIO(_archive_of(4096)))

    def test_an_archive_under_the_cap_is_let_through(self):
        # Not a tautology: a guard that refused everything would pass the two
        # assertions above and break every spreadsheet import in the product.
        with patch.object(zip_guard, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024):
            zip_guard.check_zip_member_sizes(io.BytesIO(_archive_of(16)))

    def test_reading_a_spreadsheet_does_not_need_the_ods_library(self):
        # The guard is shared with the `.ods` reader, and used to live in it.
        # `.xlsx` is registered against openpyxl alone, so importing a
        # spreadsheet must not fail on a box where the optional odfpy is not
        # installed -- which is where this was found.
        real_import = builtins.__import__

        def without_odf(name, *args, **kwargs):
            if name == "odf" or name.startswith("odf."):
                raise ModuleNotFoundError("No module named 'odf'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", without_odf):
            record = self._import_record(_workbook_of([["name"], ["Alice"]]))
            result = record.parse_preview({"has_headers": True})

        self.assertNotIn("error", result, result.get("error"))
        self.assertEqual(result["preview"], [["Alice"]])
