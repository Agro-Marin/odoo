from odoo import fields, models
from odoo.tools import frozendict


class SaleReport(models.Model):
    _inherit = "sale.report"
    _depends = frozendict(
        {
            "sale.order": ["warehouse_id"],
            "stock.picking.type": ["warehouse_id"],
        }
    )

    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        readonly=True,
    )

    def _get_fields_select(self):
        fields = super()._get_fields_select()
        fields["warehouse_id"] = "o.warehouse_id"
        return fields

    def _get_fields_group_by(self):
        fields = super()._get_fields_group_by()
        fields.append("o.warehouse_id")
        return fields
