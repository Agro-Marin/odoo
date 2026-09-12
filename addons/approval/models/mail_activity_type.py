from odoo import api, models

from . import approval_trace as trace


class MailActivityType(models.Model):
    _inherit = "mail.activity.type"

    @api.model
    def _get_model_info_by_xmlid(self):
        info = super()._get_model_info_by_xmlid()
        info["approval.mail_activity_data_approval"] = {
            "res_model": "approval.request",
            "unlink": False,
        }
        trace.REGISTRY.event("activity_model_info", entries=len(info))
        return info
