from odoo import api, models

from odoo.addons.website.models import ir_http


class IrRule(models.Model):
    _inherit = "ir.rule"

    @api.model
    def _eval_context(self):
        res = super()._eval_context()

        is_frontend = ir_http.get_request_website()
        Website = self.env["website"]
        res["website"] = (is_frontend and Website.get_current_website()) or Website
        return res

    def _compute_domain_keys(self):
        return super()._compute_domain_keys() + ["website_id"]
