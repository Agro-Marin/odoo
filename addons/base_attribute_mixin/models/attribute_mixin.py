from odoo import fields, models


class AttributeMixin(models.AbstractModel):
    """Reusable base for an EAV attribute (the dimension being profiled)."""

    # Concrete models inherit this mixin and add their own value_ids One2many
    # pointing to the matching concrete value model. Extend value_type or
    # display_type with selection_add if the subject needs extra modes.
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

    # Concrete model carrying the lines that bind this attribute to a subject,
    # e.g. "product.template.attribute.line". Setting it makes a change of
    # ``value_type`` re-validate the lines already using the attribute; leaving
    # it None skips that check.
    #
    # It is needed because ``attribute.line.mixin._check_values`` is an
    # ``@api.constrains`` on the *line* and the ORM has no cross-model
    # constrains: nothing re-runs it when the *attribute* moves. Without this,
    # flipping value_type from 'multi' to 'single' left every existing
    # multi-value line silently violating the very rule the constraint exists
    # to enforce -- the violation was reachable, just not by the write the
    # constraint watches.
    _attribute_line_model = None

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
        help="How many values of this attribute a single line may hold. This "
        "is a data rule, orthogonal to display_type, which only picks the "
        "widget: a 'single' attribute may still render as radio, pills, "
        "select or colour swatches.",
    )
    display_type = fields.Selection(
        selection=[
            ("radio", "Radio"),
            ("pills", "Pills"),
            ("select", "Select"),
            ("color", "Color"),
            ("multi", "Multi-checkbox"),
            ("image", "Image"),
        ],
        required=True,
        default="radio",
        help="Widget used to pick values of this attribute.",
    )

    def write(self, vals):
        """Re-validate existing lines when the cardinality rule changes.

        See ``_attribute_line_model`` for why this cannot be an
        ``@api.constrains``.
        """
        result = super().write(vals)
        if "value_type" in vals and self._attribute_line_model:
            self.env[self._attribute_line_model].search(
                [("attribute_id", "in", self.ids)]
            )._check_values()
        return result
