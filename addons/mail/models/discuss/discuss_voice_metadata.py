import typing

from odoo import fields, models

if typing.TYPE_CHECKING:
    from odoo.addons.bus.models.ir_attachment import IrAttachment


class DiscussVoiceMetadata(models.Model):
    _name = "discuss.voice.metadata"
    _description = "Metadata for voice attachments"

    attachment_id: IrAttachment = fields.Many2one(
        "ir.attachment",
        ondelete="cascade",
        bypass_search_access=True,
        copy=False,
        index=True,
    )
