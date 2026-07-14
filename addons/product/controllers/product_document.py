import json
import logging

from odoo import _
from odoo.http import Controller, request, route

logger = logging.getLogger(__name__)


class ProductDocumentController(Controller):
    @route("/product/document/upload", type="http", methods=["POST"], auth="user")
    def upload_document(self, ufile, res_model, res_id, **kwargs):
        if not self.is_model_valid(res_model):
            return self._error_response(
                _("Documents cannot be attached to this model.")
            )

        try:
            res_id = int(res_id)
        except ValueError, TypeError:
            return self._error_response(_("Invalid record id."))

        record = request.env[res_model].browse(res_id).exists()

        # `has_access` on the record itself: the model-level ACL alone is not
        # enough, the record rules (e.g. multi-company) must run against it too.
        if not record or not record.has_access("write"):
            return self._error_response(
                _("You are not allowed to attach documents to this record.")
            )

        files = request.httprequest.files.getlist("ufile")
        result = {"success": _("All files uploaded")}
        for file in files:
            try:
                request.env["product.document"].create(
                    {
                        "name": file.filename,
                        "res_model": record._name,
                        "res_id": record.id,
                        "company_id": record.company_id.id,
                        "mimetype": file.content_type,
                        "raw": file.read(),
                        **self.get_additional_create_params(**kwargs),
                    }
                )
            except Exception as e:
                logger.exception("Failed to upload document %s", file.filename)
                result = self._error_result(str(e))
        return json.dumps(result)

    @staticmethod
    def _error_result(message):
        # Shape recognized by the `file_upload` service (see handleResponse in
        # web/static/src/services/file_upload_service.js): the message is only
        # displayed when nested as a JSON-RPC-style error object.
        return {"error": {"message": message}}

    def _error_response(self, message):
        return json.dumps(self._error_result(message))

    # mrp hook
    def get_additional_create_params(self, **kwargs):
        return {}

    # eco hook
    def is_model_valid(self, res_model):
        return res_model in ("product.product", "product.template")
