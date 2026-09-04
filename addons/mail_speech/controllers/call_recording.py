from __future__ import annotations

from odoo import http
from odoo.http import BadRequest, Forbidden, Response, UnsupportedMediaType, request

from odoo.addons.mail.controllers.utils import get_self_member_or_404
from odoo.addons.mail.tools.discuss import add_guest_to_context
from odoo.addons.speech.tools.engines import SPOKEN_MIMETYPES

MAX_SEGMENT_MS = 4 * 60 * 60 * 1000


class CallRecordingController(http.Controller):
    @http.route(
        "/discuss/call/upload_recording",
        methods=["POST"],
        type="http",
        auth="public",
        csrf=True,
    )
    @add_guest_to_context
    def upload_recording(
        self,
        channel_id: int,
        ufile: object,
        start_ms: str = "0",
        end_ms: str = "0",
        **_kwargs: object,
    ) -> Response:
        member = get_self_member_or_404(channel_id)
        if not member.sudo().rtc_session_ids:
            raise Forbidden
        if not ufile:
            raise BadRequest
        mimetype = (getattr(ufile, "content_type", "") or "").split(";")[0].strip()
        if mimetype not in SPOKEN_MIMETYPES:
            raise UnsupportedMediaType
        try:
            start, end = int(start_ms), int(end_ms)
        except (TypeError, ValueError) as error:
            raise BadRequest from error
        if not 0 <= start < end <= MAX_SEGMENT_MS:
            raise BadRequest

        channel_sudo = member.sudo().channel_id
        attachment_sudo = (
            request.env["ir.attachment"]
            .sudo()
            ._create_from_request_file(
                file=ufile,
                mimetype=mimetype,
                res_model="mail.call.recording",
            )
        )
        segment = channel_sudo._record_call_media(attachment_sudo, start, end)
        attachment_sudo.write({"res_model": "media.segment", "res_id": segment.id})
        if attachment_sudo.can_transcribe:
            attachment_sudo._transcribe_later()
        return request.make_json_response(
            {"segment_id": segment.id, "attachment_id": attachment_sudo.id}
        )
