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
