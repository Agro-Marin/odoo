from odoo import models


class MixinProductCatalog(models.AbstractModel):
    _inherit = "mixin.product.catalog"

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "display_stock": self._is_display_stock_in_catalog(),
        }

    def _is_display_stock_in_catalog(self):
        return False
