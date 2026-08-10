from odoo import api, models
from odoo.exceptions import ValidationError


class AttributeLineMixin(models.AbstractModel):
    """Reusable base for an attribute line (one attribute + its chosen values)."""

    # Mirrors product.template.attribute.line. Concrete models declare the parent
    # Many2one (e.g. partner_id, surface_id), attribute_id and value_ids (with
    # their concrete comodels and domains). This mixin only provides the shared
    # coherence validation.
    _name = "attribute.line.mixin"
    _description = "Attribute Line Mixin"

    @api.constrains("attribute_id", "value_ids")
    def _check_values(self):
        """Values must belong to the attribute; single attributes allow one."""
        for line in self:
            stray = line.value_ids.filtered(
                lambda v, line=line: v.attribute_id != line.attribute_id
            )
            if stray:
                raise ValidationError(
                    self.env._(
                        "Values %(values)s do not belong to attribute %(attr)s.",
                        values=", ".join(stray.mapped("display_name")),
                        attr=line.attribute_id.display_name,
                    )
                )
            if line.attribute_id.value_type == "single" and len(line.value_ids) > 1:
                raise ValidationError(
                    self.env._(
                        "Attribute %(attr)s accepts a single value.",
                        attr=line.attribute_id.display_name,
                    )
                )
