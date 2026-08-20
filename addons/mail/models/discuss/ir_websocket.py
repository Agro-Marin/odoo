import re

from odoo import models


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels: list) -> list:
        remaining = []
        discuss_channel_ids = []
        token_guest = self.env["mail.guest"]
        for channel in channels:
            if isinstance(channel, str):
                if channel.startswith("mail.guest_"):
                    token_guest = self.env["mail.guest"]._get_guest_from_token(
                        channel.split("_")[1]
                    )
                    continue
                if match := re.findall(r"discuss\.channel_(\d+)", channel):
                    discuss_channel_ids.append(int(match[0]))
                    continue
            remaining.append(channel)
        if token_guest:
            self = self.with_context(guest=token_guest)
        if guest := self.env["mail.guest"]._get_guest_from_context():
            remaining.append(guest)
        domain = ["|", ("is_member", "=", True), ("id", "in", discuss_channel_ids)]
        all_user_channels = self.env["discuss.channel"].search(domain)
        remaining.extend(all_user_channels)
        if not self.env.user.share:
            remaining.extend((c, "internal_users") for c in all_user_channels)
        return super()._build_bus_channel_list(remaining)
