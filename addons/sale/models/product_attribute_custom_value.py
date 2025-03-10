from odoo import fields, models


class ProductAttributeCustomValue(models.Model):
    """Inherits the 'product.attribute.custom.value' model to link custom attribute values to sales order lines.

    This module adds a Many2one field to associate custom attribute values with specific sales order lines,
    ensuring that only one custom value is allowed per attribute value per sales order line.
    """

    _inherit = "product.attribute.custom.value"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_order_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sales Order Line",
        ondelete="cascade",
    )

    # -----------------------------------------------------------
    # SQL CONSTRAINTS
    # -----------------------------------------------------------

    _sol_custom_value_unique = models.Constraint(
        "unique(custom_product_template_attribute_value_id, sale_order_line_id)",
        "Only one Custom Value is allowed per Attribute Value per Sales Order Line.",
    )
