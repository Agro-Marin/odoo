from odoo.http import request

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.portal.utils import get_portal_partner, resolve_message_thread


class PortalThreadController(ThreadController):
    """Portal overrides for chatter post/edit: identify the author from HMAC/token."""

    def _prepare_message_data(self, post_data, *, thread, from_create=True, **kwargs):
        """Attach the portal partner as message author when posting from a public session."""
        post_data = super()._prepare_message_data(
            post_data, thread=thread, from_create=from_create, **kwargs
        )
        if from_create and request.env.user._is_public():
            if partner := get_portal_partner(
                thread,
                kwargs.get("hash"),
                kwargs.get("pid"),
                kwargs.get("token"),
            ):
                post_data["author_id"] = partner.id
        return post_data

    @classmethod
    def _can_edit_message(cls, message, hash=None, pid=None, token=None, **kwargs):
        """Allow portal-validated authors to edit their own messages.

        Public callers can edit a message only when the HMAC/token resolves to a
        partner that matches ``message.author_id``. All other callers fall
        through to the parent (mail) controller's access logic.

        ``resolve_message_thread`` rather than ``request.env[message.model]``:
        the model name is free-form and this runs *before* the parent's access
        logic, so it is the first thing a stale or non-thread ``model`` reaches.
        ``mail``'s own ``_get_message_with_access`` already absorbs the stale
        case upstream of here, which is precisely why such a message arrives
        intact instead of 404ing earlier.
        """
        if message.env.user._is_public():
            thread = resolve_message_thread(message)
            partner = get_portal_partner(thread, _hash=hash, pid=pid, token=token)
            if partner and message.author_id == partner:
                return True
        return super()._can_edit_message(
            message,
            hash=hash,
            pid=pid,
            token=token,
            **kwargs,
        )
