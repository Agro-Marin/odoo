import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

import werkzeug.exceptions

from odoo import http
from odoo.http import Response, content_disposition, request
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.tools.misc import html_escape
from odoo.tools.safe_eval import safe_eval, time

_logger = logging.getLogger(__name__)

_MAX_BARCODE_DIM = 10_000

_MAX_BARCODE_VALUE_LEN = 4096


def _clamp_barcode_dimension(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except ValueError, TypeError:
        return default
    if value < 1:
        return default
    return min(value, _MAX_BARCODE_DIM)


class ReportController(http.Controller):
    @http.route(
        [
            "/report/<converter>/<reportname>",
            "/report/<converter>/<reportname>/<docids>",
        ],
        type="http",
        auth="user",
        website=True,
        readonly=True,
    )
    def report_routes(
        self,
        reportname: str,
        docids: str | None = None,
        converter: str | None = None,
        **data,
    ) -> Response:
        report = request.env["ir.actions.report"]
        context = dict(request.env.context)

        if docids:
            docids = [int(i) for i in docids.split(",") if i.isdigit()]
        if data.get("options"):
            data.update(json_loads(data.pop("options")))
        if data.get("context"):
            data["context"] = json_loads(data["context"])
            context.update(data["context"])
        if converter == "html":
            html = report.with_context(context)._render_qweb_html(
                reportname, docids, data=data
            )[0]
            return request.make_response(html)
        elif converter == "pdf":
            pdf = report.with_context(context)._render_qweb_pdf(
                reportname, docids, data=data
            )[0]
            pdfhttpheaders = [
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(pdf)),
            ]
            return request.make_response(pdf, headers=pdfhttpheaders)
        elif converter == "text":
            text = report.with_context(context)._render_qweb_text(
                reportname, docids, data=data
            )[0]
            texthttpheaders = [
                ("Content-Type", "text/plain"),
                ("Content-Length", len(text)),
            ]
            return request.make_response(text, headers=texthttpheaders)
        else:
            raise werkzeug.exceptions.BadRequest(
                description=f"Converter {converter!r} not supported."
            )

    @http.route(
        [
            "/report/barcode",
            "/report/barcode/<barcode_type>/<path:value>",
        ],
        type="http",
        auth="public",
        readonly=True,
    )
    def report_barcode(self, barcode_type: str, value: str, **kwargs) -> Response:
        if value is not None and len(value) > _MAX_BARCODE_VALUE_LEN:
            raise werkzeug.exceptions.BadRequest("Barcode value is too long.")
        if "width" in kwargs:
            kwargs["width"] = _clamp_barcode_dimension(kwargs["width"], 600)
        if "height" in kwargs:
            kwargs["height"] = _clamp_barcode_dimension(kwargs["height"], 100)
        try:
            barcode = request.env["ir.actions.report"].prepare_barcode(
                barcode_type, value, **kwargs
            )
        except ValueError, AttributeError, KeyError:
            raise werkzeug.exceptions.BadRequest(
                "Cannot convert into barcode."
            ) from None

        return request.make_response(
            barcode,
            headers=[
                ("Content-Type", "image/png"),
                (
                    "Cache-Control",
                    f"public, max-age={http.STATIC_CACHE_LONG}, immutable",
                ),
            ],
        )

    @http.route(["/report/download"], type="http", auth="user")
    def report_download(
        self, data: str, context: str | None = None, **_kwargs
    ) -> Response:
        requestcontent = json_loads(data)
        url, type_ = requestcontent[0], requestcontent[1]
        reportname = "???"
        try:
            if type_ in ["qweb-pdf", "qweb-text"]:
                converter = "pdf" if type_ == "qweb-pdf" else "text"
                extension = "pdf" if type_ == "qweb-pdf" else "txt"

                pattern = "/report/pdf/" if type_ == "qweb-pdf" else "/report/text/"
                _, _, after_pattern = url.partition(pattern)
                if not after_pattern:
                    raise werkzeug.exceptions.BadRequest(
                        description=f"URL does not match expected pattern {pattern!r}."
                    )
                reportname = after_pattern.split("?")[0]

                docids = None
                if "/" in reportname:
                    reportname, docids = reportname.split("/", 1)

                if docids:
                    response = self.report_routes(
                        reportname,
                        docids=docids,
                        converter=converter,
                        context=context,
                    )
                else:
                    data = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
                    if "context" in data:
                        context, data_context = (
                            json_loads(context or "{}"),
                            json_loads(data.pop("context")),
                        )
                        context = json_dumps({**context, **data_context})
                    response = self.report_routes(
                        reportname, converter=converter, context=context, **data
                    )

                report = request.env["ir.actions.report"]._get_report_from_name(
                    reportname
                )
                filename = f"{report.name}.{extension}"

                if docids:
                    ids = [int(x) for x in docids.split(",") if x.isdigit()]
                    obj = request.env[report.model].browse(ids)
                    if report.print_report_name and len(obj) == 1:
                        report_name = safe_eval(
                            report.print_report_name,
                            {"object": obj, "time": time},
                        )
                        filename = f"{report_name}.{extension}"
                response.headers.add(
                    "Content-Disposition", content_disposition(filename)
                )
                return response
            else:
                raise werkzeug.exceptions.BadRequest(
                    description=f"Report type {type_!r} not supported."
                )
        except Exception as e:
            _logger.warning(
                "Error while generating report %s", reportname, exc_info=True
            )
            se = http.serialize_exception(e)
            error = {"code": 0, "message": "Odoo Server Error", "data": se}
            res = request.make_response(html_escape(json_dumps(error)))
            raise werkzeug.exceptions.InternalServerError(response=res) from e
