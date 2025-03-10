from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ProductComboItem(models.Model):
    _name = "product.combo.item"
    _description = "Product Combo Item"
    _check_company_auto = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    combo_id = fields.Many2one(
        comodel_name="product.combo",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="combo_id.company_id",
        store=True,
        precompute=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
        domain=[("type", "!=", "combo")],
        ondelete="restrict",
    )
    currency_id = fields.Many2one(
        related="product_id.currency_id",
    )
    lst_price = fields.Float(
        related="product_id.lst_price",
        string="Original Price",
        digits="Product Price",
    )
    extra_price = fields.Float(
        string="Extra Price",
        digits="Product Price",
        default=0.0,
    )

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    @api.constrains("product_id")
    def _check_product_id_no_combo(self):
        if any(combo_item.product_id.type == "combo" for combo_item in self):
            raise ValidationError(
                _('A combo choice can\'t contain products of type "combo".')
            )
