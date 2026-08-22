from odoo.http import request

from odoo.addons.mail.controllers.message_reaction import MessageReactionController
from odoo.addons.portal.utils import get_portal_partner, resolve_message_thread


class PortalMessageReactionController(MessageReactionController):

    def _get_reaction_author(self, message, **kwargs):
        partner, guest = super()._get_reaction_author(message, **kwargs)
        if not partner:
            thread = resolve_message_thread(message)
            if partner := get_portal_partner(
                thread,
                kwargs.get("hash"),
                kwargs.get("pid"),
                kwargs.get("token"),
            ):
                guest = request.env["mail.guest"]
        return partner, guest
