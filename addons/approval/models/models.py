from odoo import api, models

from . import approval_trace as trace


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    def get_views(self, views, options=None):
        result = super().get_views(views, options=options)
        gated = self.env["approval.binding"]._get_names_of_gated_models()
        for model_name, model_info in result["models"].items():
            model_info["has_approval_bindings"] = model_name in gated
        trace.BUTTON.event(
            "get_views",
            models=len(result["models"]),
            gated=sum(1 for name in result["models"] if name in gated),
        )
        return result

    def _register_hook(self):
        # Campaign scaffolding: wraps the entry points approval_trace.CALL_TRACES
        # names. Removing the campaign removes these two overrides whole.
        super()._register_hook()
        trace.instrument(self)

    def _unregister_hook(self):
        trace.uninstrument(self)
        super()._unregister_hook()
