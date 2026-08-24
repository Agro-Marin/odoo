from odoo import models


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def execute_command_help(self, **kwargs):
        super().execute_command_help(**kwargs)
        self.env['mail.bot']._apply_logic(self, kwargs, command="help")

    def message_post(self, **kwargs):
        """Answer as odoobot once the user's own message has been notified.

        Deliberately not `_message_post_after_hook`: that hook runs *before*
        `_notify_thread` (`mixin.mail.thread.message_post`), so replying from it
        put odoobot's answer on the bus ahead of the message it answers, and any
        session without an optimistic copy of the user's message -- a second tab
        or device -- rendered the answer above the question. `im_livechat`'s
        chatbot has always replied from a separate round trip for the same
        reason; this is the in-process equivalent.

        The values come from the stored message rather than from `kwargs`: a
        normal post carries no `author_id`, and the recursion guard in
        `_apply_logic` needs one. Reading them is gated on `channel_type` --
        already loaded on any channel being posted to -- so a group channel or a
        livechat, where odoobot can never answer, pays nothing for the five
        field reads. `_get_answer` re-checks the type authoritatively.

        `_message_post_batch` is not covered and does not need to be: it posts
        with `message_type="notification"`, which `_apply_logic` ignores.
        """
        message = super().message_post(**kwargs)
        if self.channel_type == "chat":
            self.env['mail.bot']._apply_logic(self, {
                "author_id": message.author_id.id,
                "message_type": message.message_type,
                "body": message.body,
                "partner_ids": message.partner_ids.ids,
                "attachment_ids": message.attachment_ids.ids,
            })
        return message
