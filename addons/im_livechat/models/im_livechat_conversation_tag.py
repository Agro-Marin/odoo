from odoo import Command, api, fields, models


class Im_LivechatConversationTag(models.Model):
    _name = "im_livechat.conversation.tag"
    _description = "Live Chat Conversation Tags"
    _inherit = ["mixin.tag"]

    name = fields.Char("Name")
    conversation_ids = fields.Many2many(
        "discuss.channel",
        "livechat_conversation_tag_rel",
        string="Discuss Channels",
    )

    @api.ondelete(at_uninstall=False)
    def _unlink_sync_conversation(self):
        self.sudo().conversation_ids.livechat_conversation_tag_ids = [
            Command.unlink(tag.id) for tag in self
        ]
