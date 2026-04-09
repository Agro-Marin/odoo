from typing import Any, Self

from odoo import models

# Maximum number of _bus_channel() delegation hops before cycle detection fires.
_MAX_CHANNEL_HOPS = 10


class BusListenerMixin(models.AbstractModel):
    """Mixin that enables sending bus notifications via a model record.

    Inherit this mixin and register the model as a valid channel in
    ``_build_bus_channel_list`` to allow ``record._bus_send(...)`` calls.

    Override ``_bus_channel()`` to delegate to a related record (e.g. a
    user model delegates to its partner).
    """

    _name = "bus.listener.mixin"
    _description = "Can send messages via bus.bus"

    def _bus_send(
        self, notification_type: str, message: Any, /, *, subchannel: str | None = None
    ) -> None:
        """Send a bus notification for each record in ``self``.

        Follows the ``_bus_channel()`` delegation chain (up to
        ``_MAX_CHANNEL_HOPS`` hops) to resolve the final channel.  Records
        whose chain resolves to an empty recordset are silently skipped.
        """
        bus = self.env["bus.bus"]
        for record in self:
            main_channel = record
            for _ in range(_MAX_CHANNEL_HOPS):
                new_main_channel = main_channel._bus_channel()
                if new_main_channel == main_channel:
                    break
                main_channel = new_main_channel
            else:
                raise RecursionError(
                    f"_bus_channel() chain on {record!r} did not terminate within "
                    f"{_MAX_CHANNEL_HOPS} hops. Check for a cycle in _bus_channel() overrides."
                )
            if not main_channel:
                continue
            main_channel.ensure_one()
            channel = main_channel if subchannel is None else (main_channel, subchannel)
            bus._sendone(channel, notification_type, message)

    def _bus_channel(self) -> Self:
        """Return the record that acts as the bus channel for ``self``.

        Override to delegate to a related record (e.g. ``self.partner_id``).
        The default returns ``self``.
        """
        return self
