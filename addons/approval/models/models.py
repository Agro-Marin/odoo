from odoo import api, models


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    def get_views(self, views, options=None):
        result = super().get_views(views, options=options)
        gated = self.env["approval.binding"]._get_names_of_gated_models()
        for model_name, model_info in result["models"].items():
            model_info["has_approval_bindings"] = model_name in gated
        return result
