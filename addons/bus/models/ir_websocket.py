from typing import Any

from odoo import models
from odoo.http import SessionExpiredException, request
from odoo.service import security
from odoo.tools.misc import OrderedSet

from ..models.bus import dispatch
from ..websocket import wsrequest


class IrWebsocket(models.AbstractModel):
    _name = "ir.websocket"
    _description = "websocket message handling"

    def _build_bus_channel_list(self, channels: list) -> list:
        """Return the list of channels to subscribe to.

        Override to add server-side channels in addition to those the
        client sent (e.g. user groups, partner channel).

        The input ``channels`` list must not be mutated — build a new
        list instead.
        """
        req = request or wsrequest
        channels = [*channels, "broadcast", *self.env.user.all_group_ids]
        if req.session.uid:
            channels.append(self.env.user.partner_id)
        return channels

    def _serve_ir_websocket(self, event_name: str, data: Any) -> None:
        """Process websocket events.

        Modules can override this method to handle their own events.  Overriding is
        not recommended — prefer HTTP routes (Odoo.sh does not use this path).
        """

    def _prepare_subscribe_data(self, channels: list[str], last: int) -> dict:
        """Parse client subscription data, validate, and resolve channels.

        Clamps ``last`` to ``[0, max_id]``: negative values would match all
        rows; values beyond ``max_id`` skip all existing notifications
        (reset to 0 instead).

        :raise ValueError: If ``channels`` contains non-string elements.
        """
        if not all(isinstance(c, str) for c in channels):
            raise ValueError("bus.Bus only string channels are allowed.")
        # sudo - bus.bus: reading non-sensitive last bus id.
        last = max(0, last)
        last = 0 if last > self.env["bus.bus"].sudo()._bus_last_id() else last
        return {
            "channels": OrderedSet(self._build_bus_channel_list(list(channels))),
            "last": last,
        }

    def _after_subscribe_data(self, data: dict) -> None:
        """Hook invoked after subscribe data have been processed.

        Modules can override to add custom behavior.
        """

    def _subscribe(self, og_data: dict) -> None:
        """Subscribe the current websocket to the channels specified in ``og_data``."""
        data = self._prepare_subscribe_data(og_data["channels"], og_data["last"])
        dispatch.subscribe(
            data["channels"], data["last"], self.env.registry.db_name, wsrequest.ws
        )
        self._after_subscribe_data(data)

    def _on_websocket_closed(self, cookies: Any) -> None:
        """Hook invoked upon WebSocket termination.

        Modules can override to add custom cleanup behavior.
        """

    @classmethod
    def _authenticate(cls) -> None:
        """Authenticate the current websocket session.

        Validates the session for logged-in users; assigns the public
        user for anonymous sessions.
        """
        if wsrequest.session.uid is not None:
            if not security.check_session(wsrequest.session, wsrequest.env, wsrequest):
                wsrequest.session.logout(keep_db=True)
                raise SessionExpiredException
        else:
            public_user = wsrequest.env.ref("base.public_user")
            wsrequest.update_env(user=public_user.id)
