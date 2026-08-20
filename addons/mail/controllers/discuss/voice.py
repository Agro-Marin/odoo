from odoo import http
from odoo.http import Response

from odoo.addons.mail.controllers.utils import javascript_file_response


class VoiceController(http.Controller):
    @http.route(
        "/discuss/voice/worklet_processor",
        methods=["GET"],
        type="http",
        auth="public",
        readonly=True,
    )
    def voice_worklet_processor(self) -> Response:
        return javascript_file_response(
            "mail/static/src/discuss/voice_message/worklets/processor.js"
        )
