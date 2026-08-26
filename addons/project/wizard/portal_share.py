from typing import Any

from odoo import models


class PortalShare(models.TransientModel):
    _inherit = "portal.share"

    def action_send_mail(self) -> dict[str, Any]:
        result = super().action_send_mail()

        if self.res_model == "project.task":
            self.resource_ref.message_subscribe(partner_ids=self.partner_ids.ids)

        return result
