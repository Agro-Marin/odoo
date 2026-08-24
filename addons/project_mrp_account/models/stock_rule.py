from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _prepare_mo_vals(self, procurement, bom):
        res = super()._prepare_mo_vals(procurement, bom)
        if procurement.values.get("project_id"):
            res["project_id"] = procurement.values["project_id"]
        return res
