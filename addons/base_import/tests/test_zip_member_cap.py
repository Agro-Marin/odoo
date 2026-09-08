import io
import zipfile
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.base_import.models import odf_ods_reader

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    def _preview(self, data):
        record = self.env["base_import.import"].create(
            {
                "res_model": "res.partner",
                "file": data,
                "file_type": XLSX_TYPE,
                "file_name": "big.xlsx",
            }
        )
        with patch.object(odf_ods_reader, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024):
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
            patch.object(odf_ods_reader, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024),
            self.assertRaises(UserError),
        ):
            odf_ods_reader._check_zip_member_sizes(io.BytesIO(_archive_of(4096)))

    def test_an_archive_under_the_cap_is_let_through(self):
        # Not a tautology: a guard that refused everything would pass the two
        # assertions above and break every spreadsheet import in the product.
        with patch.object(odf_ods_reader, "MAX_UNCOMPRESSED_MEMBER_SIZE", 1024):
            odf_ods_reader._check_zip_member_sizes(io.BytesIO(_archive_of(16)))
