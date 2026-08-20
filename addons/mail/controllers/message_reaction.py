import typing

from werkzeug.exceptions import NotFound

from odoo import http, models
from odoo.http import request

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

if typing.TYPE_CHECKING:
    from odoo.addons.mail.models.mail_message import MailMessage


class MessageReactionController(ThreadController):
    @http.route(
        "/mail/message/reaction", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def mail_message_reaction(
        self, message_id: int, content: str, action: str, **kwargs
    ) -> dict:
        if action not in ("add", "remove"):
            raise NotFound
        message = self._get_message_with_access(message_id, mode="create", **kwargs)
        if not message:
            raise NotFound
        partner, guest = self._get_reaction_author(message, **kwargs)
        if not partner and not guest:
            raise NotFound
        store = Store()
        message.sudo()._message_reaction(content, action, partner, guest, store)
        return store.get_result()

    def _get_reaction_author(
        self, message: MailMessage, **kwargs
    ) -> tuple[models.Model, models.Model]:
        return request.env["res.partner"]._get_current_persona()
