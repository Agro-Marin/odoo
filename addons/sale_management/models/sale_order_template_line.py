from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class SaleOrderTemplateLine(models.Model):
    _name = "sale.order.template.line"
    _description = "Quotation Template Line"
    _order = "sale_order_template_id, sequence, id"

    _accountable_product_id_required = models.Constraint(
        "CHECK(display_type IS NOT NULL OR (product_id IS NOT NULL AND product_uom_id IS NOT NULL))",
        "Missing required product and UoM on accountable sale quote line.",
    )
    _non_accountable_fields_null = models.Constraint(
        "CHECK(display_type IS NULL OR (product_id IS NULL AND product_uom_qty = 0 AND product_uom_id IS NULL))",
        "Forbidden product, quantity and UoM on non-accountable sale quote line",
    )

    sale_order_template_id = fields.Many2one(
        comodel_name="sale.order.template",
        string="Quotation Template Reference",
        index=True,
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(
        string="Sequence",
        help="Gives the sequence order when displaying a list of sale quote lines.",
        default=10,
    )

    company_id = fields.Many2one(
        related="sale_order_template_id.company_id", store=True, index=True
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        check_company=True,
        domain=lambda self: self._product_id_domain(),
    )

    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related="product_id.product_tmpl_id.has_configurable_attributes",
        depends=["product_id"],
    )
    allowed_no_variant_ptav_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Selectable Extra Values",
        compute="_compute_allowed_no_variant_ptav_ids",
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        string="Extra Values",
        domain="[('id', 'in', allowed_no_variant_ptav_ids)]",
        compute="_compute_custom_attribute_values",
        store=True,
        precompute=True,
        readonly=False,
        ondelete="restrict",
        copy=True,
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name="product.attribute.custom.value",
        inverse_name="sale_order_template_line_id",
        string="Custom Values",
        compute="_compute_custom_attribute_values",
        store=True,
        precompute=True,
        readonly=False,
        copy=True,
    )

    name = fields.Text(
        string="Description",
        translate=True,
    )

    allowed_uom_ids = fields.Many2many("uom.uom", compute="_compute_allowed_uom_ids")
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        domain="[('id', 'in', allowed_uom_ids)]",
        compute="_compute_product_uom_id",
        store=True,
        readonly=False,
        precompute=True,
    )
    product_uom_qty = fields.Float(
        string="Quantity", required=True, digits="Product Unit", default=1
    )

    display_type = fields.Selection(
        [
            ("line_section", "Section"),
            ("line_subsection", "Subsection"),
            ("line_note", "Note"),
        ],
        default=False,
    )

    # Section-related fields
    parent_id = fields.Many2one(
        string="Parent Section Line",
        comodel_name="sale.order.template.line",
        compute="_compute_parent_id",
    )
    is_optional = fields.Boolean(
        string="Optional Line",
        copy=True,
        default=False,
    )

    # === COMPUTE METHODS ===#

    @api.depends("product_id")
    def _compute_allowed_no_variant_ptav_ids(self):
        """The extra values a template author may pick, mirroring `allowed_uom_ids`.

        A `no_variant` attribute has no variant to select, so the value has to
        be stored on the line itself; anything else is already carried by
        `product_id`.
        """
        for option in self:
            ptavs = option.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
            option.allowed_no_variant_ptav_ids = ptavs.filtered(
                lambda ptav: ptav.attribute_id.create_variant == "no_variant",
            )

    @api.depends("product_id")
    def _compute_custom_attribute_values(self):
        """Drop the values the newly chosen product does not offer.

        One compute for both fields, as `sale.order.line` already does: the two
        are invalidated by the same event and share the lookup of what is valid.
        """
        for option in self:
            if not option.product_id:
                option.product_custom_attribute_value_ids = False
                option.product_no_variant_attribute_value_ids = False
                continue

            has_custom = bool(option.product_custom_attribute_value_ids)
            has_no_variant = bool(option.product_no_variant_attribute_value_ids)

            if not has_custom and not has_no_variant:
                continue

            valid_values = option.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids

            if has_custom:
                invalid_custom = option.product_custom_attribute_value_ids.browse()
                for pacv in option.product_custom_attribute_value_ids:
                    if (
                        pacv.custom_product_template_attribute_value_id
                        not in valid_values
                    ):
                        invalid_custom |= pacv
                option.product_custom_attribute_value_ids -= invalid_custom

            if has_no_variant:
                invalid_no_variant = (
                    option.product_no_variant_attribute_value_ids.browse()
                )
                for ptav in option.product_no_variant_attribute_value_ids:
                    if ptav._origin not in valid_values:
                        invalid_no_variant |= ptav
                option.product_no_variant_attribute_value_ids -= invalid_no_variant

    @api.depends("product_id", "product_id.uom_id", "product_id.uom_ids")
    def _compute_allowed_uom_ids(self):
        for option in self:
            option.allowed_uom_ids = (
                option.product_id.uom_id | option.product_id.uom_ids
            )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for option in self:
            option.product_uom_id = option.product_id.uom_id

    def _compute_parent_id(self):
        option_lines = set(self)
        for template, lines in self.grouped("sale_order_template_id").items():
            if not template:
                lines.parent_id = False
                continue
            last_section = False
            last_sub = False
            for line in template.sale_order_template_line_ids.sorted("sequence"):
                if line.display_type == "line_section":
                    last_section = line
                    if line in option_lines:
                        line.parent_id = False
                    last_sub = False
                elif line.display_type == "line_subsection":
                    if line in option_lines:
                        line.parent_id = last_section
                    last_sub = line
                elif line in option_lines:
                    line.parent_id = last_sub or last_section

    # === CRUD METHODS ===#

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get(
                "display_type", self.default_get(["display_type"])["display_type"]
            ):
                vals.update(product_id=False, product_uom_qty=0, product_uom_id=False)
        return super().create(vals_list)

    def write(self, vals):
        if "display_type" in vals and self.filtered(
            lambda line: line.display_type != vals.get("display_type")
        ):
            raise UserError(
                _(
                    "You cannot change the type of a sale quote line. Instead you should delete the current line and create a new line of the proper type."
                )
            )
        return super().write(vals)

    # === BUSINESS METHODS ===#

    @api.model
    def _product_id_domain(self):
        """Returns the domain of the products that can be added to the template."""
        return [("sale_ok", "=", True), ("type", "!=", "combo")]

    def _prepare_order_line_values(self):
        """Give the values to create the corresponding order line.

        :return: `sale.order.line` create values
        :rtype: dict
        """
        self.check_singleton()
        vals = {
            "display_type": self.display_type,
            "product_id": self.product_id.id,
            "product_qty": self.product_uom_qty,
            "product_uom_id": self.product_uom_id.id,
            "is_optional": self.is_optional,
            "sequence": self.sequence,
            "product_no_variant_attribute_value_ids": [
                Command.set(self.product_no_variant_attribute_value_ids.ids),
            ],
            "product_custom_attribute_value_ids": [
                Command.create(
                    {
                        "custom_product_template_attribute_value_id": (
                            pacv.custom_product_template_attribute_value_id.id
                        ),
                        "custom_value": pacv.custom_value,
                    },
                )
                for pacv in self.product_custom_attribute_value_ids
            ],
        }
        if self.name:
            vals["name"] = self.name
        return vals
