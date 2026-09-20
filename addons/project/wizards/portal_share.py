from typing import Any

from odoo import models

from ..tools import debug_log as dbg


class PortalShare(models.TransientModel):
    _inherit = "portal.share"

    def action_send_mail(self) -> dict[str, Any]:
        result = super().action_send_mail()

        if self.res_model == "project.task":
            dbg.pipeline.debug(
                "[task:%s] portal share -> subscribing %s",
                self.res_id,
                dbg.rec(self.partner_ids),
            )
            self.resource_ref.message_subscribe(partner_ids=self.partner_ids.ids)

        return result
