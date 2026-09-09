from odoo import models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def execute_command_help(self, **kwargs):
        super().execute_command_help(**kwargs)
        self.env["mail.bot"]._apply_logic(self, kwargs, command="help")

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if self.channel_type == "chat":
            self.env["mail.bot"]._apply_logic(
                self,
                {
                    "author_id": message.author_id.id,
                    "message_type": message.message_type,
                    "body": message.body,
                    "partner_ids": message.partner_ids.ids,
                    "attachment_ids": message.attachment_ids.ids,
                },
            )
        return message
