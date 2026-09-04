from __future__ import annotations

import typing

from odoo import fields, models

if typing.TYPE_CHECKING:
    from odoo.addons.base.models.ir_attachment import IrAttachment


class SpeechTestRecording(models.Model):
    _name = "speech.test.recording"
    _inherit = ["mixin.media.timeline"]
    _description = "Speech Test Recording"

    name = fields.Char(required=True, default="recording")
    transcribed_count = fields.Integer(default=0)
    failed_count = fields.Integer(default=0)
    completed = fields.Boolean(default=False)

    def _on_media_transcribed(self, attachment: IrAttachment) -> None:
        self.transcribed_count += 1

    def _on_media_transcription_failed(self, attachment: IrAttachment) -> None:
        self.failed_count += 1

    def _on_media_fully_transcribed(self) -> None:
        self.completed = True
