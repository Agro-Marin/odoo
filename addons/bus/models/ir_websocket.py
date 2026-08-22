from odoo import models
from odoo.http import SessionExpiredException
from odoo.service import security
from odoo.tools.misc import OrderedSet

from ..models.bus import dispatch
from ..websocket import wsrequest

MAX_SUBSCRIBED_CHANNELS = 4096
MAX_CHANNEL_LENGTH = 512


class IrWebsocket(models.AbstractModel):
    _name = "ir.websocket"
    _description = "websocket message handling"

    def _build_bus_channel_list(self, channels):
        channels = [*channels, "broadcast", *self.env.user.all_group_ids]
        if not self.env.user._is_public():
            channels = [*channels, self.env.user.partner_id]
        return channels

    def _serve_ir_websocket(self, event_name, data):
        pass

    def _prepare_subscribe_data(self, channels, last):
        if not isinstance(channels, (list, tuple)) or not all(
            isinstance(c, str) for c in channels
        ):
            raise ValueError("bus.Bus only string channels are allowed.")
        if len(channels) > MAX_SUBSCRIBED_CHANNELS:
            raise ValueError(
                f"bus.Bus subscription is limited to {MAX_SUBSCRIBED_CHANNELS} "
                f"channels, got {len(channels)}."
            )
        if any(len(channel) > MAX_CHANNEL_LENGTH for channel in channels):
            raise ValueError(
                f"bus.Bus channel names are limited to {MAX_CHANNEL_LENGTH} characters."
            )
        if not isinstance(last, int) or isinstance(last, bool):
            raise ValueError("bus.Bus subscription 'last' must be an integer.")
        last = max(0, last)
        if last:
            last = 0 if last > self.env["bus.bus"].sudo()._bus_last_id() else last
        channels = [c for c in channels if self._is_subscribable_channel(c)]
        return {
            "channels": OrderedSet(self._build_bus_channel_list(list(channels))),
            "last": last,
        }

    def _is_subscribable_channel(self, channel):
        return True

    def _after_subscribe_data(self, data):
        pass

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
        pass

    def _authenticate(self):
        if wsrequest.session.uid is not None:
            if not security.check_session(wsrequest.session, self.env, wsrequest):
                wsrequest.session.logout(keep_db=True)
                raise SessionExpiredException
        else:
            public_user_id = self.env["ir.model.data"]._xmlid_to_res_id(
                "base.public_user"
            )
            wsrequest.update_env(user=public_user_id)
