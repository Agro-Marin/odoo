# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class BusListenerMixin(models.AbstractModel):
    """Allow sending messages related to the current model via as a bus.bus channel.

    The model needs to be allowed as a valid channel for the bus in `_build_bus_channel_list`.
    """

    _name = "bus.listener.mixin"
    _description = "Can send messages via bus.bus"

    _MAX_CHANNEL_HOPS = 10

    def _bus_send(self, notification_type, message, /, *, subchannel=None):
        """Send a notification to the webclient."""
        bus = self.env["bus.bus"]
        for record in self:
            main_channel = record
            for _ in range(self._MAX_CHANNEL_HOPS):
                new_main_channel = main_channel._bus_channel()
                if new_main_channel == main_channel:
                    break
                main_channel = new_main_channel
            else:
                raise RecursionError(
                    f"_bus_channel() chain on {record!r} did not terminate within "
                    f"{self._MAX_CHANNEL_HOPS} hops. Check for a cycle in _bus_channel() overrides."
                )
            if not main_channel:
                continue
            main_channel.ensure_one()
            channel = main_channel if subchannel is None else (main_channel, subchannel)
            bus._sendone(channel, notification_type, message)

    def _bus_channel(self):
        return self
