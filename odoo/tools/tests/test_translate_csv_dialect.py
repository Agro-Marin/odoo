import csv
import io
import unittest

from odoo.tools.translate import CSVFileWriter


class TestTranslationCsvDialect(unittest.TestCase):
    """The dialect this writer needs is neither of the stdlib's.

    It used to be registered globally as `"UNIX"` from
    `_monkeypatches/csv.py` -- Odoo's own configuration living in a
    third-party registry, reachable by name from anywhere, and silently
    dependent on a monkeypatch having run first. It is now private to its
    one caller, so these assertions are what keep it honest.
    """

    def _write(self, rows):
        target = io.BytesIO()
        CSVFileWriter(target).write_rows(rows)
        return target.getvalue().decode()

    def test_rows_end_in_lf_not_crlf(self):
        """`csv.excel`, the base, writes CRLF; .po/.csv catalogs want LF."""
        written = self._write([])
        self.assertTrue(written.endswith("\n"))
        self.assertNotIn("\r", written)

    def test_only_fields_that_need_quoting_are_quoted(self):
        """`csv.unix_dialect` would quote all seven columns of every row."""
        written = self._write(
            [("base", "code", "addons/base/x.py", "0", "plain", "traduccion", [])]
        )
        self.assertIn("base,code,", written)

    def test_a_field_containing_the_delimiter_is_still_quoted(self):
        written = self._write([("base", "code", "x.py", "0", "a,b", "c,d", [])])
        self.assertIn('"a,b"', written)

    def test_embedded_newlines_survive_a_round_trip(self):
        """Comments are joined with "\\n", so the quoting has to hold them."""
        written = self._write(
            [("base", "code", "x.py", "0", "src", "val", ["one", "two"])]
        )
        rows = list(csv.reader(io.StringIO(written)))
        self.assertEqual(rows[1][6], "one\ntwo")

    def test_the_header_is_written_once_on_construction(self):
        self.assertEqual(
            self._write([]).splitlines(),
            ["module,type,name,res_id,src,value,comments"],
        )
