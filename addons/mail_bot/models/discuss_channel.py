# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def execute_command_help(self, **kwargs):
        super().execute_command_help(**kwargs)
        # kwargs carry the typed body, which the bot logic matches on
        self.env['mail.bot']._apply_logic(self, kwargs, command="help")

    def _message_post_after_hook(self, message, msg_vals):
        self.env["mail.bot"]._apply_logic(self, msg_vals)
        return super()._message_post_after_hook(message, msg_vals)
