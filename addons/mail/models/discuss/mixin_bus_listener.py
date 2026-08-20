from markupsafe import Markup

from odoo import models


class MixinBusListener(models.AbstractModel):
    _inherit = "mixin.bus.listener"

    def _bus_send_transient_message(self, channel: models.Model, content: str) -> None:
        self._bus_send(
            "discuss.channel/transient_message",
            {
                "body": Markup("<span class='o_mail_notification'>%s</span>") % content,
                "channel_id": channel.id,
            },
        )
