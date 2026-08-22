import io
from collections import deque

import xlsxwriter
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import UnprocessableEntity

from odoo import _, http
from odoo.http import Response, content_disposition, request
from odoo.libs.filesystem import osutil
from odoo.libs.json import loads as json_loads

MAX_EXPORT_CELLS = 1_000_000

MAX_CELL_CHARS = 32_767


def _cell(value):
    return value[:MAX_CELL_CHARS] if isinstance(value, str) else value


def _clamp_int(value, hi):
    try:
        return max(0, min(int(value), hi))
    except TypeError, ValueError:
        return 0


class TableExporter(http.Controller):
    @http.route("/web/pivot/export_xlsx", type="http", auth="user", readonly=True)
    def export_xlsx(self, data: str | FileStorage, **kw) -> Response:
        jdata = json_loads(data.read() if isinstance(data, FileStorage) else data)
        if not jdata:
            raise UnprocessableEntity(_("No data to export"))
        output = io.BytesIO()
        with xlsxwriter.Workbook(
            output, {"in_memory": True, "strings_to_formulas": False}
        ) as workbook:
            worksheet = workbook.add_worksheet(jdata["title"])

            cells_written = 0
            _raw_write = worksheet.write

            def _write(*args, **kwargs):
                nonlocal cells_written
                cells_written += 1
                if cells_written > MAX_EXPORT_CELLS:
                    raise UnprocessableEntity(
                        _(
                            "This pivot is too large to export (over %s cells). "
                            "Narrow the grouping or add filters and try again.",
                            MAX_EXPORT_CELLS,
                        )
                    )
                return _raw_write(*args, **kwargs)

            worksheet.write = _write

            header_bold = workbook.add_format(
                {"bold": True, "pattern": 1, "bg_color": "#AAAAAA"}
            )
            header_plain = workbook.add_format({"pattern": 1, "bg_color": "#AAAAAA"})
            bold = workbook.add_format({"bold": True})

            measure_count = _clamp_int(jdata["measure_count"], 100000)

            col_group_headers = jdata["col_group_headers"]

            x, y, carry = 1, 0, deque()
            for i, header_row in enumerate(col_group_headers):
                worksheet.write(i, 0, "", header_plain)
                for header in header_row:
                    while carry and carry[0]["x"] == x:
                        cell = carry.popleft()
                        for j in range(measure_count):
                            worksheet.write(y, x + j, "", header_plain)
                        if cell["height"] > 1:
                            carry.append({"x": x, "height": cell["height"] - 1})
                        x += measure_count
                    width = _clamp_int(header["width"], 100000)
                    height = _clamp_int(header["height"], 100000)
                    for j in range(width):
                        worksheet.write(
                            y,
                            x + j,
                            _cell(header["title"]) if j == 0 else "",
                            header_plain,
                        )
                    if height > 1:
                        carry.append({"x": x, "height": height - 1})
                    x += width
                while carry and carry[0]["x"] == x:
                    cell = carry.popleft()
                    for j in range(measure_count):
                        worksheet.write(y, x + j, "", header_plain)
                    if cell["height"] > 1:
                        carry.append({"x": x, "height": cell["height"] - 1})
                    x += measure_count
                x, y = 1, y + 1

            measure_headers = jdata["measure_headers"]

            if measure_headers:
                worksheet.write(y, 0, "", header_plain)
                for measure in measure_headers:
                    style = header_bold if measure["is_bold"] else header_plain
                    worksheet.write(y, x, _cell(measure["title"]), style)
                    x += 1
                x, y = 1, y + 1
            worksheet.freeze_panes(y, 1)

            x = 0
            for row in jdata["rows"]:
                indent = _clamp_int(row.get("indent", 0), 50)
                worksheet.write(
                    y,
                    x,
                    f"{indent * '     '}{_cell(row['title'])}",
                    header_plain,
                )
                for cell in row["values"]:
                    x += 1
                    if cell.get("is_bold", False):
                        worksheet.write(y, x, _cell(cell["value"]), bold)
                    else:
                        worksheet.write(y, x, _cell(cell["value"]))
                x, y = 0, y + 1

            worksheet.autofit()

        xlsx_data = output.getvalue()
        filename = osutil.clean_filename(
            _(
                "Pivot %(title)s (%(model_name)s)",
                title=jdata["title"],
                model_name=jdata["model"],
            )
        )
        return request.make_response(
            xlsx_data,
            headers=[
                (
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
                (
                    "Content-Disposition",
                    content_disposition(filename + ".xlsx"),
                ),
            ],
        )
