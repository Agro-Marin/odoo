# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request


class ImportController(http.Controller):

    @http.route('/base_import/set_file', methods=['POST'])
    # pylint: disable=redefined-builtin
    def set_file(self, id):
        file = request.httprequest.files.getlist('ufile')[0]

        written = request.env['base_import.import'].browse(int(id)).write({
            'file': file.read(),
            'file_name': file.filename,
            'file_type': file.content_type,
        })

        # make_json_response, not a bare str: a str body from an http route
        # defaults to text/html, which the uploader (rejectHtml) reads as the
        # login page and turns into a spurious session-expired dialog.
        return request.make_json_response({'result': written})
