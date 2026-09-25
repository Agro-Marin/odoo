from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    analytic_costs = fields.Boolean(
        tracking=True,
        help="Validating stock pickings will generate analytic entries for the selected project. Products set for re-invoicing will also be billed to the customer.",
    )
