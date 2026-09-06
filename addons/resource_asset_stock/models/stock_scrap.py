from odoo import models


class StockScrap(models.Model):
    _inherit = "stock.scrap"

    def _action_done(self):
        res = super()._action_done()
        assets = self.filtered(
            lambda scrap: scrap.state == "done" and scrap.lot_id.asset_id
        ).lot_id.asset_id
        assets.filtered(lambda asset: asset.state != "disposed").action_dispose()
        return res
