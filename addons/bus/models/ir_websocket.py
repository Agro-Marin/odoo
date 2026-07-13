from odoo import models
from odoo.http import SessionExpiredException, request
from odoo.service import security
from odoo.tools.misc import OrderedSet

from ..models.bus import dispatch
from ..websocket import wsrequest


class IrWebsocket(models.AbstractModel):
    _name = "ir.websocket"
    _description = "websocket message handling"

    def _build_bus_channel_list(self, channels):
        """
        Return the list of channels to subscribe to. Override this
        method to add channels in addition to the ones the client
        sent.

        :param channels: The channel list sent by the client.
        """
        req = request or wsrequest
        channels = [*channels, "broadcast", *self.env.user.all_group_ids]
        if req.session.uid:
            channels = [*channels, self.env.user.partner_id]
        return channels

    def _serve_ir_websocket(self, event_name, data):
        """Process websocket events.
        Modules can override this method to handle their own events. But overriding this method is
        not recommended and should be carefully considered, because at the time of writing this
        message, Odoo.sh does not use this method. Each new event should have a corresponding http
        route and Odoo.sh infrastructure should be updated to reflect it. On top of that, the
        event processing is very time, ressource and error sensitive."""

    def _prepare_subscribe_data(self, channels, last):
        """
        Parse the data sent by the client and return the list of channels
        and the last known notification id. This will be used both by the
        websocket controller and the websocket request class when the
        `subscribe` event is received.

        :param typing.List[str] channels: List of channels to subscribe to sent
            by the client.
        :param int last: Last known notification sent by the client.

        :return:
            A dict containing the following keys:
            - channels (set of str): The list of channels to subscribe to.
            - last (int): The last known notification id.

        :raise ValueError: If the arguments do not have the expected
            types/shape. Both the websocket `subscribe` event and the
            `/websocket/peek_notifications` route feed this method raw
            client-controlled data, so validation must not assume anything.
        """
        if not isinstance(channels, (list, tuple)) or not all(
            isinstance(c, str) for c in channels
        ):
            raise ValueError("bus.Bus only string channels are allowed.")
        if not isinstance(last, int) or isinstance(last, bool):
            raise ValueError("bus.Bus subscription 'last' must be an integer.")
        # sudo - bus.bus: reading non-sensitive last bus id.
        # Clamp to [0, max_id]: negative values would match all rows, values
        # beyond max_id skip all existing notifications (reset to 0 instead).
        last = max(0, last)
        last = 0 if last > self.env["bus.bus"].sudo()._bus_last_id() else last
        return {
            "channels": OrderedSet(self._build_bus_channel_list(list(channels))),
            "last": last,
        }

    def _after_subscribe_data(self, data):
        """Function invoked after subscribe data have been processed.
        Modules can override this method to add custom behavior."""

    def _subscribe(self, og_data):
        if not isinstance(og_data, dict) or "channels" not in og_data:
            raise ValueError(
                "bus.Bus subscribe data must be a dict with a 'channels' key."
            )
        data = self._prepare_subscribe_data(og_data["channels"], og_data.get("last", 0))
        dispatch.subscribe(
            data["channels"], data["last"], self.env.registry.db_name, wsrequest.ws
        )
        self._after_subscribe_data(data)

    def _on_websocket_closed(self, cookies):
        """Function invoked upon WebSocket termination.
        Modules can override this method to add custom behavior."""

    @classmethod
    def _authenticate(cls):
        if wsrequest.session.uid is not None:
            if not security.check_session(wsrequest.session, wsrequest.env, wsrequest):
                wsrequest.session.logout(keep_db=True)
                raise SessionExpiredException
        else:
            public_user = wsrequest.env.ref("base.public_user")
            wsrequest.update_env(user=public_user.id)
