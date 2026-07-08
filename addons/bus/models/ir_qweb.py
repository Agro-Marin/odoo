from odoo import models


class IrQWeb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_bundles_to_pregenerate(self):
        js_assets, css_assets = super()._get_bundles_to_pregenerate()
        assets = {"bus.websocket_worker_assets"}
        return (js_assets | assets, css_assets | assets)
