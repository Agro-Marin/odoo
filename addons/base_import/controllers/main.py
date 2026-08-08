# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.exceptions import MissingError, UserError
from odoo.http import request


class ImportController(http.Controller):

    @http.route('/base_import/set_file', methods=['POST'], type='http', auth='user')
    # pylint: disable=redefined-builtin
    def set_file(self, id=None, ufile=None):
        # `id` and the upload both come straight from the request body, so
        # neither can be trusted to be present or well-formed: `int(id)` on a
        # missing/garbage value and indexing an empty file list both used to
        # raise, surfacing as an HTTP 500 instead of a 4xx.
        try:
            import_id = int(id)
        except (TypeError, ValueError) as exc:
            raise UserError(request.env._("Invalid import identifier.")) from exc

        files = request.httprequest.files.getlist('ufile')
        if not files:
            raise UserError(request.env._("No file was uploaded."))
        file = files[0]

        # `exists()` after the browse so that a record belonging to someone else
        # is indistinguishable from one that never existed: the record rule on
        # base_import.import restricts access to the creator, and this route is
        # the only way a raw id reaches the model from the outside.
        record = request.env['base_import.import'].browse(import_id).exists()
        if not record:
            raise MissingError(request.env._("This import does not exist or is no longer available."))

        written = record.write({
            'file': file.read(),
            'file_name': file.filename,
            'file_type': file.content_type,
        })

        # make_json_response, not a bare str: a str body from an http route
        # defaults to text/html, which the uploader (rejectHtml) reads as the
        # login page and turns into a spurious session-expired dialog.
        return request.make_json_response({'result': written})
