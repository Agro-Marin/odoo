from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain

from .utils import unlink_where_possible


class ProductTemplateAttributeLine(models.Model):
    """Attributes available on product.template with their selected values in a m2m.
    Used as a configuration model to generate the appropriate product.template.attribute.value
    """

    _name = "product.template.attribute.line"
    _rec_name = "attribute_id"
    _rec_names_search = ["attribute_id", "value_ids"]
    _description = "Product Template Attribute Line"
    _order = "sequence, attribute_id, id"

    active = fields.Boolean(default=True)
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    attribute_id = fields.Many2one(
        comodel_name="product.attribute",
        string="Attribute",
        required=True,
        ondelete="restrict",
        index=True,
    )
    value_ids = fields.Many2many(
        comodel_name="product.attribute.value",
        relation="product_attribute_value_product_template_attribute_line_rel",
        string="Values",
        domain="[('attribute_id', '=', attribute_id)]",
        ondelete="restrict",
    )
    value_count = fields.Integer(compute="_compute_value_count", store=True)
    product_template_value_ids = fields.One2many(
        comodel_name="product.template.attribute.value",
        inverse_name="attribute_line_id",
        string="Product Attribute Values",
    )

    # NB: a template may deliberately carry the *same* attribute on several
    # lines (e.g. a two-tone product with a primary and a secondary colour).
    # The combination engine supports it and both
    # `test_product_attribute_value_config.test_get_first_possible_combination`
    # and `test_variants.test_dynamic_variants_unarchive` assert that behaviour,
    # so there is intentionally no uniqueness on (product_tmpl_id, attribute_id).

    @api.depends("value_ids")
    def _compute_value_count(self):
        for record in self:
            record.value_count = len(record.value_ids)

    @api.onchange("attribute_id")
    def _onchange_attribute_id(self):
        if self.attribute_id.create_variant == "no_variant":
            self.value_ids = self.env["product.attribute.value"].search(
                [
                    ("attribute_id", "=", self.attribute_id.id),
                ]
            )
        else:
            self.value_ids = self.value_ids.filtered(
                lambda pav: pav.attribute_id == self.attribute_id
            )

    @api.constrains("active", "value_ids", "attribute_id")
    def _check_valid_values(self):
        for ptal in self:
            if ptal.active and not ptal.value_ids:
                raise ValidationError(
                    _(
                        "The attribute %(attribute)s must have at least one value for the product %(product)s.",
                        attribute=ptal.attribute_id.display_name,
                        product=ptal.product_tmpl_id.display_name,
                    )
                )
            for pav in ptal.value_ids:
                if pav.attribute_id != ptal.attribute_id:
                    raise ValidationError(
                        _(
                            "On the product %(product)s you cannot associate the value %(value)s"
                            " with the attribute %(attribute)s because they do not match.",
                            product=ptal.product_tmpl_id.display_name,
                            value=pav.display_name,
                            attribute=ptal.attribute_id.display_name,
                        )
                    )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Override to:
        - Activate archived lines having the same configuration (if they exist)
            instead of creating new lines.
        - Set up related values and related variants.

        Reactivating existing lines allows to re-use existing variants when
        possible, keeping their configuration and avoiding duplication.

        The result is assembled back in `vals_list` order. Returning the
        reactivated lines first (the previous behaviour) broke the
        `@api.model_create_multi` contract, and callers pair the two lists by
        position: `product.product._import_resolve_ptavs` zips them
        `strict=True`, so a batch whose *later* rows matched an archived line
        mapped every `(template, attribute)` to the wrong line, resolved empty
        `product.template.attribute.value` records, and aborted the whole
        product import with a raw "column ... is of type integer but
        expression is of type boolean" from Postgres. `_load_records` assigns
        external ids by the same positional pairing.
        """
        create_values = []
        create_positions = []
        # `record_ids[i]` is the line answering `vals_list[i]`.
        record_ids = [None] * len(vals_list)
        # Reusable archived lines, resolved in one query for the whole batch.
        # The per-row search this replaces existed only to skip lines already
        # revived by an earlier row; consuming them from an ordered pool does
        # the same thing without a query per row.
        archived_ptal_pool = self._pool_of_reusable_archived_lines(vals_list)
        for index, value in enumerate(vals_list):
            vals = dict(value, active=value.get("active", True))
            pool_key = (vals.pop("product_tmpl_id", 0), vals.pop("attribute_id", 0))
            candidates = archived_ptal_pool.get(pool_key)
            archived_ptal = candidates.pop(0) if candidates else self.browse()
            if archived_ptal:
                # Write given `vals` in addition of `active` to ensure
                # `value_ids` or other fields passed to `create` are saved too,
                # but change the context to avoid updating the values and the
                # variants until all the expected lines are created/updated.
                archived_ptal.with_context(
                    update_product_template_attribute_values=False
                ).write(vals)
                record_ids[index] = archived_ptal.id
            else:
                create_values.append(value)
                create_positions.append(index)
        for position, record in zip(
            create_positions, super().create(create_values), strict=True
        ):
            record_ids[position] = record.id
        res = self.browse(record_ids)
        if self.env.context.get("update_product_template_attribute_values", True):
            res._update_product_template_attribute_values()
        return res

    def write(self, vals):
        """Override to:
        - Add constraints to prevent doing changes that are not supported such
            as modifying the template or the attribute of existing lines.
        - Clean up related values and related variants when archiving or when
            updating `value_ids`.
        """
        # Copy: the archiving branch below injects `value_ids` into this dict,
        # and `vals` belongs to the caller. Mutating it made a dict reused for a
        # second `write` silently carry a `Command.clear()` on `value_ids` --
        # wiping the values of records the caller never meant to touch.
        values = dict(vals)
        if "product_tmpl_id" in values:
            for ptal in self:
                if ptal.product_tmpl_id.id != values["product_tmpl_id"]:
                    raise UserError(
                        _(
                            "You cannot move the attribute %(attribute)s from the product"
                            " %(product_src)s to the product %(product_dest)s.",
                            attribute=ptal.attribute_id.display_name,
                            product_src=ptal.product_tmpl_id.display_name,
                            product_dest=values["product_tmpl_id"],
                        )
                    )

        if "attribute_id" in values:
            for ptal in self:
                if ptal.attribute_id.id != values["attribute_id"]:
                    raise UserError(
                        _(
                            "On the product %(product)s you cannot transform the attribute"
                            " %(attribute_src)s into the attribute %(attribute_dest)s.",
                            product=ptal.product_tmpl_id.display_name,
                            attribute_src=ptal.attribute_id.display_name,
                            attribute_dest=values["attribute_id"],
                        )
                    )
        # Remove all values while archiving to make sure the line is clean if it
        # is ever activated again.
        if not values.get("active", True):
            values["value_ids"] = [Command.clear()]
        res = super().write(values)
        if "active" in values:
            self.env.flush_all()
            self.env["product.template"].invalidate_model(["attribute_line_ids"])
        # If coming from `create`, no need to update the values and the variants
        # before all lines are created.
        if self.env.context.get("update_product_template_attribute_values", True):
            self._update_product_template_attribute_values()
        return res

    def unlink(self):
        """Override to:
        - Archive the line if unlink is not possible.
        - Clean up related values and related variants.

        Archiving is typically needed when the line has values that can't be
        deleted because they are referenced elsewhere (on a variant that can't
        be deleted, on a sales order line, ...).
        """
        # Try to remove the values first to remove some potentially blocking
        # references, which typically works:
        # - For single value lines because the values are directly removed from
        #   the variants.
        # - For values that are present on variants that can be deleted.
        self.product_template_value_ids._only_active().unlink()
        # Keep a reference to the related templates before the deletion.
        templates = self.product_tmpl_id

        # A line whose values survived the call above -- archived rather than
        # deleted, because variants still carry them -- must be archived too,
        # which is the case this method's docstring describes but never reached.
        #
        # `product.template.attribute.value.attribute_line_id` is
        # `ondelete="cascade"`, so deleting the line takes those values with it
        # at the database level, without their `unlink()` override ever running.
        # The `product_variant_combination` rows go too, and the combination of
        # every variant still holding one silently *narrows*: a red/S variant
        # that could not be deleted starts reading as a plain "red" variant.
        # `_create_variant_ids` keys `existing_variants` on that combination, so
        # the leftover then matches the red variant the template now needs and
        # is reactivated in its place, carrying the stock, barcode and history
        # of a variant that described a configuration which no longer exists.
        #
        # Deleting the line is therefore only safe once nothing references its
        # values -- exactly what `unlink_where_possible` would have discovered
        # for itself if the cascade did not make the DELETE always succeed.
        self.env.flush_all()
        still_valued = self.filtered(lambda ptal: ptal.product_template_value_ids)
        # Now delete or archive the lines, attempting the batch as a whole and
        # splitting only on failure (see `unlink_where_possible`) rather than
        # opening a savepoint per line.
        ptal_to_archive = still_valued | unlink_where_possible(
            self - still_valued, lambda ptals: ptals._unlink_without_fallback()
        )
        ptal_to_archive.action_archive()  # only calls write if there are records
        # For archived lines `_update_product_template_attribute_values` is
        # implicitly called during the `write` above, but for products that used
        # unlinked lines `_create_variant_ids` has to be called manually.
        (templates - ptal_to_archive.product_tmpl_id)._create_variant_ids()
        return True

    def _unlink_without_fallback(self):
        """Delete outright, skipping the archive-on-failure handling above."""
        return super().unlink()

    def _update_product_template_attribute_values(self):
        """Create or unlink `product.template.attribute.value` for each line in
        `self` based on `value_ids`.

        The goal is to delete all values that are not in `value_ids`, to
        activate those in `value_ids` that are currently archived, and to create
        those in `value_ids` that didn't exist.

        This is a trick for the form view and for performance in general,
        because we don't want to generate in advance all possible values for all
        templates, but only those that will be selected.
        """
        ProductTemplateAttributeValue = self.env["product.template.attribute.value"]
        ptav_to_create = []
        ptav_to_unlink = ProductTemplateAttributeValue
        # Pool of re-usable archived values, resolved in one query for the whole
        # recordset instead of one `_read_group` per line. It is kept in step
        # with the loop below -- values archived at one step are added back,
        # values revived are taken out -- so a later line can still re-use a
        # value an earlier line archived, which is the only reason the query
        # used to sit inside the loop.
        archived_ptav_pool = self._pool_of_reusable_archived_values()
        for ptal in self:
            ptav_to_activate = ProductTemplateAttributeValue
            # Only this line's additions get archived at the end of the step;
            # `ptav_to_unlink` accumulates across lines for the final `unlink`,
            # and re-writing the whole accumulation on every line was quadratic
            # in the number of lines for no effect (the earlier ones are already
            # archived).
            ptav_to_deactivate = ProductTemplateAttributeValue
            remaining_pav = set(ptal.value_ids.ids)
            for ptav in ptal.product_template_value_ids:
                if ptav.product_attribute_value_id.id not in remaining_pav:
                    # Remove values that existed but don't exist anymore, but
                    # ignore those that are already archived because if they are
                    # archived it means they could not be deleted previously.
                    if ptav.ptav_active:
                        ptav_to_unlink += ptav
                        ptav_to_deactivate += ptav
                else:
                    # Activate corresponding values that are currently archived.
                    remaining_pav.remove(ptav.product_attribute_value_id.id)
                    if not ptav.ptav_active:
                        ptav_to_activate += ptav

            line_key = (ptal.product_tmpl_id.id, ptal.attribute_id.id)
            for pav_id in sorted(remaining_pav):
                ptav = archived_ptav_pool.pop((*line_key, pav_id), None)
                if ptav is None:
                    continue
                ptav.write({"ptav_active": True, "attribute_line_id": ptal.id})
                # If the value was marked for deletion, now keep it.
                ptav_to_unlink -= ptav
                ptav_to_deactivate -= ptav
                remaining_pav.remove(pav_id)

            remaining_pav = (
                self.env["product.attribute.value"].sudo().browse(sorted(remaining_pav))
            )
            # create values that didn't exist yet
            ptav_to_create.extend(
                {
                    "product_attribute_value_id": pav.id,
                    "attribute_line_id": ptal.id,
                    "price_extra": pav.default_extra_price,
                }
                for pav in remaining_pav
            )
            # Handle active at each step in case a following line might want to
            # re-use a value that was archived at a previous step.
            ptav_to_activate.write({"ptav_active": True})
            ptav_to_deactivate.write({"ptav_active": False})
            # Keep the pool in step with what this step just (de)activated, so
            # the batched lookup answers exactly what the per-line query did.
            for ptav in ptav_to_activate:
                archived_ptav_pool.pop(self._archived_value_key(ptav), None)
            for ptav in ptav_to_deactivate:
                archived_ptav_pool.setdefault(self._archived_value_key(ptav), ptav)
        if ptav_to_unlink:
            ptav_to_unlink.unlink()
        ProductTemplateAttributeValue.create(ptav_to_create)
        if self.env.context.get("create_product_product", True):
            self.product_tmpl_id._create_variant_ids()

    @api.model
    def _pool_of_reusable_archived_lines(self, vals_list):
        """Archived lines the rows of ``vals_list`` could revive, as
        ``{(template_id, attribute_id): [ptal, ...]}``.

        One query for the whole batch. Each list keeps the model's own order, so
        popping from the front picks the same line the per-row ``limit=1``
        search did, and consuming an entry is what stops two rows targeting the
        same (template, attribute) from reviving one line twice.
        """
        wanted = {
            (vals.get("product_tmpl_id"), vals.get("attribute_id"))
            for vals in vals_list
            if vals.get("product_tmpl_id") and vals.get("attribute_id")
        }
        if not wanted:
            return {}
        domain = Domain("active", "=", False) & Domain.OR(
            Domain("product_tmpl_id", "=", template_id)
            & Domain("attribute_id", "=", attribute_id)
            for template_id, attribute_id in wanted
        )
        pool = {}
        for ptal in self.search(domain):
            pool.setdefault((ptal.product_tmpl_id.id, ptal.attribute_id.id), []).append(
                ptal
            )
        return pool

    @api.model
    def _archived_value_key(self, ptav):
        """Pool key of a `product.template.attribute.value`: what identifies it
        as a re-usable slot for a line (template, attribute, attribute value).
        """
        return (
            ptav.product_tmpl_id.id,
            ptav.attribute_id.id,
            ptav.product_attribute_value_id.id,
        )

    def _pool_of_reusable_archived_values(self):
        """Archived `product.template.attribute.value` records that the lines in
        `self` could revive, as ``{(template_id, attribute_id, value_id): ptav}``.

        One query for the whole recordset. The candidate values are over-fetched
        (every value of every line, not just the ones that turn out to be
        missing) because narrowing per line is exactly what forced the query
        into the loop; entries that are never consulted cost nothing.

        Ordered by id and inserted with `setdefault`, so a duplicated
        (template, attribute, value) triple resolves to the lowest id -- stable,
        unlike the arbitrary aggregate order this replaces.
        """
        pairs = {(ptal.product_tmpl_id.id, ptal.attribute_id.id) for ptal in self}
        value_ids = self.value_ids.ids
        if not pairs or not value_ids:
            return {}
        domain = (
            Domain("ptav_active", "=", False)
            & Domain("product_attribute_value_id", "in", value_ids)
            & Domain.OR(
                Domain("product_tmpl_id", "=", template_id)
                & Domain("attribute_id", "=", attribute_id)
                for template_id, attribute_id in pairs
            )
        )
        pool = {}
        for ptav in self.env["product.template.attribute.value"].search(
            domain, order="id"
        ):
            pool.setdefault(self._archived_value_key(ptav), ptav)
        return pool

    def _without_no_variant_attributes(self):
        return self.filtered(
            lambda ptal: ptal.attribute_id.create_variant != "no_variant"
        )

    def _is_configurable(self):
        self.ensure_one()
        return (
            len(self.value_ids) >= 2
            or self.attribute_id.display_type == "multi"
            or self.value_ids.is_custom
        )

    @api.readonly
    def action_open_attribute_values(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Product Variant Values"),
            "res_model": "product.template.attribute.value",
            "view_mode": "list,form",
            "domain": [("id", "in", self.product_template_value_ids.ids)],
            "views": [
                (
                    self.env.ref(
                        "product.view_product_template_attribute_value_list"
                    ).id,
                    "list",
                ),
                (
                    self.env.ref(
                        "product.view_product_template_attribute_value_form"
                    ).id,
                    "form",
                ),
            ],
            "context": {
                "search_default_active": 1,
                "product_invisible": True,
            },
        }
