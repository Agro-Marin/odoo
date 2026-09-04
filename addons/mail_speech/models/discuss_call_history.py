from __future__ import annotations

import typing

from odoo import models

if typing.TYPE_CHECKING:
    from odoo.addons.base.models.ir_attachment import IrAttachment


class DiscussCallHistory(models.Model):
    _name = "discuss.call.history"
    _inherit = ["discuss.call.history", "mixin.media.timeline"]

    def _on_media_fully_transcribed(self) -> None:
        super()._on_media_fully_transcribed()
        for history in self:
            history.channel_id._bus_send(
                "discuss.call.history/transcribed",
                {"id": history.id, "transcript": history.media_transcript},
            )

    def _on_media_transcribed(self, attachment: IrAttachment) -> None:
        super()._on_media_transcribed(attachment)
        for history in self:
            history.channel_id._bus_send(
                "discuss.call.history/segment_transcribed",
                {"id": history.id, "attachment_id": attachment.id},
            )
