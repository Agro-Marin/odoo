from random import randint

from odoo import api, fields, models


class AttributeValueMixin(models.AbstractModel):
    """Reusable base for an EAV attribute value."""

    # Concrete models add the attribute_id Many2one to their own attribute
    # model, and scope name uniqueness to it -- as a unique expression index
    # over the source term, not a plain UNIQUE(attribute_id, name); see
    # attribute.mixin for why the constraint form does not hold on a
    # translated name.
    _name = "attribute.value.mixin"
    _description = "Attribute Value Mixin"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        translate=True,
    )
    sequence = fields.Integer(
        default=10,
    )
    color = fields.Integer(
        default=lambda self: self._get_default_color(),
    )
    active = fields.Boolean(
        default=True,
    )

    def _get_default_color(self):
        """Spread values over the palette instead of collapsing them onto one.

        A fixed default gives every value of every attribute the same colour,
        which makes the chips that render them useless as a distinguisher. The
        palette is 1-11; 0 means "no colour" and is deliberately not drawn.
        """
        return randint(1, 11)

    @api.depends("attribute_id")
    @api.depends_context("show_attribute")
    def _compute_display_name(self):
        """Qualify a value with its attribute.

        A bare value name is ambiguous wherever values of different attributes
        meet -- "Large" or "High" says nothing on its own. The exception is a
        form that already groups values under their attribute (an attribute's
        own value list, a line being configured), which passes
        ``show_attribute=False`` to suppress the repetition.
        """
        if not self.env.context.get("show_attribute", True):
            return super()._compute_display_name()
        for value in self:
            value.display_name = f"{value.attribute_id.name}: {value.name}"
        return None
