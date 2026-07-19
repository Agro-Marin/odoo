import json

from werkzeug.exceptions import BadRequest, InternalServerError

from odoo import http
from odoo.http import request
from odoo.tools.misc import html_escape


class StockReportController(http.Controller):
    @http.route(
        [
            "/stock/<string:output_format>",
            # Legacy path: the trailing report-name segment was never consumed
            # server-side. The in-tree builders (stock_traceability_report_data.xml,
            # stock_traceability_report_backend.js) now use the canonical form,
            # but stored copies of the client action in existing databases
            # (Studio duplicates, saved contexts) may still carry it, so it
            # stays routable (and ignored).
            "/stock/<string:output_format>/<string:report_name>",
        ],
        type="http",
        auth="user",
    )
    def report(self, output_format, report_name=None, **kw):
        # Only PDF is produced; anything else used to fall through and return
        # ``None`` (an invalid WSGI response). Reject it explicitly.
        if output_format != "pdf":
            raise BadRequest(f"Unsupported output format: {output_format!r}")

        # Validate client input before the try block: client errors must
        # surface as 400s, not be swallowed by the generic handler below and
        # re-raised as a misleading 500 "Odoo Server Error".
        raw_data = kw.get("data")
        active_id = kw.get("active_id")
        active_model = kw.get("active_model")
        if not raw_data or not active_id or not active_model:
            raise BadRequest("Missing required parameters: data/active_id/active_model")
        try:
            active_id = int(active_id)
        except ValueError as e:
            raise BadRequest("'active_id' must be an integer") from e
        try:
            line_data = json.loads(raw_data)
        except ValueError as e:
            raise BadRequest("Invalid JSON payload in 'data'") from e

        uid = request.session.uid
        domain = [("create_uid", "=", uid)]
        stock_traceability = (
            request.env["stock.traceability.report"]
            .with_user(uid)
            .search(domain, limit=1)
        )
        try:
            return request.make_response(
                stock_traceability.with_context(
                    active_id=active_id, active_model=active_model
                ).get_pdf(line_data),
                headers=[
                    ("Content-Type", "application/pdf"),
                    (
                        "Content-Disposition",
                        "attachment; filename=" + "stock_traceability" + ".pdf;",
                    ),
                ],
            )
        except Exception as e:
            se = http.serialize_exception(e)
            error = {
                "code": 0,
                "message": "Odoo Server Error",
                "data": se,
            }
            res = request.make_response(html_escape(json.dumps(error)))
            raise InternalServerError(response=res) from e
