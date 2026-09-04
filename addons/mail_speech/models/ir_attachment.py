from __future__ import annotations

import typing

from odoo import models

from odoo.addons.mail.tools.discuss import Store

if typing.TYPE_CHECKING:
    from odoo.addons.mail.tools.discuss import StoreFieldsInput


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _to_store_defaults(self, target: Store.Target) -> StoreFieldsInput:
        return super()._to_store_defaults(target) + [
            "can_transcribe",
            "speech_state",
            "speech_transcript",
        ]

    def _speech_notify_owner(self, transcribed: bool) -> None:
        super()._speech_notify_owner(transcribed)
        # A voice message is not a media segment, so the timeline hooks never
        # reach it: its owner is the message it is attached to, and what has to
        # learn the words is whoever has that conversation open.
        for attachment in self:
            for message in attachment._speech_messages():
                Store(bus_channel=message._bus_channel()).add(
                    attachment,
                    ["speech_state", "speech_transcript"],
                ).bus_send()

    def _speech_messages(self) -> models.Model:
        self.check_singleton()
        return (
            self.env["mail.message"].sudo().search([("attachment_ids", "in", self.ids)])
        )
