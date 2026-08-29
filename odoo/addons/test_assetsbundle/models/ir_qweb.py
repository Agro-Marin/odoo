from odoo import models
from odoo.tools import config


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _register_hook(self):
        super()._register_hook()
        registry = self.env.registry
        if config["init"] and registry.updated_modules and not registry.ready:
            self._pregenerate_assets_bundles()
