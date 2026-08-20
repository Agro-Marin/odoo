from odoo.http import request

from odoo.addons.mail.controllers.message_reaction import MessageReactionController
from odoo.addons.portal.utils import get_portal_partner, resolve_message_thread


class PortalMessageReactionController(MessageReactionController):
    """Add HMAC/token-based reaction authorship for portal-authenticated users."""

    def _get_reaction_author(self, message, **kwargs):
        """Resolve the reacting partner, falling back to portal credentials.

        When the parent (mail) controller cannot identify a partner — typically
        because the caller is anonymous — try the portal HMAC/token. If we
        recognise the portal partner, clear the guest so the reaction is
        attributed to the partner rather than an anonymous guest record.

        ``resolve_message_thread`` rather than ``request.env[message.model]``:
        the model name is free-form (a stale name after an uninstall, or a model
        that never inherited ``mixin.mail.thread``) and this route is ``auth="public"``.
        See :meth:`mail.message._is_thread_model`.
        """
        partner, guest = super()._get_reaction_author(message, **kwargs)
        if not partner:
            thread = resolve_message_thread(message)
            if partner := get_portal_partner(
                thread,
                kwargs.get("hash"),
                kwargs.get("pid"),
                kwargs.get("token"),
            ):
                # Portal-validated partner takes precedence: drop the guest binding.
                guest = request.env["mail.guest"]
        return partner, guest
