from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose the ``portal.allow_api_keys`` toggle in the General Settings."""

    _inherit = "res.config.settings"

    portal_allow_api_keys = fields.Boolean(
        "Customer API Keys",
        config_parameter="portal.allow_api_keys",
    )
