# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command, api, fields, models


class Im_LivechatConversationTag(models.Model):
    """Tags for Live Chat conversations."""

    _name = "im_livechat.conversation.tag"
    _description = "Live Chat Conversation Tags"
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, whose index replaces the plain `(name)` one
    # this model declared -- that one compares whole jsonb documents once `name`
    # is translatable. Flat: conversation tags do not nest.
    _inherit = ["mixin.tag"]

    name = fields.Char("Name")
    conversation_ids = fields.Many2many(
        "discuss.channel",
        "livechat_conversation_tag_rel",
        string="Discuss Channels",
    )

    @api.ondelete(at_uninstall=False)
    def _unlink_sync_conversation(self):
        # For triggering the _sync_field_names before being unlinked
        # sudo: users who can delete tags can remove them from conversations in cascade
        self.sudo().conversation_ids.livechat_conversation_tag_ids = [
            Command.unlink(tag.id) for tag in self
        ]
