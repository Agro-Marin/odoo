from odoo import Command

from odoo.addons.mail.tests.common import MailCommon


class MailBotCommon(MailCommon):
    """A user with a real OdooBot chat, and helpers to talk to it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.odoobot = cls.env.ref("base.partner_root")
        cls.bot_user = cls.env["res.users"].create({
            "name": "Bot Tester",
            "login": "mail_bot_tester",
            "group_ids": [Command.link(cls.env.ref("base.group_user").id)],
        })
        cls.bot_channel = cls.bot_user.with_user(cls.bot_user)._init_odoobot()

    def _set_state(self, state, failed=False):
        self.bot_user.sudo().write({"odoobot_state": state, "odoobot_failed": failed})

    def _say(self, body="", *, user=None, channel=None, context=None, **kwargs):
        """Post as the user and return odoobot's answers, in id order."""
        user = user or self.bot_user
        channel = channel if channel is not None else self.bot_channel
        if context:
            channel = channel.with_context(**context)
        last_id = self.env["mail.message"].search(
            [("model", "=", "discuss.channel"), ("res_id", "=", channel.id)],
            order="id desc", limit=1,
        ).id or 0
        post_kwargs = {
            "body": body,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_comment",
            **kwargs,
        }
        channel.with_user(user).message_post(**post_kwargs)
        answers = self.env["mail.message"].search([
            ("model", "=", "discuss.channel"),
            ("res_id", "=", channel.id),
            ("id", ">", last_id),
            ("author_id", "=", self.odoobot.id),
        ], order="id")
        return [str(answer.body) for answer in answers]

    def _say_one(self, body="", **kwargs):
        answers = self._say(body, **kwargs)
        self.assertTrue(answers, f"odoobot said nothing to {body!r}")
        return answers[0]
