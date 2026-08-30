from odoo import models

EMPLOYEE_CHANNEL_PREFIX = "hr.employee_"


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        """Let a client follow the presence of the employees it may read.

        The presence widget asks for ``hr.employee_<id>``; turn that into the
        record the notification is actually sent on. Which employees the
        subscriber may follow is decided by searching ``hr.employee.public``,
        not by browsing it: a browse would answer the model-level access check
        and skip ``hr_employee_public_comp_rule``, which is the rule that keeps
        one company out of another's employees.
        """
        requested_ids = []
        kept_channels = []
        for channel in channels:
            suffix = (
                channel[len(EMPLOYEE_CHANNEL_PREFIX) :]
                if isinstance(channel, str)
                and channel.startswith(EMPLOYEE_CHANNEL_PREFIX)
                else None
            )
            if suffix and suffix.isdigit():
                requested_ids.append(int(suffix))
            else:
                kept_channels.append(channel)
        if requested_ids:
            readable = self.env["hr.employee.public"].search(
                [("id", "in", requested_ids)]
            )
            kept_channels.extend(readable.employee_id)
        return super()._build_bus_channel_list(kept_channels)
