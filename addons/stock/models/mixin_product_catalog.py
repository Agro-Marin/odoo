from odoo import models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinProductCatalog(models.AbstractModel):
    _inherit = "mixin.product.catalog"

    def _prepare_catalog_extra_context(self):
        display_stock = self._is_display_stock_in_catalog()
        _debug.logic("catalog_extra_context", catalog=self, display_stock=display_stock)
        return {
            **super()._prepare_catalog_extra_context(),
            "display_stock": display_stock,
        }

    def _is_display_stock_in_catalog(self):
        return False
