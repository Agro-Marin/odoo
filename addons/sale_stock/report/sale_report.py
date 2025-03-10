from odoo import fields, models


class SaleReport(models.Model):
    _inherit = "sale.report"

    warehouse_id = fields.Many2one('stock.warehouse', 'Warehouse', readonly=True)

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res['warehouse_id'] = "o.warehouse_id"
        return res

    def _group_by_sale(self):
        res = super()._group_by_sale()
        res += """,
            o.warehouse_id"""
        return res
