from odoo import fields, models
from odoo.tools import frozendict

from odoo.addons.trade.tools import SALE


class CustomerDelayReport(models.Model):
    _name = "customer.delay.report"
    _inherit = ["mixin.order.delay.report"]
    _description = "Customer Delay Report"
    _auto = False

    _order_line_table = "sale_order_line"
    _order_table = "sale_order"
    _link_column = "sale_line_id"
    _date_commitment_alias = "o"
    _direction = SALE
    _access_anchors = frozendict(
        {
            "company": models.Anchor("company_id", shared=False),
        }
    )

    partner_id = fields.Many2one(string="Customer")
