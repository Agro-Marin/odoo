import io
from collections import deque

import xlsxwriter
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import UnprocessableEntity

from odoo import _, http
from odoo.http import Response, content_disposition, request
from odoo.libs.filesystem import osutil
from odoo.libs.json import loads as json_loads

# Hard ceiling on the number of cells a single pivot export may emit. The
# per-header ``width`` and ``measure_count`` are individually clamped below, but
# the COUNT of headers/rows is client-controlled and unbounded, and the workbook
# is built ``in_memory`` (``constant_memory`` cannot help while ``in_memory`` is
# set, and is incompatible with the ``autofit`` below — measured: it gives no RAM
# reduction). A crafted body with many wide headers could otherwise drive ~10^8
# ``write`` calls into RAM → worker OOM. Capping the emitted cells bounds the work
# without altering the output of any legitimately-sized export (a 10k-row ×
# 30-measure pivot is ~300k cells). ~1M cells ≈ 230 MB peak — generous but finite.
MAX_EXPORT_CELLS = 1_000_000


class TableExporter(http.Controller):
    @http.route("/web/pivot/export_xlsx", type="http", auth="user", readonly=True)
    def export_xlsx(self, data: str | FileStorage, **kw) -> Response:
        jdata = json_loads(data.read() if isinstance(data, FileStorage) else data)
        if not jdata:
            raise UnprocessableEntity(_("No data to export"))
        output = io.BytesIO()
        # strings_to_formulas=False: pivot labels/values are client-supplied;
        # never let a leading "=" be interpreted as a formula (injection).
        with xlsxwriter.Workbook(
            output, {"in_memory": True, "strings_to_formulas": False}
        ) as workbook:
            worksheet = workbook.add_worksheet(jdata["title"])

            # Bound the total number of cells written, regardless of the header /
            # row COUNT the client declares (only per-header width is clamped
            # below). Shadowing the instance ``write`` intercepts every call site.
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

            measure_count = max(0, min(jdata["measure_count"], 100000))

            # Step 1: writing col group headers
            col_group_headers = jdata["col_group_headers"]

            # x,y: current coordinates
            # carry: queue containing cell information when a cell has a >= 2 height
            #      and the drawing code needs to add empty cells below
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
                        x = x + measure_count
                    width = max(0, min(header["width"], 100000))
                    for j in range(width):
                        worksheet.write(
                            y,
                            x + j,
                            header["title"] if j == 0 else "",
                            header_plain,
                        )
                    if header["height"] > 1:
                        carry.append({"x": x, "height": header["height"] - 1})
                    x = x + width
                while carry and carry[0]["x"] == x:
                    cell = carry.popleft()
                    for j in range(measure_count):
                        worksheet.write(y, x + j, "", header_plain)
                    if cell["height"] > 1:
                        carry.append({"x": x, "height": cell["height"] - 1})
                    x = x + measure_count
                x, y = 1, y + 1

            # Step 2: writing measure headers
            measure_headers = jdata["measure_headers"]

            if measure_headers:
                worksheet.write(y, 0, "", header_plain)
                for measure in measure_headers:
                    style = header_bold if measure["is_bold"] else header_plain
                    worksheet.write(y, x, measure["title"], style)
                    x = x + 1
                x, y = 1, y + 1
            worksheet.freeze_panes(y, 1)

            # Step 3: writing data
            x = 0
            for row in jdata["rows"]:
                worksheet.write(
                    y,
                    x,
                    f"{row['indent'] * '     '}{row['title']}",
                    header_plain,
                )
                for cell in row["values"]:
                    x = x + 1
                    if cell.get("is_bold", False):
                        worksheet.write(y, x, cell["value"], bold)
                    else:
                        worksheet.write(y, x, cell["value"])
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
