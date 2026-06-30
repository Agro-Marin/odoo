from odoo import api, models
from odoo.http import request


class IrHttp(models.AbstractModel):
    """Register portal-owned JS modules with the frontend translation loader."""

    _inherit = "ir.http"

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        """Append ``portal`` so its JS strings ship with frontend translation bundles."""
        mods = super()._get_translation_frontend_modules_name()
        return [*mods, "portal"]

    @api.model
    def get_frontend_session_info(self):
        """Carry the manual-tour state into the frontend (portal/website) session.

        Lets an onboarding tour resume after a redirect to the portal (e.g. to
        sign a report) instead of stopping at the page boundary.
        """
        result = super().get_frontend_session_info()
        if request.session.uid:
            result["tour_enabled"] = self.env.user.tour_enabled
            if self.env.user.tour_enabled:
                result["current_tour"] = self.env["web_tour.tour"].get_current_tour()
        return result
