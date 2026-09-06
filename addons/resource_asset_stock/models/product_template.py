from odoo import api, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.constrains("asset_kind_id", "tracking", "is_storable")
    def _check_asset_kind_tracking(self):
        for template in self:
            if (
                template.asset_kind_id
                and template.is_storable
                and template.tracking != "serial"
            ):
                raise ValidationError(
                    self.env._(
                        "%(name)s: a storable product whose units are assets must be tracked by unique serial number, so that each unit is one asset.",
                        name=template.name,
                    )
                )
