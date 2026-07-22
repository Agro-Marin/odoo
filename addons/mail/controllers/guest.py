from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

from odoo.addons.mail.controllers.thread import _to_record_id
from odoo.addons.mail.tools.discuss import add_guest_to_context


class GuestController(http.Controller):
    @http.route(
        "/mail/guest/update_name", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def mail_guest_update_name(self, guest_id, name):
        # Coerce the client-supplied id like the ~20 sibling public routes:
        # browse("abc") yields tuple("abc") -> a 3-record set with string ids,
        # whose .exists() hits `id IN ('a','b','c')` -> InvalidTextRepresentation
        # (an anonymous 500), and browse([1, 2]) reaches _update_name's
        # ensure_one() as a ValueError. A 404 is the right answer.
        guest = request.env["mail.guest"]._get_guest_from_context()
        guest_to_rename_sudo = (
            guest.env["mail.guest"].browse(_to_record_id(guest_id)).sudo().exists()
        )
        if not guest_to_rename_sudo:
            raise NotFound
        if guest_to_rename_sudo != guest and not request.env.user._is_admin():
            raise NotFound
        guest_to_rename_sudo._update_name(name)
