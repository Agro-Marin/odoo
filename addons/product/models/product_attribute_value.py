from odoo import _, api, fields, models


class ProductAttributeValue(models.Model):
    # if you change this _order, keep it in sync with the method
    # `_sort_key_variant` in `product.template'
    _name = "product.attribute.value"
    _inherit = "mixin.attribute.value"
    _order = "attribute_id, sequence, id"
    _description = "Attribute Value"

    attribute_id = fields.Many2one(
        comodel_name="product.attribute",
        string="Attribute",
        required=True,
        ondelete="cascade",
        index=True,
        help="The attribute cannot be changed once the value is used on at least one product.",
    )
    display_type = fields.Selection(related="attribute_id.display_type")
    # name, active and color come from mixin.attribute.value; only the labels
    # and the index are product-specific. `sequence` now carries the mixin's
    # default of 10 -- it had none here, so new values were created with a NULL
    # sequence, which sorts *last* under `_order` and made the display order of
    # a freshly added value depend on nothing the user set.
    name = fields.Char(string="Value")
    sequence = fields.Integer(
        string="Sequence",
        index=True,
        help="Determine the display order",
    )
    color = fields.Integer(string="Color Index")
    html_color = fields.Char(
        string="Color",
        help="Here you can set a specific HTML color index (e.g. #ff0000)"
        " to display the color if the attribute type is 'Color'.",
    )
    pav_attribute_line_ids = fields.Many2many(
        comodel_name="product.template.attribute.line",
        relation="product_attribute_value_product_template_attribute_line_rel",
        string="Lines",
        copy=False,
    )

    default_extra_price = fields.Float()
    image = fields.Image(
        string="Image",
        max_width=70,
        max_height=70,
        help="You can upload an image that will be used as the color of the attribute value.",
    )

    is_custom = fields.Boolean(
        string="Free text",
        help="Allow customers to set their own value",
    )
    is_used_on_products = fields.Boolean(
        string="Used on Products",
        compute="_compute_is_used_on_products",
    )
    default_extra_price_changed = fields.Boolean(
        compute="_compute_default_extra_price_changed",
    )

    # === CRUD METHODS === #

    # The re-home guard ("cannot change the attribute of a value in use") and
    # the delete guard both live on mixin.attribute.value now; _used_records
    # and _usage_label below narrow "in use" to active templates.

    def _used_records(self):
        return self.filtered("is_used_on_products")

    def _usage_label(self):
        return ", ".join(
            self.pav_attribute_line_ids.product_tmpl_id.mapped("display_name")
        )

    def write(self, vals):
        invalidate = "sequence" in vals and any(
            record.sequence != vals["sequence"] for record in self
        )
        res = super().write(vals)
        if invalidate:
            # prefetched o2m have to be resequenced
            # (eg. product.template.attribute.line: value_ids)
            self.env.flush_all()
            self.env.invalidate_all()
        return res

    def unlink(self):
        # Batch search all PTAVs linked to these PAVs in a single query.
        # `active_test=False` has to be on the recordset the m2m is *read*
        # from: the cache holds every id of the relation and the ORM applies
        # the active filter at read time, from the reading record's context.
        # Grouping through `|=` into a recordset built on the bare env dropped
        # that context (a union takes the left operand's env), so
        # `ptav_product_variant_ids` came back active-only, the branch below
        # was dead, and a value whose only trace was an archived variant went
        # to `super().unlink()` -- where the RESTRICT foreign key of
        # `product_variant_combination` turned it into a raw RestrictViolation
        # traceback instead of the archive this code is written to do.
        PTAV = self.env["product.template.attribute.value"].with_context(
            active_test=False
        )
        ptavs_by_pav = PTAV.search(
            [("product_attribute_value_id", "in", self.ids)]
        ).grouped("product_attribute_value_id")
        pavs_to_archive = self.env["product.attribute.value"]
        for pav in self:
            linked_products = ptavs_by_pav.get(pav, PTAV).ptav_product_variant_ids
            active_linked_products = linked_products.filtered("active")
            # Archive (rather than delete) a value whose only remaining trace is
            # an archived variant -- but never one an *active* product still
            # offers on an attribute line: archiving it there desynchronises the
            # line (`value_ids` stops listing it while the stored `value_count`
            # and the active `product.template.attribute.value` keep counting
            # it) and the next `_create_variant_ids` resurrects the very variant
            # the user archived. Such a value must keep raising the explanatory
            # UserError from `_unlink_except_in_use`, exactly like the
            # archived-template case handled below.
            if (
                linked_products
                and not active_linked_products
                and not pav.is_used_on_products
            ):
                pavs_to_archive |= pav
        # A value still referenced by an attribute line cannot be deleted:
        # `product_attribute_value_product_template_attribute_line_rel` is a
        # restrict FK. `_unlink_except_in_use` only sees what `_used_records`
        # reports, and that is narrowed here to lines of *active* templates, so
        # a value used solely on an archived template
        # passed every Python guard and surfaced as a raw RestrictViolation
        # traceback. Archive it instead, consistently with the archived-variant
        # case handled above.
        remaining = self - pavs_to_archive
        if remaining:
            # Only for values whose *sole* remaining usage is on archived
            # templates: a value still used on an active product must keep
            # raising the explanatory UserError from
            # `_unlink_except_in_use` rather than being archived.
            still_referenced = remaining.with_context(active_test=False).filtered(
                lambda pav: pav.pav_attribute_line_ids and not pav.is_used_on_products
            )
            pavs_to_archive |= still_referenced.with_env(self.env)
        if pavs_to_archive:
            pavs_to_archive.action_archive()
        return super(ProductAttributeValue, self - pavs_to_archive).unlink()

    # === COMPUTE METHODS === #

    # _get_default_color and _compute_display_name (qualifying a value with its
    # attribute, suppressed by `show_attribute=False`) now live on
    # mixin.attribute.value -- neither was product-specific.

    @api.depends("pav_attribute_line_ids")
    def _compute_is_used_on_products(self):
        for pav in self:
            pav.is_used_on_products = bool(
                pav.pav_attribute_line_ids.filtered("product_tmpl_id.active")
            )

    @api.depends("default_extra_price")
    def _compute_default_extra_price_changed(self):
        company_domain = self.env["product.template"]._check_company_domain(
            self.env.companies
        )
        # `sudo` required to know which products we lack access to
        ptavs_by_pav = (
            self.env["product.template.attribute.value"]
            .sudo()
            .search_fetch(
                [
                    ("product_attribute_value_id", "in", self.ids),
                    ("product_tmpl_id", "any", company_domain),
                ],
                ["price_extra", "product_attribute_value_id"],
            )
            .grouped("product_attribute_value_id")
        )
        for pav in self:
            ptavs = ptavs_by_pav.get(pav, [])
            pav.default_extra_price_changed = (
                pav.default_extra_price != pav._origin.default_extra_price
                or any(pav.default_extra_price != ptav.price_extra for ptav in ptavs)
            )

    # === ACTION METHODS === #

    @api.readonly
    def action_add_to_products(self):
        return {
            "name": _("Add to all products"),
            "type": "ir.actions.act_window",
            "res_model": "update.product.attribute.value",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_attribute_value_id": self.id,
                "default_mode": "add",
                "dialog_size": "medium",
            },
        }

    @api.readonly
    def action_update_prices(self):
        return {
            "name": _("Update product extra prices"),
            "type": "ir.actions.act_window",
            "res_model": "update.product.attribute.value",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_attribute_value_id": self.id,
                "default_mode": "update_extra_price",
                "dialog_size": "medium",
            },
        }

    def _without_no_variant_attributes(self):
        return self.filtered(
            lambda pav: pav.attribute_id.create_variant != "no_variant",
        )

    def check_is_used_on_products(self):
        """Message naming the products blocking a delete, or False.

        Called over RPC by the attribute-value list
        (``static/src/js/product_attribute_value_list.js``), so the shape of
        the return value -- message-or-False -- is a public contract.
        """
        return self._in_use_message()
