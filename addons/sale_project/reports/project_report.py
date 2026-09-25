from odoo import fields, models
from odoo.tools import frozendict


class ReportProjectTaskUser(models.Model):
    _inherit = "report.project.task.user"
    _depends = frozendict(
        {
            "project.task": ["sale_line_id", "sale_order_id"],
        }
    )

    sale_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sales Order Item",
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        readonly=True,
    )

    def _select(self):
        return super()._select() + ", t.sale_line_id as sale_line_id, t.sale_order_id"

    def _group_by(self):
        return super()._group_by() + ", t.sale_line_id, t.sale_order_id"
