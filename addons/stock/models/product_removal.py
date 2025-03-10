from odoo import fields, models


class ProductRemoval(models.Model):
    _name = "product.removal"
    _description = "Removal Strategy"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    name = fields.Char(
        "Name",
        required=True,
        translate=True,
    )
    method = fields.Char(
        "Method",
        required=True,
        translate=True,
        help="FIFO, LIFO...",
    )
