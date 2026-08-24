from werkzeug.exceptions import BadRequest

from odoo import models
from odoo.http import request
from odoo.tools.translate import _


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _auth_method_calendar(cls):
        # An empty token is not a token. `('access_token', '=', '')` matches
        # every row whose column is NULL, so without this guard a request with
        # no token at all authenticates as any attendee created outside the
        # field's default -- and the caller then reads the invitation page and
        # answers the invitation. Reject falsy tokens before they reach a
        # domain; `CalendarController._attendee_from_token` /
        # `_event_from_token` apply the same rule to the routes, which look
        # records up by token again after this method has run.
        token = request.httprequest.args.get('token', '')
        if not token:
            raise BadRequest(_("Invalid Invitation Token."))

        attendee = request.env['calendar.attendee'].sudo().search(
            [('access_token', '=', token)], limit=1)
        if not attendee:
            raise BadRequest(_("Invalid Invitation Token."))

        if request.session.uid and request.session.login != 'anonymous':
            # A valid token, but presented from somebody else's session: the
            # invitation was forwarded. Say so without echoing either address
            # back into the response -- the page is reachable by anyone holding
            # the token, and the message used to name both mailboxes.
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if attendee.partner_id != user.partner_id:
                raise BadRequest(_(
                    "This invitation belongs to somebody else and cannot be "
                    "forwarded. Please ask the organizer to add you."
                ))

        cls._auth_method_public()
