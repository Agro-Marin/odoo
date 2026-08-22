import datetime
import logging
from ast import literal_eval
from collections import defaultdict
from typing import Any

from odoo import api, fields, models, modules, tools
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import SQL

_logger = logging.getLogger("odoo.addons.product.merge")


def _can_commit() -> bool:
    """Whether committing the current transaction is acceptable.

    The automatic sweep commits group by group so a failure halfway through
    keeps the merges already done. A test cursor refuses to commit at all, so
    the sweep asks first -- same guard as ``account.move.send._can_commit``.
    """
    return not (tools.config["test_enable"] or modules.module.current_test)


class ProductMergeLine(models.TransientModel):
    _name = "product.merge.line"
    _description = "Merge Product Line"
    _order = "min_id asc"

    wizard_id = fields.Many2one(comodel_name="product.merge.wizard", string="Wizard")
    min_id = fields.Integer(string="MinID")
    aggr_ids = fields.Char(string="Ids", required=True)


class ProductMergeWizard(models.TransientModel):
    """Merge duplicated products, the way ``base.partner.merge.automatic.wizard``
    merges duplicated contacts.

    A product is two records, not one: the ``product.template`` the user sees
    and the ``product.product`` variants every document actually points at. So
    a merge runs at both levels -- each source variant is paired with the
    destination variant carrying the same attribute combination, and the
    documents are re-pointed variant by variant before the templates
    themselves are merged and the sources deleted.

    What the engine below deliberately does not touch is the *structure* of the
    destination: attribute lines, their values and the variants they generate
    stay as they are (see ``_get_excluded_template_tables``). Re-pointing an
    attribute line at the destination would regenerate its variants underneath
    the merge that is still running.

    Two consequences worth knowing before merging:

    * The destination wins every field it *answers for*, and answering means a
      truthy value. A deliberate 0.00 sales price or an unticked "Can be Sold"
      reads as an empty field, so a source's value lands there. Inherited from
      the contact merge, which fills gaps the same way.
    * A source variant whose attribute combination the destination does not
      already have is refused rather than created -- notably for templates with
      dynamic attributes, where the destination only holds the combinations
      somebody has already ordered. Configure the missing combination on the
      destination first, then merge.
    """

    _name = "product.merge.wizard"
    _inherit = ["merge.mixin"]
    _description = "Merge Products Wizard"

    # For safety: the same cap the contact merge applies, for the same reason
    # -- a merge is not reversible, and a wide selection is usually a mistake.
    _MAX_MERGE_SIZE = 3

    _GROUPBY_ALLOWED_FIELDS = frozenset(
        {"name", "default_code", "barcode", "categ_id", "type", "uom_id"}
    )
    # `barcode` is not stored on the template: it is a computed proxy over the
    # variant's own column, so grouping on it means joining the variants in.
    _VARIANT_GROUPBY_FIELDS = frozenset({"barcode"})
    _CASE_INSENSITIVE_GROUPBY_FIELDS = frozenset({"name", "default_code", "barcode"})

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        active_ids = self.env.context.get("active_ids")
        active_model = self.env.context.get("active_model")
        if (
            active_model not in ("product.template", "product.product")
            or not active_ids
        ):
            return res

        if active_model == "product.product":
            # Variants are merged with their template, never on their own: a
            # variant is regenerated from the attribute lines of its template,
            # so a variant-only merge would be undone by the next regeneration.
            templates = (
                self.env["product.product"]
                .browse(active_ids)
                .with_context(active_test=False)
                .product_tmpl_id
            )
        else:
            templates = self.env["product.template"].browse(active_ids)

        if "state" in fields:
            res["state"] = "selection"
        if "product_tmpl_ids" in fields:
            res["product_tmpl_ids"] = [Command.set(templates.ids)]
        if "dst_product_tmpl_id" in fields and templates:
            res["dst_product_tmpl_id"] = self._get_ordered_templates(templates.ids)[
                -1
            ].id
        return res

    group_by_name = fields.Boolean(string="Name")
    group_by_default_code = fields.Boolean(string="Internal Reference")
    group_by_barcode = fields.Boolean(string="Barcode")
    group_by_categ_id = fields.Boolean(string="Product Category")
    group_by_type = fields.Boolean(string="Product Type")
    group_by_uom_id = fields.Boolean(string="Unit")

    state = fields.Selection(
        selection=[
            ("option", "Option"),
            ("selection", "Selection"),
            ("finished", "Finished"),
        ],
        string="State",
        readonly=True,
        required=True,
        default="option",
    )

    number_group = fields.Integer(string="Group of Products", readonly=True)
    maximum_group = fields.Integer(string="Maximum of Group of Products")
    current_line_id = fields.Many2one(
        comodel_name="product.merge.line", string="Current Line"
    )
    line_ids = fields.One2many(
        comodel_name="product.merge.line", inverse_name="wizard_id", string="Lines"
    )
    product_tmpl_ids = fields.Many2many(
        comodel_name="product.template",
        string="Products",
        context={"active_test": False},
    )
    dst_product_tmpl_id = fields.Many2one(
        comodel_name="product.template", string="Destination Product"
    )

    exclude_journal_item = fields.Boolean(
        string="Journal Items associated to the product"
    )

    # -- merge policy ---------------------------------------------------------

    def _get_excluded_merge_tables(self, model: str) -> set[str]:
        tables = super()._get_excluded_merge_tables(model)
        if model == "product.template":
            return tables | self._get_excluded_template_tables()
        if model == "product.product":
            return tables | self._get_excluded_variant_tables()
        return tables

    def _get_excluded_template_tables(self) -> set[str]:
        """Template rows that must die with the source instead of moving.

        Everything here describes how the source is *built* rather than what
        happened to it: its variants (merged pairwise beforehand), its
        attribute lines and the template-level values those lines generate.
        Re-pointing any of them at the destination would either duplicate its
        attributes or trigger a variant regeneration mid-merge.
        """
        return {
            "product_product",
            # A stored compute (`product.attribute.product_tmpl_ids`) over the
            # attribute lines: re-pointing it writes a value the compute did
            # not produce, and the destination's rows are already right.
            "product_attribute_product_template_rel",
            "product_template_attribute_line",
            "product_template_attribute_value",
            "product_template_attribute_exclusion",
        }

    def _get_excluded_variant_tables(self) -> set[str]:
        """Variant rows that must die with the source variant.

        ``product_variant_combination`` links a variant to the
        ``product.template.attribute.value`` records of *its own* template.
        Those ids differ from the destination's even when the two variants
        stand for the same combination, so re-pointing the rows would hand the
        destination variant attribute values belonging to a deleted template.
        """
        return {"product_variant_combination"}

    def _get_fields_summable(self) -> list[str]:
        """Template fields added up instead of being taken from one side."""
        return []

    def _get_fields_summable_variant(self) -> list[str]:
        """Variant fields added up instead of being taken from one side."""
        return []

    def _get_fields_excluded_value(self) -> tuple[str, ...]:
        """Destination fields no source is allowed to overwrite.

        ``company_id`` is the one that matters. ``_check_mergeable`` lets a
        product scoped to one company be merged into a product shared between
        all of them, precisely because the shared destination stays usable by
        everybody -- and the generic value merge would then take the source's
        company, since the destination leaves the field empty, and hand every
        other company's documents a product they cannot use. The destination's
        own scope is always the right one: in the only other case the check
        allows, source and destination already share it.
        """
        return ("company_id",)

    def _get_fields_deferred_variant(self) -> tuple[str, ...]:
        """Variant fields written only once the sources are gone.

        ``barcode`` is checked for uniqueness per company, so the destination
        cannot adopt a source's barcode while that source still holds it.
        """
        return ("barcode",)

    def _get_ordered_templates(self, template_ids: list[int]) -> models.BaseModel:
        """Order candidates so the last one is the natural destination: the
        oldest still-active product, as the contact merge does."""
        return (
            self.env["product.template"]
            .browse(template_ids)
            .sorted(
                key=lambda template: (
                    not template.active,
                    (template.create_date or datetime.datetime(1970, 1, 1)),
                ),
                reverse=True,
            )
        )

    def _check_mergeable(
        self, src_templates: models.BaseModel, dst_template: models.BaseModel
    ) -> None:
        templates = src_templates + dst_template

        if len(set(templates.mapped("type"))) > 1:
            raise UserError(
                self.env._(
                    "You cannot merge products of different types (%(types)s).",
                    types=", ".join(sorted(set(templates.mapped("type")))),
                )
            )

        if len(templates.uom_id) > 1:
            raise UserError(
                self.env._(
                    "You cannot merge products measured in different units "
                    "(%(units)s). Every quantity already recorded against the "
                    "source products would silently change meaning.",
                    units=", ".join(sorted(templates.uom_id.mapped("name"))),
                )
            )

        if dst_template.company_id:
            other_company = src_templates.filtered(
                lambda template: template.company_id != dst_template.company_id
            )
            if other_company:
                raise UserError(
                    self.env._(
                        "The destination product belongs to %(company)s while "
                        "%(products)s do not. Merge into the product shared "
                        "between companies instead, or the documents of the "
                        "other companies would end up pointing at a product "
                        "they cannot use.",
                        company=dst_template.company_id.display_name,
                        products=", ".join(other_company.mapped("display_name")),
                    )
                )

    def _get_variant_pairs(
        self, src_template: models.BaseModel, dst_template: models.BaseModel
    ) -> dict[models.BaseModel, models.BaseModel]:
        """Pair each source variant with the destination variant standing for
        the same attribute combination.

        Two templates describe a combination with different
        ``product.template.attribute.value`` records -- those are template
        scoped -- so the pairing is done on the ``product.attribute.value``
        records behind them, which are shared.
        """

        def combination(variant: models.BaseModel) -> frozenset[int]:
            values = variant.product_template_attribute_value_ids
            return frozenset(values.product_attribute_value_id.ids)

        dst_variants = dst_template.with_context(active_test=False).product_variant_ids
        dst_by_combination = {combination(variant): variant for variant in dst_variants}

        pairs = {}
        for variant in src_template.with_context(active_test=False).product_variant_ids:
            counterpart = dst_by_combination.get(combination(variant))
            if not counterpart:
                raise UserError(
                    self.env._(
                        "%(product)s has no counterpart among the variants of "
                        "%(destination)s. Products can only be merged when "
                        "every variant of the source matches one of the "
                        "destination on the same attribute values.",
                        product=variant.display_name,
                        destination=dst_template.display_name,
                    )
                )
            pairs[variant] = counterpart
        return pairs

    def _merge_dependent_records(
        self,
        src_templates: models.BaseModel,
        dst_template: models.BaseModel,
        src_variants_by_dst: dict[models.BaseModel, models.BaseModel],
    ) -> None:
        """Hook for records that cannot simply be re-pointed.

        A module holding one row per product under a uniqueness constraint --
        a stock quant per (product, location), a reordering rule per
        (product, warehouse) -- must fold the source's row into the
        destination's here, before the generic re-pointing runs and resolves
        the collision by deleting the row instead. ``loyalty`` does exactly
        this for the contact merge.

        Those rows hang off the *variant*, not the template, which is why the
        pairing is passed in: ``src_variants_by_dst`` maps each destination
        variant to the source variants standing for the same combination.
        """

    # -- merge ----------------------------------------------------------------

    @api.model
    def _update_foreign_keys(
        self, src_templates: models.BaseModel, dst_template: models.BaseModel
    ) -> None:
        self._update_foreign_keys_generic(
            "product.template", src_templates, dst_template
        )

    @api.model
    def _update_reference_fields(
        self, src_templates: models.BaseModel, dst_template: models.BaseModel
    ) -> None:
        self._update_reference_fields_generic(
            "product.template", src_templates, dst_template
        )

    @api.model
    def _update_values(
        self, src_templates: models.BaseModel, dst_template: models.BaseModel
    ) -> None:
        self._update_values_generic(
            src_templates,
            dst_template,
            summable_fields=self._get_fields_summable(),
            excluded_fields=self._get_fields_excluded_value(),
        )

    @api.model
    def _update_variant_foreign_keys(
        self, src_variants: models.BaseModel, dst_variant: models.BaseModel
    ) -> None:
        self._update_foreign_keys_generic("product.product", src_variants, dst_variant)

    @api.model
    def _update_variant_reference_fields(
        self, src_variants: models.BaseModel, dst_variant: models.BaseModel
    ) -> None:
        self._update_reference_fields_generic(
            "product.product", src_variants, dst_variant
        )

    @api.model
    def _update_variant_values(
        self, src_variants: models.BaseModel, dst_variant: models.BaseModel
    ) -> dict[str, Any]:
        return self._update_values_generic(
            src_variants,
            dst_variant,
            summable_fields=self._get_fields_summable_variant(),
            deferred_fields=self._get_fields_deferred_variant(),
            # `product.product` delegates 40 fields to its template
            # (`_inherits`), so a write here reaches the template too -- the
            # company exclusion has to hold on this side as well.
            excluded_fields=self._get_fields_excluded_value(),
        )

    def _merge(
        self,
        product_tmpl_ids: list[int],
        dst_template: models.BaseModel | None = None,
    ) -> None:
        templates = self.env["product.template"].browse(product_tmpl_ids).exists()
        if len(templates) < 2:
            return

        if len(templates) > self._MAX_MERGE_SIZE:
            raise UserError(
                self.env._(
                    "For safety reasons, you cannot merge more than %(maximum)s "
                    "products together. You can re-open the wizard several "
                    "times if needed.",
                    maximum=self._MAX_MERGE_SIZE,
                )
            )

        if dst_template and dst_template in templates:
            src_templates = templates - dst_template
        else:
            ordered_templates = self._get_ordered_templates(templates.ids)
            dst_template = ordered_templates[-1]
            src_templates = ordered_templates[:-1]
        _logger.info("dst_template: %s", dst_template.id)

        self._check_mergeable(src_templates, dst_template)

        # Pair every variant before anything is written: a template whose
        # combinations do not line up must abort the merge, not half of it.
        # Sources are grouped per destination variant rather than handled one
        # at a time, so merging three products reads the same way at the
        # variant level as it does at the template level -- one destination,
        # every source it absorbs.
        src_variants_by_dst = defaultdict(lambda: self.env["product.product"])
        for src_template in src_templates:
            pairs = self._get_variant_pairs(src_template, dst_template)
            for src_variant, dst_variant in pairs.items():
                src_variants_by_dst[dst_variant] |= src_variant

        self._merge_dependent_records(src_templates, dst_template, src_variants_by_dst)

        deferred_variant_values = {}
        for dst_variant, src_variants in src_variants_by_dst.items():
            self._update_variant_foreign_keys(src_variants, dst_variant)
            self._update_variant_reference_fields(src_variants, dst_variant)
            deferred_variant_values[dst_variant] = self._update_variant_values(
                src_variants, dst_variant
            )

        self._update_foreign_keys(src_templates, dst_template)
        self._update_reference_fields(src_templates, dst_template)
        self._update_values(src_templates, dst_template)

        self._log_merge_operation(src_templates, dst_template)

        src_variants = self.env["product.product"].union(*src_variants_by_dst.values())
        # Variants first, through the ORM, so every module's own `unlink`
        # checks still run; a template left without variants goes with them.
        src_variants.sudo().unlink()
        src_templates.exists().sudo().unlink()

        for dst_variant, values in deferred_variant_values.items():
            if values:
                dst_variant.write(values)

    def _log_merge_operation(
        self, src_templates: models.BaseModel, dst_template: models.BaseModel
    ) -> None:
        _logger.info(
            "(uid = %s) merged the products %r into %s",
            self.env.uid,
            src_templates.ids,
            dst_template.id,
        )
        dst_template.message_post(
            body=self.env._(
                "Merged with the following products: %s",
                [
                    self.env._(
                        "%(product)s (ID %(id)s)",
                        product=template.display_name,
                        id=template.id,
                    )
                    for template in src_templates
                ],
            )
        )

    # -- duplicate search -----------------------------------------------------

    @api.model
    def _generate_query(self, fields: list[str], maximum_group: int = 100) -> SQL:
        template = SQL.identifier("template")
        variant = SQL.identifier("variant")

        group_expressions = []
        filters = []
        for field in fields:
            if field not in self._GROUPBY_ALLOWED_FIELDS:
                raise ValueError(f"Field {field!r} is not allowed in merge grouping")
            alias = variant if field in self._VARIANT_GROUPBY_FIELDS else template
            column = SQL("%s.%s", alias, SQL.identifier(field))
            if field == "name":
                # A translated field is a jsonb column, and `en_US` is the one
                # key every term carries: it is the source term itself.
                expression = SQL(
                    "lower(COALESCE(%s ->> %s, %s ->> 'en_US'))",
                    column,
                    self.env.lang or "en_US",
                    column,
                )
            elif field in self._CASE_INSENSITIVE_GROUPBY_FIELDS:
                expression = SQL("lower(%s)", column)
            else:
                expression = column
            group_expressions.append(expression)
            # Two products are not duplicates for both lacking a category:
            # NULL groups with NULL in SQL, so every criterion excludes the
            # rows that do not answer it. `type` and `uom_id` are required, so
            # the filter only ever bites on the optional ones.
            filters.append(SQL("%s IS NOT NULL", expression))

        parts = [
            SQL("SELECT min(%s.id), array_agg(DISTINCT %s.id)", template, template),
            SQL("FROM product_template AS %s", template),
        ]
        if not self._VARIANT_GROUPBY_FIELDS.isdisjoint(fields):
            parts.append(
                SQL(
                    "JOIN product_product AS %s ON %s.product_tmpl_id = %s.id",
                    variant,
                    variant,
                    template,
                )
            )
        if filters:
            parts.append(SQL("WHERE %s", SQL(" AND ").join(filters)))
        parts.extend(
            [
                SQL("GROUP BY %s", SQL(", ").join(group_expressions)),
                # DISTINCT, because the variant join multiplies a template by
                # its variant count: a single template with two variants
                # sharing a barcode is not a duplicate.
                SQL("HAVING COUNT(DISTINCT %s.id) >= 2", template),
                SQL("ORDER BY min(%s.id)", template),
            ]
        )
        if maximum_group:
            parts.append(SQL("LIMIT %s", maximum_group))

        return SQL(" ").join(parts)

    def _get_selected_groupby(self) -> list[str]:
        group_by_prefix = "group_by_"
        groups = [
            field_name.removeprefix(group_by_prefix)
            for field_name in self._fields
            if field_name.startswith(group_by_prefix) and self[field_name]
        ]

        if not groups:
            raise UserError(
                self.env._("You have to specify a filter for your selection.")
            )

        return groups

    def _get_exclusion_models(self) -> dict[str, str]:
        """Models whose presence takes a group of duplicates out of the run."""
        model_mapping = {}
        if "account.move.line" in self.env and self.exclude_journal_item:
            model_mapping["account.move.line"] = "product_id"
        return model_mapping

    @api.model
    def _is_used_in(self, template_ids: list[int], models: dict[str, str]) -> bool:
        variant_ids = (
            self.env["product.template"]
            .browse(template_ids)
            .with_context(active_test=False)
            .product_variant_ids.ids
        )
        return any(
            self.env[model].search_count([(field, "in", variant_ids)])
            for model, field in models.items()
        )

    def _process_query(self, query: SQL) -> None:
        self.ensure_one()
        model_mapping = self._get_exclusion_models()

        # The duplicate search reads the tables directly, and two of the
        # columns it groups on (`default_code`, and `barcode` on the variant)
        # are filled by stored computes. Without a flush they are still in the
        # cache and the search reports no duplicate at all.
        self.env.flush_all()
        self.env.cr.execute(query)  # noqa: E8501  built by _generate_query

        groups = self.env.cr.fetchall()
        all_ids = [tmpl_id for _, aggr_ids in groups for tmpl_id in aggr_ids]
        accessible = self.env["product.template"].search([("id", "in", all_ids)])
        accessible_set = set(accessible.ids)

        counter = 0
        for min_id, aggr_ids in groups:
            template_ids = [
                tmpl_id for tmpl_id in aggr_ids if tmpl_id in accessible_set
            ]
            if len(template_ids) < 2:
                continue

            if model_mapping and self._is_used_in(template_ids, model_mapping):
                continue

            self.env["product.merge.line"].create(
                {
                    "wizard_id": self.id,
                    "min_id": min_id,
                    "aggr_ids": template_ids,
                }
            )
            counter += 1

        self.write({"state": "selection", "number_group": counter})

        _logger.info("counter: %s", counter)

    # -- screens --------------------------------------------------------------

    def _action_next_screen(self) -> dict[str, Any]:
        self.env.invalidate_all()
        values = {}
        if self.line_ids:
            current_line = self.line_ids[0]
            current_template_ids = literal_eval(current_line.aggr_ids)
            values.update(
                {
                    "current_line_id": current_line.id,
                    "product_tmpl_ids": [Command.set(current_template_ids)],
                    "dst_product_tmpl_id": self._get_ordered_templates(
                        current_template_ids
                    )[-1].id,
                    "state": "selection",
                }
            )
        else:
            values.update(
                {
                    "current_line_id": False,
                    "product_tmpl_ids": [],
                    "state": "finished",
                }
            )

        self.write(values)

        return self._action_reopen()

    def _action_reopen(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_skip(self) -> dict[str, Any]:
        if self.current_line_id:
            self.current_line_id.unlink()
        return self._action_next_screen()

    def action_merge(self) -> dict[str, Any]:
        self.ensure_one()
        if not self.product_tmpl_ids:
            self.write({"state": "finished"})
            return self._action_reopen()

        if len(self.product_tmpl_ids) < 2:
            raise UserError(
                self.env._("Select at least two products to merge them together.")
            )

        self._merge(self.product_tmpl_ids.ids, self.dst_product_tmpl_id)

        if self.current_line_id:
            self.current_line_id.unlink()

        return self._action_next_screen()

    def action_start_manual_process(self) -> dict[str, Any]:
        self.ensure_one()
        groups = self._get_selected_groupby()
        query = self._generate_query(groups, self.maximum_group)
        self._process_query(query)
        return self._action_next_screen()

    def action_start_automatic_process(self) -> dict[str, Any]:
        self.ensure_one()
        self.action_start_manual_process()
        self.env.invalidate_all()

        for line in self.line_ids:
            template_ids = literal_eval(line.aggr_ids)
            try:
                # A group the policy refuses -- too many duplicates at once,
                # mismatched units, variants that do not line up -- is skipped
                # rather than fatal: the sweep is the whole point, and its line
                # survives for the user to settle by hand afterwards. The
                # savepoint is for an override of `_merge_dependent_records`
                # that raises after writing something.
                with self.env.cr.savepoint():
                    self._merge(template_ids)
            except UserError as error:
                _logger.warning(
                    "Skipping the merge of products %s: %s", template_ids, error
                )
                continue
            line.unlink()
            if _can_commit():
                self.env.cr.commit()

        # Whatever the sweep refused is still on the wizard, so hand the user
        # the first of those rather than the "nothing left to do" screen.
        return self._action_next_screen()
