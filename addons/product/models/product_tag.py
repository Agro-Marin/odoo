from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class ProductTag(models.Model):
    _name = "product.tag"
    _description = "Product Tag"
    _order = "sequence, id"

    def _get_default_template_id(self):
        return self.env["product.template"].browse(
            self.env.context.get("product_template_id")
        )

    def _get_default_variant_id(self):
        return self.env["product.product"].browse(
            self.env.context.get("product_variant_id")
        )

    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Char(string="Color", default="#3C3C3C")
    product_template_ids = fields.Many2many(
        comodel_name="product.template",
        relation="product_tag_product_template_rel",
        string="Product Templates",
        default=_get_default_template_id,
    )
    product_product_ids = fields.Many2many(
        comodel_name="product.product",
        relation="product_tag_product_product_rel",
        string="Product Variants",
        domain="[('attribute_line_ids', '!=', False), ('product_tmpl_id', 'not in', product_template_ids)]",
        default=_get_default_variant_id,
    )
    product_ids = fields.Many2many(
        comodel_name="product.product",
        string="All Product Variants using this Tag",
        compute="_compute_product_ids",
        search="_search_product_ids",
    )
    visible_to_customers = fields.Boolean(
        string="Visible to customers",
        default=True,
        help="Whether the tag is displayed to customers.",
    )
    image = fields.Image(string="Image", max_width=200, max_height=200)

    # NB: no SQL `unique (name)` here. `name` is `translate=True`, so its column
    # is jsonb and a UNIQUE index compares whole translation *dicts*:
    # {"en_US": "Fragile"} and {"en_US": "Fragile", "fr_FR": "Fragile"} are
    # distinct values and both insert, which silently voided the guarantee as
    # soon as a second language was installed. The check has to run in Python,
    # on the value the user actually sees.
    @api.constrains("name")
    def _check_name_uniq(self):
        names = [tag.name for tag in self if tag.name]
        if not names:
            return
        # One query for the whole batch instead of one per record: importing or
        # creating tags in bulk ran a `search_count` per row. The duplicate may
        # be another record in `self` (two new tags sharing a name), so compare
        # against both the stored rows and the batch itself.
        taken = self.search(
            [("name", "in", names), ("id", "not in", self.ids)]
        ).grouped("name")
        seen = set()
        for tag in self:
            if not tag.name:
                continue
            if tag.name in taken or tag.name in seen:
                raise ValidationError(
                    self.env._("The tag name %(name)s already exists.", name=tag.name)
                )
            seen.add(tag.name)

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        # A None entry marks a record already copied in this operation (the
        # same record twice in `self`, or a cycle through a relation); it has
        # no values to rename and is dropped by `copy()`.
        return [
            vals if vals is None else dict(vals, name=self.env._("%s (copy)", tag.name))
            for tag, vals in zip(self, vals_list, strict=True)
        ]

    def copy_translations(self, new, excluded=()):
        # ``copy_data`` renames ``name`` in the duplicating user's language
        # only; without this the copy would keep the source record's exact
        # ``name`` in every other language.
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    @api.depends("product_template_ids.product_variant_ids", "product_product_ids")
    def _compute_product_ids(self):
        for tag in self:
            tag.product_ids = (
                tag.product_template_ids.product_variant_ids | tag.product_product_ids
            )

    def _search_product_ids(self, operator, operand):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return [
            "|",
            ("product_template_ids.product_variant_ids", operator, operand),
            ("product_product_ids", operator, operand),
        ]
