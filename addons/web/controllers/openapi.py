import werkzeug.exceptions

import odoo.release
from odoo import http
from odoo.http import request
from odoo.http.openapi import openapi_from_map


class OpenAPI(http.Controller):
    @http.route(
        "/web/openapi.json", type="http", auth="user", methods=["GET"], readonly=True
    )
    def openapi_json(self):
        if not request.env.user.has_group("base.group_system"):
            raise werkzeug.exceptions.Forbidden(
                "Only system administrators may read the API document."
            )
        document = openapi_from_map(
            request.env["ir.http"].routing_map(),
            title="Odoo HTTP API",
            version=odoo.release.major_version,
            servers=[{"url": request.httprequest.url_root.rstrip("/")}],
            typed_only=True,
        )
        return request.make_json_response(document)
