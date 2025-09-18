from odoo import fields, models
from odoo.tools.sql import SQL


class SaleReport(models.Model):
    _inherit = "sale.report"

    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        readonly=True,
    )

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res["warehouse_id"] = "o.warehouse_id"
        return res

    def _group_by_sale(self):
        res = super()._group_by_sale()
        return SQL(
            "%s , o.warehouse_id",
            res,
        )
