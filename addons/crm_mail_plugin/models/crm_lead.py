from odoo import api, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model
    def _form_view_auto_fill(self):
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "crm.lead",
            "context": {
                "default_partner_id": self.env.context.get("params", {}).get(
                    "partner_id"
                ),
            },
        }
