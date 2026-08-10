from odoo import fields, models


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
        default=0,
    )
    active = fields.Boolean(
        default=True,
    )
