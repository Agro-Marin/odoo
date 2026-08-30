from odoo import models

CHANNEL_PREFIX = "automation.workflow/"
SUBCHANNEL = "WORKFLOW"


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        requested = [
            channel
            for channel in channels
            if isinstance(channel, str) and channel.startswith(CHANNEL_PREFIX)
        ]
        if requested:
            rule_ids = set()
            for channel in requested:
                channels.remove(channel)
                suffix = channel[len(CHANNEL_PREFIX) :]
                if suffix.isdigit():
                    rule_ids.add(int(suffix))
            readable = (
                self.env["automation.rule"]
                .browse(sorted(rule_ids))
                .exists()
                ._filtered_access("read")
            )
            channels.extend((rule, SUBCHANNEL) for rule in readable)
        return super()._build_bus_channel_list(channels)
