from odoo import api, fields, models


class ProductTemplate(models.Model):
    "Inherit ProductTemplate"

    _inherit = "product.template"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    property_account_creditor_price_difference = fields.Many2one(
        comodel_name="account.account",
        string="Price Difference Account",
        company_dependent=True,
        ondelete="restrict",
        help="This account is used in automated inventory valuation to "
        "record the price difference between a purchase order "
        "and its related vendor bill when validating this vendor bill.",
    )
    route_ids = fields.Many2many(
        default=lambda self: self._get_buy_route(),
    )

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    @api.model
    def _get_buy_route(self):
        buy_route = self.env.ref(
            "purchase_stock.route_warehouse0_buy", raise_if_not_found=False
        )
        if buy_route:
            return self.env["stock.route"].search([("id", "=", buy_route.id)]).ids

        return []
