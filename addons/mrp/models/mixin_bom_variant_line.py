from itertools import product as cartesian_product
from itertools import starmap

from odoo import fields, models


class MixinBomVariantLine(models.AbstractModel):
    _name = "mixin.bom.variant.line"
    _description = "BoM row that may be restricted to some variants"

    bom_id = fields.Many2one(
        comodel_name="mrp.bom",
        string="Parent BoM",
        index=True,
        required=True,
        ondelete="cascade",
    )
    possible_bom_product_template_attribute_value_ids = fields.Many2many(
        related="bom_id.possible_product_template_attribute_value_ids"
    )
    bom_product_template_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Apply on Variants",
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        ondelete="restrict",
        help="BOM Product Variants needed to apply this line.",
    )

    def _is_bom_line_skipped(self, product, never_attribute_values=False):
        self.check_singleton()
        if not product or product._name == "product.template":
            return False
        return self.env["mrp.bom"]._is_skipped_for_no_variant(
            product,
            self.bom_product_template_attribute_value_ids,
            never_attribute_values,
        )

    def _filtered_applicable_to(self, product, never_attribute_values=False):
        return self.filtered(
            lambda row: not row._is_bom_line_skipped(product, never_attribute_values)
        )

    def _get_no_variant_values(self):
        return self.bom_product_template_attribute_value_ids.filtered(
            lambda value: value.attribute_id.create_variant == "no_variant"
        )

    def _filtered_possibly_applicable_to(self, product):
        return self._filtered_applicable_to(product, self._get_no_variant_values())

    def _get_no_variant_choices(self):
        values = self._get_no_variant_values()
        options = [
            [attribute_values]
            if attribute.display_type == "multi"
            else list(attribute_values)
            for attribute, attribute_values in values.grouped("attribute_id").items()
        ]
        return list(starmap(values.browse().union, cartesian_product(*options)))
