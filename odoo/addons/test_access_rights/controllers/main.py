from odoo import http
from odoo.http import request


class SharedDocController(http.Controller):
    @http.route(
        "/test_access_rights/shared/<int:doc_id>",
        type="http",
        auth="link",
        link="test_access_right.shared_doc:doc_id",
        methods=["GET"],
    )
    def shared_doc(self, doc_id, **kwargs):
        return request.prepare_json_response(
            {"id": request.link_subject.id, "link": request.access_link.id or False}
        )

    @http.route(
        "/test_access_rights/shared_edit/<int:doc_id>",
        type="http",
        auth="link",
        link="test_access_right.shared_doc:doc_id",
        link_role="edit",
        methods=["GET"],
    )
    def shared_doc_edit(self, doc_id, **kwargs):
        return request.prepare_json_response({"id": request.link_subject.id})
