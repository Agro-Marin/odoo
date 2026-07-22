import io
from http import HTTPStatus
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

from odoo import http
from odoo.libs.json import dumps as json_dumps
from odoo.tests.common import HttpCase, tagged


@tagged("web_http", "web_pivot")
class TestPivotExport(HttpCase):
    def test_export_xlsx_with_integer_column(self):
        """Int header titles and cell values are written as numbers, not coerced to text."""
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Sales Analysis",
            "model": "sale.report",
            "measure_count": 1,
            "origin_count": 1,
            "col_group_headers": [
                [{"title": 500, "width": 1, "height": 1}],
            ],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [
                {"title": 1, "indent": 0, "values": [{"value": 42}]},
            ],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        response.raise_for_status()
        zip_file = ZipFile(io.BytesIO(response.content))

        with zip_file.open("xl/worksheets/sheet1.xml") as file:
            sheet_tree = etree.parse(file)
        xml_data = {}

        for c in sheet_tree.iterfind(
            ".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
        ):
            cell_ref = c.attrib["r"]
            value = c.findtext(
                "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v"
            )
            xml_data[cell_ref] = value

        self.assertEqual(xml_data["B1"], "500")
        self.assertEqual(xml_data["A2"], "0")
        self.assertEqual(xml_data["B2"], "42")

    def test_export_xlsx_non_numeric_sizes_are_handled(self):
        """Non-numeric count/size fields must degrade to 0, not raise a 500.

        ``measure_count``/``width``/``height``/``indent`` are raw client JSON. A
        bare ``min(value, 100000)`` on a string raised ``TypeError`` (Py3 forbids
        str/int comparison) -> 500; they are now coerced defensively.
        """
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Bad sizes",
            "model": "res.partner",
            "measure_count": "not-a-number",
            "origin_count": 1,
            "col_group_headers": [
                [{"title": "h", "width": "wide", "height": "tall"}],
            ],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [{"title": "r", "indent": "deep", "values": [{"value": 1}]}],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(
            response.status_code,
            200,
            f"non-numeric sizes must be coerced, not 500: {response.text[:200]}",
        )

    def test_export_xlsx_oversized_cell_string_is_truncated(self):
        """A multi-hundred-KB cell string is clamped to Excel's 32767 limit.

        The cell-COUNT cap counts cells, not per-cell length, so an unbounded
        title/value would be built into a single write and could OOM the worker.
        Strings are now truncated at ``MAX_CELL_CHARS`` before any write.
        """
        self.authenticate("admin", "admin")
        long_title = "A" * 100_000
        jdata = {
            "title": "Long",
            "model": "res.partner",
            "measure_count": 1,
            "origin_count": 1,
            "col_group_headers": [],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [{"title": long_title, "indent": 0, "values": [{"value": 1}]}],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        response.raise_for_status()
        zip_file = ZipFile(io.BytesIO(response.content))
        with zip_file.open("xl/sharedStrings.xml") as file:
            shared = file.read().decode()
        # The written title must not exceed Excel's 32767-char cell limit.
        self.assertNotIn("A" * 32_768, shared)
        self.assertIn("A" * 32_767, shared)

    def test_export_xlsx_with_empty_data(self):
        """An empty request body is rejected with 422, not a 500."""
        self.authenticate("admin", "admin")

        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps({}),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("No data to export", response.text)

    @patch(
        "odoo.addons.web.controllers.pivot.MAX_EXPORT_CELLS",
        5,
    )
    def test_export_xlsx_oversized_is_rejected(self):
        """A pivot exceeding the cell budget is rejected with 422, not OOM.

        The per-header width and measure_count are clamped, but the COUNT of
        headers/rows is client-controlled and unbounded; the total-cell cap is
        the backstop against a crafted body driving ~10^8 writes into RAM. Here
        the cap is patched low so the test stays fast; a body writing more than
        5 cells must 422.
        """
        self.authenticate("admin", "admin")
        jdata = {
            "title": "Huge",
            "model": "sale.report",
            "measure_count": 1,
            "origin_count": 1,
            # one header row, one header of width 50 => 50 cells >> 5 cap
            "col_group_headers": [
                [{"title": "x", "width": 50, "height": 1}],
            ],
            "measure_headers": [],
            "origin_headers": [],
            "rows": [],
        }
        response = self.url_open(
            "/web/pivot/export_xlsx",
            data={
                "data": json_dumps(jdata),
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("too large to export", response.text)
