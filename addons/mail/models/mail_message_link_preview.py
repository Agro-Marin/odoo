from odoo import fields, models

from odoo.addons.mail.tools.discuss import Store


class MessageMailLinkPreview(models.Model):
    _name = "mail.message.link.preview"
    _inherit = ["bus.listener.mixin"]
    _description = "Link between link previews and messages"
    _order = "sequence, id"

    message_id = fields.Many2one(
        "mail.message", required=True, index=True, ondelete="cascade"
    )
    link_preview_id = fields.Many2one(
        "mail.link.preview", index=True, required=True, ondelete="cascade"
    )
    sequence = fields.Integer("Sequence")
    is_hidden = fields.Boolean()
    author_id = fields.Many2one(related="message_id.author_id")

    _unique_message_link_preview = models.UniqueIndex("(message_id, link_preview_id)")

    def _bus_channel(self):
        return self.message_id._bus_channel()

    def _hide_and_notify(self):
        if not self:
            return
        self.is_hidden = True
        for message_link_preview in self:
            # per-record channel: self._bus_channel() delegates to
            # message_id._bus_channel() which ensure_one()s, so computing it on
            # the whole recordset crashes as soon as `self` spans two messages
            # (and needlessly recomputed the same channel N times otherwise).
            Store(bus_channel=message_link_preview._bus_channel()).delete(
                message_link_preview
            ).bus_send()

    def _unlink_and_notify(self):
        if not self:
            return
        for message_link_preview in self:
            # per-record channel, see _hide_and_notify.
            Store(bus_channel=message_link_preview._bus_channel()).delete(
                message_link_preview
            ).bus_send()
        self.unlink()

    def _to_store_defaults(self, target):
        return [
            Store.One("link_preview_id", sudo=True),
            Store.One("message_id", [], sudo=True),
        ]
