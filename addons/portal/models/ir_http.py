from odoo import models


class IrHttp(models.AbstractModel):
    """Register portal-owned JS modules with the frontend translation loader."""

    _inherit = "ir.http"

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        """Append ``portal`` so its JS strings ship with frontend translation bundles."""
        mods = super()._get_translation_frontend_modules_name()
        return [*mods, "portal"]
