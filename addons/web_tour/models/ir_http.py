from odoo import models


class IrHttp(models.AbstractModel):
    """Extend session info with tour state for the web client."""

    _inherit = "ir.http"

    def session_info(self):
        """Add ``tour_enabled`` and ``current_tour`` to the session payload."""
        result = super().session_info()
        result["tour_enabled"] = self.env.user.tour_enabled
        result["current_tour"] = self.env["web_tour.tour"].get_current_tour()
        return result
