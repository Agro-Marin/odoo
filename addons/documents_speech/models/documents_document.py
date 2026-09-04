from __future__ import annotations

from odoo import api, fields, models


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    speech_state = fields.Selection(
        related="attachment_id.speech_state", string="Transcription"
    )
    speech_transcript = fields.Text(
        related="attachment_id.speech_transcript", string="Transcript"
    )
    can_transcribe = fields.Boolean(related="attachment_id.can_transcribe")

    def action_transcribe(self) -> bool:
        return self.attachment_id.action_transcribe()

    def _speech_vtt(self) -> str:
        self.check_singleton()
        return self.attachment_id._speech_vtt()

    @api.model
    def action_read_aloud(self, text: str, folder_id: int | None = None) -> int:
        attachment = self.env["ir.attachment"]._speech_synthesize(text)
        document = self.create(
            {
                "attachment_id": attachment.id,
                "folder_id": folder_id,
            }
        )
        return document.id
