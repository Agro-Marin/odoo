from typing import Any

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WebConfig(models.Model):
    _name = "web.config"
    _description = "A company's web configuration"
    _inherit = ["mixin.company.config"]

    homemenu_default_config = fields.Json(
        string="Default Home Menu Layout",
        help="The home menu layout a user of this company sees until they "
        "customise their own: the same shape as the user's setting.",
    )

    @api.model
    def set_homemenu_default(self, config: Any) -> dict[str, Any]:
        normalized = self.env["res.users.settings"]._normalize_homemenu_config(config)
        if normalized is None:
            raise ValidationError(self.env._("Invalid launcher layout."))
        company_config = self._for(self.env.company)
        company_config.check_singleton()
        company_config.homemenu_default_config = normalized
        return normalized
