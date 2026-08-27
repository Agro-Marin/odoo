from odoo import fields, models


class MixinBomVariantLine(models.AbstractModel):
    """BoM row (line, by-product or operation) that may be restricted to some variants."""

    _name = "mixin.bom.variant.line"
    _description = "BoM row that may be restricted to some variants"

    bom_id = fields.Many2one(
        "mrp.bom", "Parent BoM", index=True, ondelete="cascade", required=True
    )
    possible_bom_product_template_attribute_value_ids = fields.Many2many(
        related="bom_id.possible_product_template_attribute_value_ids"
    )
    bom_product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        string="Apply on Variants",
        ondelete="restrict",
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.",
    )

    def _skip_bom_line(self, product, never_attribute_values=False):
        """Is this row left out when the BoM is applied to `product`?

        A template is not a variant and cannot fail a variant restriction, so it
        never skips anything; that is what makes a BoM report readable at
        template level.
        """
        self.ensure_one()
        if not product or product._name == "product.template":
            return False
        return self.env["mrp.bom"]._skip_for_no_variant(
            product,
            self.bom_product_template_attribute_value_ids,
            never_attribute_values,
        )
