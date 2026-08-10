from odoo import fields, models


class AttributeMixin(models.AbstractModel):
    """Reusable base for an EAV attribute (the dimension being profiled)."""

    # Concrete models inherit this mixin and add their own value_ids One2many
    # pointing to the matching concrete value model. Extend value_type with
    # selection_add if the subject needs extra modes.
    #
    # Name uniqueness is NOT declared here, and a concrete model must not
    # declare it as a plain UNIQUE(name) either. ``name`` is translated, so it
    # is a jsonb column and a UNIQUE constraint on it compares whole
    # translation *documents* rather than names -- it silently permits
    # duplicates as soon as a second language is active, because Odoo writes
    # the active language alongside the source term on create. The rule has to
    # compare the *source term*, which means an expression, and PostgreSQL does
    # not allow expressions in a UNIQUE constraint: declare a
    # ``models.UniqueIndex`` over ``(name->>'en_US')`` instead.
    _name = "attribute.mixin"
    _description = "Attribute Mixin"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        translate=True,
    )
    sequence = fields.Integer(
        default=10,
    )
    active = fields.Boolean(
        default=True,
    )
    value_type = fields.Selection(
        selection=[
            ("single", "Single value"),
            ("multi", "Multiple values"),
        ],
        required=True,
        default="single",
        help="How values of this attribute are picked.",
    )
