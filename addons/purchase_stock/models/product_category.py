from odoo import fields, models


class ProductCategory(models.Model):
    "Inherit ProductCategory"

    _inherit = "product.category"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    property_account_creditor_price_difference_categ = fields.Many2one(
        comodel_name="account.account",
        string="Price Difference Account",
        company_dependent=True,
        ondelete="restrict",
        help="This account will be used to value price difference "
        "between purchase price and accounting cost.",
    )
