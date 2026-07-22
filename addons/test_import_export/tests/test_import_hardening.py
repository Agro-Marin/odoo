import datetime
import unittest
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, can_import

from odoo.addons.base_import.models.base_import import ImportValidationError


class ImportHardeningCase(TransactionCase):
    """ Regression tests for the t24068 correctness/security audit of
    `base_import` (see the campaign ledger, findings F1/F2/F4/F11/F19). Each
    test reproduces a case that crashed with an unhandled, non-
    `ImportValidationError` exception (or leaked memory unboundedly) instead
    of failing cleanly, reachable when `execute_import`/engine internals are
    called directly (RPC, automation, or any caller that skips the UI's
    `parse_preview` step, which happens to mask some of these cases).
    """

    def _make_import(self, res_model='import.char', **vals):
        vals.setdefault('res_model', res_model)
        return self.env['base_import.import'].create(vals)

    def test_execute_import_empty_file_raises_clean_error(self):
        """ F4a: `_read_csv` used to `return ()` for a completely empty file;
        unpacking that into `file_length, rows_to_import` raised an unhandled
        `ValueError` inside `_convert_import_data`, escaping `execute_import`
        (which only catches `ImportValidationError`). """
        imp = self._make_import(file=b'', file_name='empty.csv', file_type='text/csv')
        result = imp.execute_import(['value'], ['Value'], {'has_headers': False, 'quoting': '"'})
        self.assertTrue(result.get('messages'))
        self.assertIn('no content', result['messages'][0]['message'])

    def test_execute_import_blank_rows_raises_clean_error(self):
        """ F4b: a non-empty file whose rows are all blank makes `_read_csv`
        return `(0, [])` (not the bare `()` above); `_convert_import_data`
        indexed `rows_to_import[0]` unconditionally, raising an unhandled
        `IndexError`. Distinct code path from the empty-file case. """
        imp = self._make_import(file=b'\n\n\n', file_name='blank.csv', file_type='text/csv')
        result = imp.execute_import(['value'], ['Value'], {'has_headers': False, 'quoting': '"'})
        self.assertTrue(result.get('messages'))
        self.assertIn('no content', result['messages'][0]['message'])

    def test_read_csv_undetectable_encoding_raises_clean_error(self):
        """ F19: `chardet.detect()` can return `{'encoding': None}` for
        ambiguous byte content; calling `.lower()` on that `None` used to
        raise an unhandled `AttributeError` instead of a clean
        `ImportValidationError`. """
        imp = self._make_import(file=b'a,b,c', file_name='x.csv', file_type='text/csv')
        with patch(
            'odoo.addons.base_import.models.base_import.chardet.detect',
            return_value={'encoding': None, 'confidence': 0.0},
        ), self.assertRaises(ImportValidationError):
            imp._read_csv({'quoting': '"'})

    def test_import_file_by_url_oversized_reports_specific_error(self):
        """ F2: `_import_file_by_url` raises its own specific
        `ImportValidationError` when `Content-Length` exceeds
        `import_file_maxbytes`, but its outer `except Exception` used to
        re-catch that same error and re-wrap it into a generic "Could not
        retrieve URL" message with no `field`/`field_type` — losing both the
        actionable text and the client-side column routing. """
        imp = self._make_import()
        fake_response = MagicMock(headers={'Content-Length': str(10**9)})
        fake_session = MagicMock()
        fake_session.get.return_value = fake_response

        with self.assertRaises(ImportValidationError) as cm:
            imp._import_file_by_url('http://example.com/big.png', fake_session, 'image_field', 0)

        self.assertIn('exceeds configured maximum', cm.exception.message)
        self.assertEqual(cm.exception.field_path, ['image_field'])

    def test_binary_field_date_value_does_not_crash(self):
        """ F11: `_read_xlsx`/`_read_xls` return native `date`/`datetime`
        objects for date-formatted cells. If such a cell lands in a column
        mapped to a `binary`+`attachment` field (e.g. `res.partner.image_1920`),
        every branch of the binary-import loop (`re.match` / `'.' in ...` /
        `base64.b64decode`) assumed a string and used to raise an unhandled
        `TypeError`. A date is not valid image data by any of the 3
        interpretations (URL, filename, base64), so the correct outcome is a
        clean `ImportValidationError` — not a crash. """
        imp = self._make_import(res_model='res.partner')
        data = [[datetime.date(2024, 1, 1)]]
        with self.assertRaises(ImportValidationError):
            imp._parse_import_data_recursive('res.partner', '', data, ['image_1920'], {})


@unittest.skipUnless(can_import("odf"), "odfpy not installed")
class TestODSReaderHardening(unittest.TestCase):
    """ F1: `numbercolumnsrepeated`/`numbercolumnsspanned` are ODS XML
    attributes fully controlled by the uploaded file's author. Without a cap,
    `ODSReader.readSheet` builds `[textContent] * repeat` unbounded — a
    crafted cell declaring a huge repeat count OOM-crashes the worker. No env/
    DB access needed, so this doesn't inherit TransactionCase.

    Guarded by `can_import("odf")`: odfpy is an optional dependency (not
    listed in requirements.txt — see the t24068 ledger's F20-adjacent gap) and
    is not installed in every dev/CI environment; this test runs for real
    wherever it is.
    """

    def _build_doc_with_repeat(self, repeat_value):
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableCell, TableRow
        from odf.text import P

        doc = OpenDocumentSpreadsheet()
        table = Table(name="Sheet1")
        row = TableRow()
        # A non-last cell carrying an attacker-controlled repeat count: readSheet
        # only reads `numbercolumnsrepeated` on non-last cells (the true last
        # cell of a row is a legitimate "repeat to end of used range" marker).
        # `setAttribute` mirrors the reader's own `getAttribute` calls exactly
        # (same attribute names), unlike guessing at constructor kwarg names.
        repeated_cell = TableCell()
        repeated_cell.setAttribute("numbercolumnsrepeated", str(repeat_value))
        repeated_cell.addElement(P(text="x"))
        row.addElement(repeated_cell)
        row.addElement(TableCell())  # trailing cell, keeps the crafted one non-last
        table.addElement(row)
        doc.spreadsheet.addElement(table)
        return doc

    def test_repeat_count_is_capped(self):
        from odoo.addons.base_import.models.odf_ods_reader import (
            MAX_CELL_REPEAT,
            ODSReader,
        )

        doc = self._build_doc_with_repeat(10**8)
        reader = ODSReader(content=doc)
        row = reader.getSheet("Sheet1")[0]
        self.assertLessEqual(len(row), MAX_CELL_REPEAT + 1)  # +1 for the trailing empty cell
