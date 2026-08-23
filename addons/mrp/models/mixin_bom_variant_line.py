from odoo import fields, models


class MixinBomVariantLine(models.AbstractModel):
    """What a BoM's lines, by-products and operations say identically.

    All three hang off one `mrp.bom`, all three can be restricted to a subset of
    the finished product's variants, and all three answered the same question --
    "does this row apply when the BoM is used for that variant?" -- with the same
    ten-line body under three different names: `_skip_bom_line`,
    `_skip_byproduct_line` and `_skip_operation_line`. One name, one body, and
    the two attribute-value fields declared once instead of three times.

    `mrp.routing.workcenter` adds one clause: an archived operation never
    applies. It says so by overriding `_skip_bom_line`, not by carrying a fourth
    copy of the rest.

    What is deliberately NOT here: `product_id`, `product_qty` and
    `product_uom_id`. An operation has none of them, so everything that reads a
    component's quantity -- the unit-consistency constraint, the product-catalog
    payload -- lives on `mixin.bom.component`, which inherits this one.
    """

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
