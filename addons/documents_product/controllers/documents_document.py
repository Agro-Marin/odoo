import json
import logging

from odoo import _
from odoo.http import Controller, request, route

logger = logging.getLogger(__name__)


class ProductDocumentsController(Controller):
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

        if not record or not record.has_access("write"):
            return self._error_response(
                _("You are not allowed to attach documents to this record.")
            )

        files = request.httprequest.files.getlist("ufile")
        failed = []
        for file in files:
            try:
                with request.env.cr.savepoint():
                    request.env["documents.document"].create(
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
            except Exception:
                logger.exception("Failed to upload document %s", file.filename)
                failed.append(file.filename or _("unnamed file"))

        if failed:
            if len(failed) == len(files):
                message = _("No file could be uploaded.")
            else:
                message = _("Some files could not be uploaded: %s", ", ".join(failed))
            return json.dumps(self._error_result(message))
        return json.dumps({"success": _("All files uploaded")})

    @staticmethod
    def _error_result(message):
        return {"error": {"message": message}}

    def _error_response(self, message):
        return json.dumps(self._error_result(message))

    def get_additional_create_params(self, **kwargs):
        return {}

    def is_model_valid(self, res_model):
        return res_model in ("product.product", "product.template")
