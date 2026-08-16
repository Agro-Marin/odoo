from odoo.http import SessionExpiredException, request, route

from odoo.addons.bus.controllers.websocket import WebsocketController
from odoo.addons.mail.tools.discuss import add_guest_to_context


class WebsocketControllerPresence(WebsocketController):
    @route()
    @add_guest_to_context
    def peek_notifications(
        self, channels: list, last: int, is_first_poll: bool = False
    ) -> list:
        return super().peek_notifications(channels, last, is_first_poll)

    @route("/websocket/update_bus_presence", type="jsonrpc", auth="public", cors="*")
    def update_bus_presence(self, inactivity_period: int) -> dict:
        if "is_websocket_session" not in request.session:
            raise SessionExpiredException
        try:
            inactivity_period = int(inactivity_period)
        except TypeError, ValueError:
            inactivity_period = 0
        request.env["ir.websocket"]._update_mail_presence(inactivity_period)
        return {}
