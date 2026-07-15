import re
from collections import defaultdict

from odoo import api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import OrderedSet, float_compare, groupby
from odoo.tools.image import is_image_size_above
from odoo.tools.misc import unique
from odoo.tools.sql import SQL

# Resolutions (px) for which resized image / image_variant fields exist.
IMAGE_SIZES = (1920, 1024, 512, 256, 128)


class ProductProduct(models.Model):
    _name = "product.product"
    _description = "Product Variant"
    _inherits = {"product.template": "product_tmpl_id"}
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "default_code, name, id"
    _check_company_domain = models.check_company_domain_parent_of

    # price_extra: catalog extra value only, sum of variant extra attributes
    price_extra = fields.Float(
        string="Variant Price Extra",
        min_display_digits="Product Price",
        compute="_compute_product_price_extra",
        help="This is the sum of the extra price of all attributes",
    )
    # lst_price: catalog value + extra, context dependent (uom)
    lst_price = fields.Float(
        string="Public Price",
        min_display_digits="Product Price",
        compute="_compute_product_lst_price",
        inverse="_set_product_lst_price",
        help="The sale price is managed from the product template. Click on the 'Configure Variants' button to set the extra attribute prices.",
    )

    default_code = fields.Char(
        string="Internal Reference",
        index=True,
    )
    code = fields.Char(
        string="Reference",
        compute="_compute_product_code",
    )
    partner_ref = fields.Char(
        string="Customer Ref",
        compute="_compute_partner_ref",
    )

    active = fields.Boolean(
        string="Active",
        default=True,
        help="If unchecked, it will allow you to hide the product without removing it.",
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        required=True,
        bypass_search_access=True,
        ondelete="cascade",
        index=True,
    )
    barcode = fields.Char(
        string="Barcode",
        copy=False,
        index="btree_not_null",
        help="International Article Number used for product identification.",
    )
    product_uom_ids = fields.One2many(
        comodel_name="product.uom",
        inverse_name="product_id",
        string="Unit Barcode",
    )
    product_template_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        relation="product_variant_combination",
        string="Attribute Values",
        ondelete="restrict",
    )
    product_template_variant_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        relation="product_variant_combination",
        string="Variant Values",
        domain=[("attribute_line_id.value_count", ">", 1)],
        ondelete="restrict",
    )
    import_attribute_values = fields.Char(
        string="Product Values",
        compute="_compute_import_attribute_values",
        inverse="_inverse_import_attribute_values",
        store=False,
        copy=False,
    )
    combination_indices = fields.Char(
        compute="_compute_combination_indices",
        store=True,
        index=True,
    )
    is_product_variant = fields.Boolean(
        compute="_compute_is_product_variant",
    )

    standard_price = fields.Float(
        string="Cost",
        min_display_digits="Product Price",
        company_dependent=True,
        groups="base.group_user",
        help="""Value of the product (automatically computed in AVCO).
        Used to value the product when the purchase cost is not known (e.g. inventory adjustment).
        Used to compute margins on sale orders.""",
    )
    volume = fields.Float(
        string="Volume",
        digits="Volume",
    )
    weight = fields.Float(
        string="Weight",
        digits="Stock Weight",
    )

    pricelist_rule_ids = fields.One2many(
        comodel_name="product.pricelist.item",
        inverse_name="product_id",
        string="Pricelist Rules",
        compute="_compute_pricelist_rule_ids",
        inverse="_inverse_pricelist_rule_ids",
        readonly=False,
    )

    product_document_ids = fields.One2many(
        comodel_name="product.document",
        inverse_name="res_id",
        string="Documents",
        domain=lambda self: [("res_model", "=", self._name)],
    )
    product_document_count = fields.Integer(
        string="Documents Count",
        compute="_compute_product_document_count",
    )

    additional_product_tag_ids = fields.Many2many(
        comodel_name="product.tag",
        relation="product_tag_product_product_rel",
        string="Variant Tags",
        domain="[('id', 'not in', product_tag_ids)]",
    )
    all_product_tag_ids = fields.Many2many(
        comodel_name="product.tag",
        compute="_compute_all_product_tag_ids",
        search="_search_all_product_tag_ids",
    )

    # all image fields are base64 encoded and PIL-supported

    # all image_variant fields are technical and should not be displayed to the user
    image_variant_1920 = fields.Image(
        string="Variant Image",
        max_width=1920,
        max_height=1920,
    )

    # resized fields stored (as attachment) for performance
    image_variant_1024 = fields.Image(
        related="image_variant_1920",
        string="Variant Image 1024",
        max_width=1024,
        max_height=1024,
        store=True,
    )
    image_variant_512 = fields.Image(
        related="image_variant_1920",
        string="Variant Image 512",
        max_width=512,
        max_height=512,
        store=True,
    )
    image_variant_256 = fields.Image(
        related="image_variant_1920",
        string="Variant Image 256",
        max_width=256,
        max_height=256,
        store=True,
    )
    image_variant_128 = fields.Image(
        related="image_variant_1920",
        string="Variant Image 128",
        max_width=128,
        max_height=128,
        store=True,
    )
    can_image_variant_1024_be_zoomed = fields.Boolean(
        string="Can Variant Image 1024 be zoomed",
        compute="_compute_can_image_variant_1024_be_zoomed",
        store=True,
    )

    # Computed fields that are used to create a fallback to the template if
    # necessary, it's recommended to display those fields to the user.
    image_1920 = fields.Image(
        string="Image",
        compute="_compute_image_1920",
        inverse="_set_image_1920",
    )
    image_1024 = fields.Image(string="Image 1024", compute="_compute_image_1024")
    image_512 = fields.Image(string="Image 512", compute="_compute_image_512")
    image_256 = fields.Image(string="Image 256", compute="_compute_image_256")
    image_128 = fields.Image(string="Image 128", compute="_compute_image_128")
    can_image_1024_be_zoomed = fields.Boolean(
        string="Can Image 1024 be zoomed",
        compute="_compute_can_image_1024_be_zoomed",
    )
    write_date = fields.Datetime(
        compute="_compute_write_date",
        store=True,
    )

    # Ensure there is at most one active variant for each combination.
    # There could be no variant for a combination if using dynamic attributes.
    _combination_unique = models.UniqueIndex(
        "(product_tmpl_id, combination_indices) WHERE active IS TRUE",
    )

    is_favorite = fields.Boolean(
        related="product_tmpl_id.is_favorite",
        store=True,
        readonly=False,
    )
    _is_favorite_index = models.Index("(is_favorite) WHERE is_favorite IS TRUE")
    is_in_selected_section_of_order = fields.Boolean(
        search="_search_is_in_selected_section_of_order",
    )

    @api.constrains("barcode")
    def _check_barcode_uniqueness(self):
        """With GS1 nomenclature, products and packagings use the same pattern. Therefore, we need
        to ensure the uniqueness between products' barcodes and packagings' ones
        """
        # Barcodes should only be unique within a company
        self_ctx = self.with_context(skip_preprocess_gs1=True)
        for company_id, barcodes_within_company in self_ctx._get_barcodes_by_company():
            self_ctx._check_duplicated_product_barcodes(
                barcodes_within_company,
                company_id,
            )
            self_ctx._check_duplicated_packaging_barcodes(
                barcodes_within_company,
                company_id,
            )

    @api.constrains("company_id")
    def _check_company_id(self):
        combo_items = (
            self.env["product.combo.item"]
            .sudo()
            .search([("product_id", "in", self.ids)])
        )
        combo_items._check_company(fnames=["product_id"])

    @api.constrains("standard_price")
    def _check_standard_price(self):
        # `_onchange_standard_price` only gives UI feedback; a negative cost
        # written through ORM / import / server actions would otherwise reach
        # AVCO valuation and sale-margin computation unchecked.
        for product in self:
            if product.standard_price < 0:
                raise ValidationError(
                    self.env._("The cost of a product can't be negative."),
                )

    def _inverse_import_attribute_values(self):
        raise UserError(
            self.env._("This field can only be used to import products."),
        )

    @api.depends("product_template_attribute_value_ids")
    def _compute_import_attribute_values(self):
        for product in self:
            product.import_attribute_values = ",".join(
                sorted(
                    f"{ptav.attribute_line_id.attribute_id.name}:{ptav.product_attribute_value_id.name}"
                    for ptav in product.product_template_attribute_value_ids
                )
            )

    def _load_records_write(self, values):
        import_attribute_values = values.get("import_attribute_values", "")
        if not import_attribute_values:
            return super()._load_records_write(values)

        def split(values):
            return {
                tuple(part.strip() for part in attr.split(":"))
                for attr in values.split(",")
            }

        attribute_values = split(import_attribute_values)
        existing_values = split(self.import_attribute_values)

        if attribute_values != existing_values:
            raise ValidationError(
                self.env._(
                    'The existing product has different attribute values. "%(imported_values)s" is not equivalent to "%(existing_values)s" for "%(external_id)s", "%(id)s"',
                    imported_values=import_attribute_values,
                    existing_values=self.import_attribute_values,
                    external_id=self.get_external_id()[self.id],
                    id=self.id,
                )
            )

        # Keep only truthy values (import_attribute_values, guaranteed truthy by
        # the early return above, is always dropped). During an attribute-value
        # import an empty cell must not overwrite the matched product's existing
        # value. Known limitation: a cell holding an explicit falsy value (0, "")
        # is indistinguishable from an empty cell here, so it is not written.
        values = {
            key: val
            for key, val in values.items()
            if val and key != "import_attribute_values"
        }

        return super()._load_records_write(values)

    def _parse_import_attribute_values(self, raw):
        """Parse an ``"Attribute:Value,Attribute2:Value2"`` import string into a
        list of ``(attribute_name, value_name)`` tuples (both stripped).

        Validates the format and rejects a repeated attribute within the same
        row. Centralizes what used to be three independent, hand-synchronized
        parses in ``_load_records_create``.
        """
        parsed = []
        seen_attributes = set()
        for token in raw.split(","):
            attribute_name, value_name = (
                token.split(":", 1) if ":" in token else (None, token)
            )
            attribute_name = attribute_name and attribute_name.strip()
            value_name = value_name.strip()
            if not attribute_name:
                raise ValueError(
                    self.env._(
                        "Unable to import products with attribute value without attribute name (defined as: attribute:value): %s",
                        raw,
                    )
                )
            if attribute_name in seen_attributes:
                raise ValueError(
                    self.env._(
                        "It is not possible to import different values for the same attribute: %s",
                        raw,
                    )
                )
            seen_attributes.add(attribute_name)
            parsed.append((attribute_name, value_name))
        return parsed

    def _load_records_create(self, data_list):
        with_import_values = [
            vals for vals in data_list if vals.get("import_attribute_values")
        ]
        without_import_values = [
            vals for vals in data_list if not vals.get("import_attribute_values")
        ]
        if not with_import_values:
            return super()._load_records_create(data_list)

        imported_product = super()._load_records_create(without_import_values)

        for vals in with_import_values:
            vals["name"] = (vals.get("name") or "").strip()
            if not vals["name"] and not vals.get("product_tmpl_id"):
                raise ValueError(
                    self.env._(
                        "Unable to import products with attribute values but without name of product set"
                    )
                )

        # sudo + context shared by every resolution phase below. Attribute /
        # template / PTAL / PTAV lookups all run through this env; only the raw
        # string parsing stays on `self` (for its access-checked error _()).
        contexted = self.sudo().with_context(
            create_product_product=False,
            update_product_template_attribute_values=True,
        )

        # Parse each row's "attribute:value,..." string exactly once and reuse
        # it across attribute/value creation, PTAL creation and PTAV resolution.
        parsed_by_vals = {
            id(vals): self._parse_import_attribute_values(
                vals["import_attribute_values"]
            )
            for vals in with_import_values
        }

        # Resolve (creating on demand) the attribute values, templates, and the
        # template-attribute-values the imported variants will point at. The
        # phases are ordered: default_values must be read *before* the useless
        # placeholder products are pruned, since it reads their field values.
        pa_pav_records = contexted._import_resolve_attribute_values(
            with_import_values, parsed_by_vals
        )
        id2template, name2template, product_templates, created_templates = (
            contexted._import_resolve_templates(with_import_values)
        )

        field_names = list(with_import_values[0])
        default_values = {
            values["product_tmpl_id"][0]: values
            for values in (
                product_templates.product_variant_id
                + created_templates.product_variant_id
            ).read(fields=["product_tmpl_id"] + field_names)
        }

        # Remove the useless product created with each product template. It has
        # no attribute value; it should not exist because we created variants.
        useless_products = contexted.env["product.product"].search(
            Domain("product_tmpl_id", "in", id2template.keys())
            & Domain("product_template_attribute_value_ids", "=", False)
        )
        useless_products._unlink_or_archive()

        template_value_to_ptav = contexted._import_resolve_ptavs(
            with_import_values,
            parsed_by_vals,
            id2template,
            name2template,
            pa_pav_records,
        )

        # Rewrite each row into a plain create dict: resolve the template id,
        # translate parsed attributes into ptav ids, and fall back to the
        # template's default value for any empty imported cell.
        for vals in with_import_values:
            name = vals.pop("name")
            if not vals.get("product_tmpl_id"):
                vals["product_tmpl_id"] = name2template[name].id

            parsed = parsed_by_vals[id(vals)]
            vals.pop("import_attribute_values")
            vals["product_template_attribute_value_ids"] = [
                template_value_to_ptav[
                    vals["product_tmpl_id"],
                    pa_pav_records[attribute_name, value_name].id,
                ].id
                for attribute_name, value_name in parsed
            ]

        new_data_list = [
            {
                key: value or default_values[vals["product_tmpl_id"]].get(key, False)
                for key, value in vals.items()
                if key not in ("import_attribute_values", "id")
            }
            for vals in with_import_values
        ]
        products = super()._load_records_create(new_data_list)

        return imported_product.exists() + products

    def _import_resolve_attribute_values(self, with_import_values, parsed_by_vals):
        """Resolve every ``(attribute_name, value_name)`` pair referenced by the
        imported rows into a ``product.attribute.value`` record, creating the
        missing attributes (as dynamic) and values on demand.

        :return: ``{(attribute_name, value_name): product.attribute.value}``
        """
        PA = self.env["product.attribute"]
        PAV = self.env["product.attribute.value"]

        attribute_to_values = defaultdict(OrderedSet)  # attribute_name => {value_name}
        for vals in with_import_values:
            for attribute_name, value_name in parsed_by_vals[id(vals)]:
                attribute_to_values[attribute_name].add(value_name)

        # Seed pa_records with the *existing* attributes, then create the
        # missing ones. Seeding matters: when an attribute already exists but
        # every imported value for it is new, the PAV search below finds nothing
        # and would leave pa_records[attribute_name] unset -> KeyError when
        # building missing_pav (a latent upstream bug).
        pa_records = {  # attribute_name => Record<'product.attribute'>
            pa.name: pa
            for pa in PA.search(Domain("name", "in", list(attribute_to_values)))
        }
        missing_pa = [
            {
                "name": attribute_name,
                "create_variant": "dynamic",
                "display_type": "radio",
            }
            for attribute_name in attribute_to_values
            if attribute_name not in pa_records
        ]
        if missing_pa:
            for pa in PA.create(missing_pa):
                pa_records[pa.name] = pa

        # search existing attribute values
        pa_pav_records = {}  # (attribute_name, value_name) => Record<'product.attribute.value'>
        domain = Domain(False)
        for attribute_name, value_names in attribute_to_values.items():
            domain |= Domain("name", "in", value_names) & Domain(
                "attribute_id.name", "=", attribute_name
            )
        for pav in PAV.search(domain):
            pa_records[pav.attribute_id.name] = pav.attribute_id
            pa_pav_records[pav.attribute_id.name, pav.name] = pav

        # create missing attribute values
        missing_pav = [
            {
                "name": value_name,
                "attribute_id": pa_records[attribute_name].id,
            }
            for attribute_name, value_names in attribute_to_values.items()
            for value_name in value_names
            if (attribute_name, value_name) not in pa_pav_records
        ]
        if missing_pav:
            for pav in PAV.create(missing_pav):
                pa_pav_records[pav.attribute_id.name, pav.name] = pav

        return pa_pav_records

    def _import_resolve_templates(self, with_import_values):
        """Resolve the ``product.template`` each imported row targets (by
        ``product_tmpl_id`` or by ``name``), creating missing templates with
        only their required fields.

        :return: ``(id2template, name2template, product_templates,
            created_templates)`` where the first two are lookup dicts and the
            last two are the pre-existing / newly created recordsets.
        """
        PT = self.env["product.template"]

        product_templates = PT.search(
            Domain("name", "in", [vals["name"] for vals in with_import_values])
            | Domain(
                "id", "in", [vals.get("product_tmpl_id") for vals in with_import_values]
            )
        )
        id2template = dict(
            zip(product_templates.ids, product_templates, strict=True)
        )  # id => Record<'product.template'>
        name2template = dict(
            zip(product_templates.mapped("name"), product_templates, strict=True)
        )  # template_name => Record<'product.template'>

        template_vals_list = {}
        for vals in with_import_values:
            name = vals["name"]
            if name and name not in name2template and name not in template_vals_list:
                template_vals_list[name] = {
                    key: value
                    for key, value in vals.items()
                    if PT._fields[key].required
                }

        # create the first product to have default values
        created_templates = PT.with_context(create_product_product=True).create(
            list(template_vals_list.values())
        )
        for rec in created_templates:
            id2template[rec.id] = rec
            name2template[rec.name] = rec

        return id2template, name2template, product_templates, created_templates

    def _import_resolve_ptavs(
        self,
        with_import_values,
        parsed_by_vals,
        id2template,
        name2template,
        pa_pav_records,
    ):
        """Ensure each template carries the attribute lines/values used by the
        import (creating ``product.template.attribute.line`` or extending its
        ``value_ids``), then map every ``(template_id, attribute_value_id)`` to
        its ``product.template.attribute.value``.

        :return: ``{(template_id, attribute_value_id):
            product.template.attribute.value}``
        """
        PTAL = self.env["product.template.attribute.line"]

        pt_to_attribute_to_values = defaultdict(
            list
        )  # (template_id, attribute_id) => [pav]
        for vals in with_import_values:
            pt = id2template.get(vals.get("product_tmpl_id")) or name2template.get(
                vals["name"]
            )
            for attribute_name, value_name in parsed_by_vals[id(vals)]:
                pav = pa_pav_records[attribute_name, value_name]
                pt_to_attribute_to_values[pt.id, pav.attribute_id.id].append(pav)
        domain = Domain(False)
        for template_id, attribute_id in pt_to_attribute_to_values:
            domain |= Domain("product_tmpl_id", "=", template_id) & Domain(
                "attribute_id", "=", attribute_id
            )
        template_attribute_to_ptal = {  # (template_id, attribute_id) => ptal
            (ptal.product_tmpl_id.id, ptal.attribute_id.id): ptal
            for ptal in PTAL.search(domain)
        }
        ptals_to_create = []
        for (template_id, attribute_id), pavs in pt_to_attribute_to_values.items():
            ptal = template_attribute_to_ptal.get((template_id, attribute_id))
            if ptal:
                # add the new value ids
                ptal.value_ids = ptal.value_ids.union(*pavs)
            else:
                ptals_to_create.append(
                    {
                        "product_tmpl_id": template_id,
                        "attribute_id": attribute_id,
                        "value_ids": [value.id for value in pavs],
                    }
                )
        if ptals_to_create:
            ptals = PTAL.create(ptals_to_create)
            template_attribute_to_ptal.update(
                dict(
                    zip(
                        [
                            (val["product_tmpl_id"], val["attribute_id"])
                            for val in ptals_to_create
                        ],
                        ptals,
                        strict=True,
                    )
                )
            )

        return {  # (template_id, value_id) => Record<'product.template.attribute.value'>
            (template_id, pav.id): template_attribute_to_ptal[
                template_id, attribute_id
            ].product_template_value_ids.filtered(
                lambda v, pav=pav: v.product_attribute_value_id.id == pav.id
            )
            for (template_id, attribute_id), pavs in pt_to_attribute_to_values.items()
            for pav in pavs
        }

    @api.model
    def load(self, fields, data):
        if "import_attribute_values" in fields and not self.env.context.get(
            "from_template_import"
        ):
            res = self.env["product.template"].load(fields, data)
            res["ids"] = self.search(Domain("product_tmpl_id", "in", res["ids"])).ids
            return res
        return super().load(fields, data)

    @api.model_create_multi
    def create(self, vals_list):
        products = super(
            ProductProduct,
            self.with_context(create_product_product=False),
        ).create(vals_list)
        # `_get_variant_id_for_combination` depends on existing variants
        self.env.registry.clear_cache()
        # Return products in the caller's env so that the internal
        # create_product_product=False context doesn't leak to downstream
        # operations (e.g., product.copy() calling template.create() which
        # then skips _create_variant_ids()).
        return products.with_env(self.env)

    def write(self, vals):
        res = super().write(vals)
        # `_get_variant_id_for_combination` depends on `product_template_attribute_value_ids`
        # and on which template a variant belongs to;
        # `_get_first_possible_variant_id` depends on the variants' active state.
        if (
            "product_template_attribute_value_ids" in vals
            or "active" in vals
            or "product_tmpl_id" in vals
        ):
            self.env.registry.clear_cache()
        return res

    def copy(self, default=None):
        """Variants are generated depending on the configuration of attributes
        and values on the template, so copying them does not make sense.

        For convenience the template is copied instead and its first variant is
        returned.
        """
        # copy variant is disabled in https://github.com/odoo/odoo/pull/38303
        # this returns the first possible combination of variant to make it
        # works for now, need to be fixed to return product_variant_id if it's
        # possible in the future

        # Use tmp recordset in case we copy several variants from the same template
        templates = [product.product_tmpl_id for product in self]
        templates_to_copy = self.env["product.template"].concat(*templates)
        new_templates = templates_to_copy.copy(default=default)
        new_product_list = [
            new_template.product_variant_id
            or new_template._create_first_product_variant()
            for new_template in new_templates
        ]
        return self.env["product.product"].concat(*new_product_list)

    def unlink(self):
        if self.env.context.get("create_product_product") is False:
            res = super().unlink()
            # `_get_variant_id_for_combination` depends on existing variants,
            # also on this early-return path (e.g. import placeholder cleanup).
            self.env.registry.clear_cache()
            return res

        unlink_products_ids = set()
        unlink_templates_ids = set()

        # Check if products still exists, in case they've been unlinked by unlinking their template
        existing_products = self.exists()
        product_ids_by_template_id = {
            template.id: set(ids)
            for template, ids in self.with_context(active_test=False)._read_group(
                domain=[
                    ("product_tmpl_id", "in", existing_products.product_tmpl_id.ids),
                ],
                groupby=["product_tmpl_id"],
                aggregates=["id:array_agg"],
            )
        }
        for product in existing_products:
            # If there is an image set on the variant and no image set on the
            # template, move the image to the template.
            if product.image_variant_1920 and not product.product_tmpl_id.image_1920:
                product.product_tmpl_id.image_1920 = product.image_variant_1920
            # Check if the product is last product of this template...
            # NB: only the current record is subtracted (not the whole batch):
            # the variant engine batch-unlinks every obsolete variant during
            # regeneration and relies on the template surviving that call.
            has_other_products = product_ids_by_template_id.get(
                product.product_tmpl_id.id,
                set(),
            ) - {product.id}
            # ... and do not delete product template if it's configured to be created "on demand"
            if (
                not has_other_products
                and not product.product_tmpl_id.has_dynamic_attributes()
            ):
                unlink_templates_ids.add(product.product_tmpl_id.id)
            unlink_products_ids.add(product.id)
        unlink_products = self.env["product.product"].browse(unlink_products_ids)
        res = super(ProductProduct, unlink_products).unlink()
        # delete templates after calling super, as deleting template could lead to deleting
        # products due to ondelete='cascade'
        unlink_templates = self.env["product.template"].browse(unlink_templates_ids)
        unlink_templates.unlink()
        # `_get_variant_id_for_combination` depends on existing variants
        self.env.registry.clear_cache()
        return res

    def _compute_variant_image(self, size):
        """Fall back to the template image when the variant has none, for the
        given resolution ``size`` (e.g. 1920).

        Kept as one method per size (rather than a single compute assigning all
        five fields) so that reading a thumbnail never forces loading the larger
        image blobs.
        """
        field = "image_%s" % size
        variant_field = "image_variant_%s" % size
        for record in self:
            record[field] = record[variant_field] or record.product_tmpl_id[field]

    def _compute_image_1920(self):
        self._compute_variant_image(1920)

    def _compute_image_1024(self):
        self._compute_variant_image(1024)

    def _compute_image_512(self):
        self._compute_variant_image(512)

    def _compute_image_256(self):
        self._compute_variant_image(256)

    def _compute_image_128(self):
        self._compute_variant_image(128)

    def _compute_can_image_1024_be_zoomed(self):
        """Get the image from the template if no image is set on the variant."""
        for record in self:
            record.can_image_1024_be_zoomed = (
                record.can_image_variant_1024_be_zoomed
                if record.image_variant_1920
                else record.product_tmpl_id.can_image_1024_be_zoomed
            )

    @api.depends("image_variant_1920", "image_variant_1024")
    def _compute_can_image_variant_1024_be_zoomed(self):
        # bin_size=False: under a bin_size context the binary fields yield
        # size strings ("12.5 Kb") that crash the image decoding.
        for record in self.with_context(bin_size=False):
            record.can_image_variant_1024_be_zoomed = (
                record.image_variant_1920
                and is_image_size_above(
                    record.image_variant_1920,
                    record.image_variant_1024,
                )
            )

    @api.depends("product_tmpl_id.pricelist_rule_ids")
    def _compute_pricelist_rule_ids(self):
        for product in self:
            if not product.id:
                product.pricelist_rule_ids = False
                continue
            product.pricelist_rule_ids = (
                product.product_tmpl_id.pricelist_rule_ids.filtered(
                    lambda rule, product=product: rule.product_id <= product,
                )
            )

    @api.depends("product_tmpl_id.write_date")
    def _compute_write_date(self):
        """
        First, the purpose of this computation is to update a product's
        write_date whenever its template's write_date is updated.  Indeed,
        when a template's image is modified, updating its products'
        write_date will invalidate the browser's cache for the products'
        image, which may be the same as the template's.  This guarantees UI
        consistency.

        Second, the field 'write_date' is automatically updated by the
        framework when the product is modified.  The recomputation of the
        field supplements that behavior to keep the product's write_date
        up-to-date with its template's write_date.

        Third, the framework normally prevents us from updating write_date
        because it is a "magic" field.  However, the assignment inside the
        compute method is not subject to this restriction.  It therefore
        works as intended :-)
        """
        now = self.env.cr.now()
        self.fetch(["write_date"])
        for record in self:
            if not record.id:
                record.write_date = record._origin.write_date
                continue
            record.write_date = max(
                record.write_date or now,
                record.product_tmpl_id.write_date or now,
            )

    @api.depends("product_template_attribute_value_ids")
    def _compute_combination_indices(self):
        for product in self:
            product.combination_indices = (
                product.product_template_attribute_value_ids._ids2str()
            )

    def _compute_is_product_variant(self):
        self.is_product_variant = True

    @api.depends("product_template_attribute_value_ids.price_extra")
    def _compute_product_price_extra(self):
        for product in self:
            product.price_extra = sum(
                product.product_template_attribute_value_ids.mapped("price_extra"),
            )

    @api.depends("list_price", "price_extra")
    @api.depends_context("uom")
    def _compute_product_lst_price(self):
        to_uom = None
        if "uom" in self.env.context:
            to_uom = self.env["uom.uom"].browse(self.env.context["uom"])

        for product in self:
            if to_uom:
                list_price = product.uom_id._compute_price(product.list_price, to_uom)
            else:
                list_price = product.list_price
            product.lst_price = list_price + product.price_extra

    @api.depends(
        "default_code",
        "seller_ids.partner_id",
        "seller_ids.product_code",
        "seller_ids.product_id",
    )
    @api.depends_context("partner_id")
    def _compute_product_code(self):
        read_access = self.env["ir.model.access"].check(
            "product.supplierinfo",
            "read",
            False,
        )
        partner_id = self.env.context.get("partner_id")
        for product in self:
            product.code = product.default_code
            # With no partner in context no supplier row can match, so skip
            # iterating sellers entirely (the common, no-partner render path).
            if read_access and partner_id:
                for supplier_info in product.seller_ids:
                    if supplier_info.partner_id.id == partner_id:
                        if (
                            supplier_info.product_id
                            and supplier_info.product_id != product
                        ):
                            # Supplier info specific for another variant.
                            continue
                        product.code = (
                            supplier_info.product_code or product.default_code
                        )
                        if product == supplier_info.product_id:
                            # Supplier info specific for this variant.
                            break

    @api.depends(
        "default_code",
        "name",
        "code",
        "display_name",
        "seller_ids.partner_id",
        "seller_ids.product_name",
    )
    @api.depends_context("partner_id")
    def _compute_partner_ref(self):
        partner_id = self.env.context.get("partner_id")
        for product in self:
            # Without a partner in context, no supplier row matches: fall back to
            # display_name directly instead of scanning seller_ids per product.
            matched_seller = False
            if partner_id:
                matched_seller = next(
                    (
                        seller
                        for seller in product.seller_ids
                        if seller.partner_id.id == partner_id
                    ),
                    False,
                )
            if matched_seller:
                product_name = (
                    matched_seller.product_name or product.default_code or product.name
                )
                product.partner_ref = "%s%s" % (
                    (product.code and "[%s] " % product.code) or "",
                    product_name,
                )
            else:
                product.partner_ref = product.display_name

    def _compute_product_document_count(self):
        counts = {}
        if self:
            data = self.env["product.document"]._read_group(
                [("res_model", "=", "product.product"), ("res_id", "in", self.ids)],
                ["res_id"],
                ["__count"],
            )
            counts = dict(data)
        for product in self:
            product.product_document_count = counts.get(product.id, 0)

    @api.depends("product_tag_ids", "additional_product_tag_ids")
    def _compute_all_product_tag_ids(self):
        for product in self:
            product.all_product_tag_ids = (
                product.product_tag_ids | product.additional_product_tag_ids
            ).sorted("sequence")

    @api.depends_context(
        "company_id",
        "partner_id",
        "display_default_code",
        "seller_id",
        "formatted_display_name",
        "lang",
    )
    @api.depends("name", "default_code", "product_tmpl_id")
    def _compute_display_name(self):
        def get_display_name(name, code):
            if self.env.context.get("display_default_code", True) and code:
                if self.env.context.get("formatted_display_name"):
                    return f"{name}\t--{code}--"
                return f"[{code}] {name}"
            return name

        partner_id = self.env.context.get("partner_id")
        if partner_id:
            partner_ids = [
                partner_id,
                self.env["res.partner"].browse(partner_id).commercial_partner_id.id,
            ]
        else:
            partner_ids = []
        company_id = self.env.context.get("company_id")

        # all user don't have access to seller and partner
        # check access and use superuser
        self.check_access("read")

        product_template_ids = self.sudo().product_tmpl_id.ids

        if partner_ids:
            # prefetch the fields used by the `display_name`
            supplier_info = (
                self.env["product.supplierinfo"]
                .sudo()
                .search_fetch(
                    [
                        ("product_tmpl_id", "in", product_template_ids),
                        ("partner_id", "in", partner_ids),
                    ],
                    [
                        "product_tmpl_id",
                        "product_id",
                        "company_id",
                        "product_name",
                        "product_code",
                    ],
                )
            )
            supplier_info_by_template = {}
            for r in supplier_info:
                supplier_info_by_template.setdefault(r.product_tmpl_id, []).append(r)

        # Loop-invariant: the seller forced through context is the same for
        # every product, so resolve it once instead of per record.
        context_sellers = (
            self.env["product.supplierinfo"]
            .sudo()
            .browse(self.env.context.get("seller_id"))
            or []
        )

        for product in self.sudo():
            variant = (
                product.product_template_attribute_value_ids._get_combination_name()
            )

            name = (variant and "%s (%s)" % (product.name, variant)) or product.name
            sellers = context_sellers
            if not sellers and partner_ids:
                product_supplier_info = supplier_info_by_template.get(
                    product.product_tmpl_id,
                    [],
                )
                sellers = [
                    x
                    for x in product_supplier_info
                    if x.product_id and x.product_id == product
                ]
                if not sellers:
                    sellers = [x for x in product_supplier_info if not x.product_id]
                # Filter out sellers based on the company. This is done afterwards for a better
                # code readability. At this point, only a few sellers should remain, so it should
                # not be a performance issue.
                if company_id:
                    sellers = [
                        x for x in sellers if x.company_id.id in [company_id, False]
                    ]
            if sellers:
                temp = []
                for s in sellers:
                    seller_variant = (
                        s.product_name
                        and (
                            (variant and "%s (%s)" % (s.product_name, variant))
                            or s.product_name
                        )
                    ) or False
                    temp.append(
                        get_display_name(
                            seller_variant or name,
                            s.product_code or product.default_code,
                        ),
                    )

                product.display_name = ", ".join(unique(temp))
            else:
                product.display_name = get_display_name(name, product.default_code)

    def _inverse_pricelist_rule_ids(self):
        for product in self:
            template = product.product_tmpl_id
            template.pricelist_rule_ids = (
                product.pricelist_rule_ids
                # We have to manually keep the rules the current variant
                # wasn't aware of because they targeted other variants.
                | template.pricelist_rule_ids.filtered(
                    lambda rule, product=product: rule.product_id
                    and rule.product_id != product,
                )
            )

    def _set_image_1920(self):
        return self._set_template_field("image_1920", "image_variant_1920")

    @api.model
    def _search(self, domain, *args, **kwargs):
        # TDE FIXME: strange
        if self.env.context.get("search_default_categ_id"):
            domain = Domain(domain) & Domain(
                "categ_id",
                "child_of",
                self.env.context["search_default_categ_id"],
            )
        return super()._search(domain, *args, **kwargs)

    @api.model
    def _search_display_name(self, operator, value):
        is_positive = operator not in Domain.NEGATIVE_OPERATORS
        template_domains = [[("name", operator, value)]]
        product_domains = [[("default_code", operator, value)]]

        if operator == "in":
            product_domains.append([("barcode", "in", value)])
            product_domains.extend(
                [("default_code", "=", m.group(2))]
                for v in value
                if isinstance(v, str) and (m := re.search(r"(\[(.*?)\])", v))
            )
        elif operator.endswith("like") and is_positive:
            product_domains.append([("barcode", "in", [value])])

        supplier_domain = []
        if partner_id := self.env.context.get("partner_id"):
            supplier_domain = [
                ("partner_id", "=", partner_id),
                "|",
                ("product_code", operator, value),
                ("product_name", operator, value),
            ]

        # AND clauses properly hit indexes so no need for custom sql in this case.
        if operator in Domain.NEGATIVE_OPERATORS:
            domains = template_domains + product_domains
            if supplier_domain:
                domains.append([("product_tmpl_id.seller_ids", "any", supplier_domain)])
            return Domain.AND(domains)

        # Disable active_test to simplify subqueries
        self_no_active_test = self.with_context(active_test=False)
        queries = [
            self_no_active_test._search(
                [
                    (
                        "product_tmpl_id",
                        "in",
                        self_no_active_test.env["product.template"]._search(
                            Domain.OR(template_domains)
                        ),
                    ),
                ],
            ),
            self_no_active_test._search(Domain.OR(product_domains)),
        ]
        if supplier_domain:
            queries.append(
                self_no_active_test._search(
                    [
                        (
                            "product_tmpl_id",
                            "in",
                            self_no_active_test.env["product.supplierinfo"]
                            ._search(supplier_domain)
                            .subselect("product_tmpl_id"),
                        ),
                    ],
                ),
            )
        query = SQL(
            """(%s)""",
            SQL("UNION ALL").join([SQL("(%s)", query.select()) for query in queries]),
        )

        return [("id", "in", query)]

    @api.model
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        if not name:
            return super().name_search(name, domain, operator, limit)
        # search progressively by the most specific attributes
        positive_operators = ["=", "ilike", "=ilike", "like", "=like"]
        is_positive = operator not in Domain.NEGATIVE_OPERATORS
        products = self.browse()
        domain = Domain(domain or Domain.TRUE)
        if operator in positive_operators:
            products = self.search_fetch(
                domain & Domain("default_code", "=", name),
                ["display_name"],
                limit=limit,
            ) or self.search_fetch(
                domain & Domain("barcode", "=", name),
                ["display_name"],
                limit=limit,
            )
        if not products:
            if is_positive:
                # Do not merge the 2 next lines into one single search, SQL search performance would be abysmal
                # on a database with thousands of matching products, due to the huge merge+unique needed for the
                # OR operator (and given the fact that the 'name' lookup results come from the ir.translation table
                # Performing a quick memory merge of ids in Python will give much better performance
                products = self.search_fetch(
                    domain & Domain("default_code", operator, name),
                    ["display_name"],
                    limit=limit,
                )
                limit_rest = limit and limit - len(products)
                # `search` treats limit=0/None as "unlimited", so keep searching
                # names whenever there is no limit or room remains. Guarding on
                # `limit_rest > 0` alone dropped every name match for limit=0.
                if not limit or limit_rest > 0:
                    # This branch only runs when the default_code search did not
                    # reach `limit`, so `products` already holds every matching
                    # default_code row: reuse its ids instead of re-issuing the
                    # same search as an exclusion subquery.
                    products |= self.search_fetch(
                        domain
                        & Domain("id", "not in", products.ids)
                        & Domain("name", operator, name),
                        ["display_name"],
                        limit=limit_rest,
                    )
            else:
                domain_neg = Domain("name", operator, name) & (
                    Domain("default_code", operator, name)
                    | Domain("default_code", "=", False)
                )
                products = self.search_fetch(
                    domain & domain_neg,
                    ["display_name"],
                    limit=limit,
                )
        if (
            not products
            and operator in positive_operators
            and (m := re.search(r"(\[(.*?)\])", name))
        ):
            match_domain = Domain("default_code", "=", m.group(2))
            products = self.search_fetch(
                domain & match_domain,
                ["display_name"],
                limit=limit,
            )
        if not products and (partner_id := self.env.context.get("partner_id")):
            # still no results, partner in context: search on supplier info as last hope to find something
            supplier_domain = Domain(
                [
                    ("partner_id", "=", partner_id),
                    "|",
                    ("product_code", operator, name),
                    ("product_name", operator, name),
                ],
            )
            match_domain = Domain("product_tmpl_id.seller_ids", "any", supplier_domain)
            products = self.search_fetch(
                domain & match_domain,
                ["display_name"],
                limit=limit,
            )
        return [(product.id, product.display_name) for product in products.sudo()]

    def _search_all_product_tag_ids(self, operator, operand):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return [
            "|",
            ("product_tag_ids", operator, operand),
            ("additional_product_tag_ids", operator, operand),
        ]

    def _search_is_in_selected_section_of_order(self, operator, value):
        if operator != "in":
            return NotImplemented
        ctx = self.env.context
        order_id = ctx.get("order_id")
        order_model = ctx.get("product_catalog_order_model")
        line_field = ctx.get("child_field")
        if not (order_id and order_model and line_field):
            return []

        product_ids = (
            self.env[order_model]
            .browse(order_id)[line_field]
            .filtered(
                lambda line: line.get_line_parent_section().id == ctx.get("section_id"),
            )
            .mapped("product_id")
            .ids
        )

        return [("id", "in", product_ids)]

    @api.onchange("lst_price")
    def _set_product_lst_price(self):
        for product in self:
            if self.env.context.get("uom"):
                value = (
                    self.env["uom.uom"]
                    .browse(self.env.context["uom"])
                    ._compute_price(product.lst_price, product.uom_id)
                )
            else:
                value = product.lst_price
            value -= product.price_extra
            product.write({"list_price": value})

    @api.onchange("standard_price")
    def _onchange_standard_price(self):
        if self.standard_price < 0:
            raise ValidationError(
                self.env._("The cost of a product can't be negative."),
            )

    @api.onchange("default_code")
    def _onchange_default_code(self):
        if not self.default_code:
            return None

        domain = [("default_code", "=", self.default_code)]
        if self.id.origin:
            domain.append(("id", "!=", self.id.origin))

        if self.env["product.product"].search_count(domain, limit=1):
            return {
                "warning": {
                    "title": self.env._("Note:"),
                    "message": self.env._(
                        "The Reference '%s' already exists.",
                        self.default_code,
                    ),
                },
            }
        return None

    @api.onchange("uom_id")
    def _onchange_uom_id(self):
        if self._origin.uom_id == self.uom_id or not self._trigger_uom_warning():
            return None
        message = self.env._(
            "Changing the unit of measure for your product will apply a conversion 1 %(old_uom_name)s = 1 %(new_uom_name)s.\n"
            "All existing records (Sales orders, Purchase orders, etc.) using this product will be updated by replacing the unit name.",
            old_uom_name=self._origin.uom_id.display_name,
            new_uom_name=self.uom_id.display_name,
        )
        return {
            "warning": {
                "title": self.env._("What to expect ?"),
                "message": message,
            },
        }

    def action_archive(self):
        records = self.filtered("active")
        super().action_archive()
        # We deactivate product templates which are active with no active variants.
        records.product_tmpl_id.filtered(
            lambda product_tmpl: product_tmpl.active
            and not product_tmpl.product_variant_ids,
        ).action_archive()

    def action_unarchive(self):
        records = self.filtered(lambda rec: not rec.active)
        super().action_unarchive()
        # We activate product templates which are inactive with active variants.
        records.product_tmpl_id.filtered(
            lambda product_tmpl: not product_tmpl.active
            and product_tmpl.product_variant_ids,
        ).action_unarchive()

    @api.model
    def view_header_get(self, view_id, view_type):
        if self.env.context.get("categ_id"):
            return self.env._(
                "Products: %(category)s",
                category=self.env["product.category"]
                .browse(self.env.context["categ_id"])
                .name,
            )
        return super().view_header_get(view_id, view_type)

    # === ACTION METHODS ===#

    @api.readonly
    def action_view_label_layout(self):
        if any(product.type == "service" for product in self):
            raise ValidationError(
                self.env._("Labels cannot be printed for products of service type"),
            )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "product.action_view_label_layout",
        )
        action["context"] = {"default_product_ids": self.ids}
        return action

    def view_product_template(self):
        """Utility method used to add an "Open Template" button in product views"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "product.template",
            "view_mode": "form",
            "res_id": self.product_tmpl_id.id,
            "target": "new",
        }

    @api.readonly
    def action_open_documents(self):
        res = self.product_tmpl_id.action_open_documents()
        res["context"].update(
            {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "search_default_context_variant": True,
            },
        )
        return res

    # === BUSINESS METHODS ===#

    def _filter_to_unlink(self):
        return self

    def _unlink_or_archive(self, check_access=True):
        """Unlink or archive products.
        Try in batch as much as possible because it is much faster.
        Use dichotomy when an exception occurs.
        """
        # Avoid access errors in case the products is shared amongst companies
        # but the underlying objects are not. If unlink fails because of an
        # AccessError (e.g. while recomputing fields), the 'write' call will
        # fail as well for the same reason since the field has been set to
        # recompute.
        if check_access:
            self.check_access("unlink")
            self.check_access("write")
            self = self.sudo()
            to_unlink = self._filter_to_unlink()
            to_archive = self - to_unlink
            to_archive.write({"active": False})
            self = to_unlink

        try:
            with self.env.cr.savepoint(), tools.mute_logger("odoo.db"):
                self.unlink()
        except Exception:
            # We catch all kind of exceptions to be sure that the operation
            # doesn't fail.
            if len(self) > 1:
                self[: len(self) // 2]._unlink_or_archive(check_access=False)
                self[len(self) // 2 :]._unlink_or_archive(check_access=False)
            elif self.active:
                # Note: this can still fail if something is preventing
                # from archiving.
                # This is the case from existing stock reordering rules.
                self.write({"active": False})

    def _get_invoice_policy(self):
        return False

    def _get_placeholder_filename(self, field):
        if field in tuple("image_%s" % size for size in IMAGE_SIZES):
            return self._get_product_placeholder_filename()
        return super()._get_placeholder_filename(field)

    def _get_product_placeholder_filename(self):
        return self.product_tmpl_id._get_product_placeholder_filename()

    def _get_barcodes_by_company(self):
        return [
            (company_id, [p.barcode for p in products if p.barcode])
            for company_id, products in groupby(self, lambda p: p.company_id.id)
        ]

    def _get_barcode_search_domain(self, barcodes_within_company, company_id):
        domain = [("barcode", "in", barcodes_within_company)]
        if company_id:
            domain.append(("company_id", "in", (False, company_id)))
        return domain

    def _set_template_field(self, template_field, variant_field):
        # Batch count active variants per template to avoid N+1 search_count
        tmpl_ids = self.product_tmpl_id.ids
        variant_counts = {}
        if tmpl_ids:
            data = self.env["product.product"]._read_group(
                [("product_tmpl_id", "in", tmpl_ids), ("active", "=", True)],
                ["product_tmpl_id"],
                ["__count"],
            )
            variant_counts = {tmpl.id: count for tmpl, count in data}
        for record in self:
            if (
                # We are trying to remove a field from the variant even though it is already
                # not set on the variant, remove it from the template instead.
                (not record[template_field] and not record[variant_field])
                # We are trying to add a field to the variant, but the template field is
                # not set, write on the template instead.
                or (
                    record[template_field]
                    and not record.product_tmpl_id[template_field]
                )
                # There is only one variant, always write on the template.
                or variant_counts.get(record.product_tmpl_id.id, 0) <= 1
            ):
                record[variant_field] = False
                record.product_tmpl_id[template_field] = record[template_field]
            else:
                record[variant_field] = record[template_field]

    def _trigger_uom_warning(self):
        return False

    def _prepare_sellers(self, params=False):
        # Use variant_seller_ids (no company domain, unlike seller_ids) so that
        # _get_filtered_supplier can do the company filtering itself based on
        # params (e.g. the order company). sudo: reading cross-company sellers
        # would otherwise raise on suppliers of other companies.
        all_sellers = self.sudo().variant_seller_ids
        sellers = all_sellers._get_filtered_supplier(self.env.company, self, params)
        return sellers.sorted(lambda s: (s.sequence, -s.min_qty, s.price, s.id))

    def _get_filtered_sellers(
        self,
        partner_id=False,
        quantity=0.0,
        date=None,
        uom_id=False,
        params=False,
    ):
        self.ensure_one()
        if not date:
            date = fields.Date.context_today(self)
        precision = self.env["decimal.precision"].precision_get("Product Unit")

        sellers_filtered = self._prepare_sellers(params)
        matching_ids = []
        for seller in sellers_filtered:
            if seller.date_start and seller.date_start > date:
                continue
            if seller.date_end and seller.date_end < date:
                continue
            if (
                params
                and params.get("force_uom")
                and seller.product_uom_id not in (uom_id, self.uom_id)
            ):
                continue
            if partner_id and seller.partner_id not in [
                partner_id,
                partner_id.parent_id,
            ]:
                continue
            if seller.product_id and seller.product_id != self:
                continue
            # min_qty is expressed in the seller's UoM, so convert the requested
            # quantity into it before comparing. This runs only for sellers that
            # passed the filters above, so we never convert into the UoM of an
            # irrelevant seller. If the requested UoM shares no reference unit
            # with the seller's (different category, e.g. Units vs Liters), the
            # seller cannot satisfy a request denominated in `uom_id` -- skip it
            # instead of letting the conversion raise.
            if quantity is not None:
                quantity_uom_seller = quantity
                if quantity_uom_seller and uom_id and uom_id != seller.product_uom_id:
                    if not uom_id._has_common_reference(seller.product_uom_id):
                        continue
                    quantity_uom_seller = uom_id._compute_quantity(
                        quantity_uom_seller,
                        seller.product_uom_id,
                    )
                if (
                    float_compare(
                        quantity_uom_seller,
                        seller.min_qty,
                        precision_digits=precision,
                    )
                    == -1
                ):
                    continue
            matching_ids.append(seller.id)
        return self.env["product.supplierinfo"].browse(matching_ids)

    def _select_seller(
        self,
        partner_id=False,
        quantity=0.0,
        date=None,
        uom_id=False,
        ordered_by="price_discounted",
        params=False,
    ):
        # Always sort by discounted price but another field can take the primacy through the `ordered_by` param.
        sort_key = ("price_discounted", "sequence", "id")
        if ordered_by != "price_discounted":
            sort_key = (ordered_by, "price_discounted", "sequence", "id")

        def sort_function(record):
            vals = {
                "price_discounted": record.currency_id._convert(
                    record.price_discounted,
                    record.env.company.currency_id,
                    record.env.company,
                    date or fields.Date.context_today(self),
                    round=False,
                ),
            }
            return [vals.get(key, record[key]) for key in sort_key]

        sellers = self._get_filtered_sellers(
            partner_id=partner_id,
            quantity=quantity,
            date=date,
            uom_id=uom_id,
            params=params,
        )
        res_ids = []
        res_partner = None
        for seller in sellers:
            if not res_ids or res_partner == seller.partner_id:
                res_ids.append(seller.id)
                res_partner = seller.partner_id
        res = self.env["product.supplierinfo"].browse(res_ids)
        return res and res.sorted(sort_function)[:1]

    def _get_product_price_context(self, combination):
        self.ensure_one()
        res = {}

        no_variant_attributes_price_extra = self._get_no_variant_attributes_price_extra(
            combination,
        )

        if no_variant_attributes_price_extra:
            res["no_variant_attributes_price_extra"] = no_variant_attributes_price_extra

        return res

    def _get_no_variant_attributes_price_extra(self, combination):
        # It is possible that a no_variant attribute is still in a variant if
        # the type of the attribute has been changed after creation.
        return sum(
            ptav.price_extra
            for ptav in combination.filtered(
                lambda ptav: ptav.price_extra
                and ptav.product_tmpl_id == self.product_tmpl_id
                and ptav not in self.product_template_attribute_value_ids,
            )
        )

    def _get_attributes_extra_price(self):
        self.ensure_one()

        return self.price_extra + self.env.context.get(
            "no_variant_attributes_price_extra",
            0,
        )

    def _price_compute(
        self,
        price_type,
        uom=None,
        currency=None,
        company=None,
        date=False,
    ):
        company = company or self.env.company
        date = date or fields.Date.context_today(self)

        self = self.with_company(company)
        if price_type == "standard_price":
            # standard_price field can only be seen by users in base.group_user
            # Thus, in order to compute the sale price from the cost for users not in this group
            # We fetch the standard price as the superuser
            self = self.sudo()

        prices = dict.fromkeys(self.ids, 0.0)
        for product in self:
            price = product[price_type] or 0.0
            price_currency = product.currency_id
            if price_type == "standard_price":
                price_currency = product.cost_currency_id
            elif price_type == "list_price":
                price += product._get_attributes_extra_price()

            if uom:
                price = product.uom_id._compute_price(price, uom)

            # Convert from current user company currency to asked one
            # This is right cause a field cannot be in more than one currency
            if currency:
                price = price_currency._convert(price, currency, company, date)

            prices[product.id] = price

        return prices

    @api.model
    def get_empty_list_help(self, help_message):
        self = self.with_context(
            empty_list_help_document_name=self.env._("product"),
        )
        return super().get_empty_list_help(help_message)

    def get_product_multiline_description_sale(self):
        """Compute a multiline description of this product, in the context of sales
        (do not use for purchases or other display reasons that don't intend to use "description_sale").
        It will often be used as the default description of a sale order line referencing this product.
        """
        name = self.display_name
        if self.description_sale:
            name += "\n" + self.description_sale

        return name

    def _is_variant_possible(self, parent_combination=None):
        """Return whether the variant is possible based on its own combination,
        and optionally a parent combination.

        See `_is_combination_possible` for more information.

        :param parent_combination: combination from which `self` is an
            optional or accessory product.
        :type parent_combination: recordset `product.template.attribute.value`

        :return: ẁhether the variant is possible based on its own combination
        :rtype: bool
        """
        self.ensure_one()
        return self.product_tmpl_id._is_combination_possible(
            self.product_template_attribute_value_ids,
            parent_combination=parent_combination,
            ignore_no_variant=True,
        )

    def get_contextual_price(self):
        return self._get_contextual_price()

    def _get_contextual_price(self):
        # FIXME VFE this won't consider ptavs extra prices, since we rely on the template price
        self.ensure_one()
        return self.product_tmpl_id._get_contextual_price(self)

    def _get_contextual_discount(self):
        self.ensure_one()

        pricelist = self.product_tmpl_id._get_contextual_pricelist()
        if not pricelist:
            # No pricelist = no discount
            return 0.0

        lst_price = self.currency_id._convert(
            self.lst_price,
            pricelist.currency_id,
            self.env.company,
            fields.Datetime.now(),
            round=False,
        )
        if lst_price:
            return (lst_price - self._get_contextual_price()) / lst_price
        return 0.0

    def _update_uom(self, to_uom_id):
        """Hook to handle an UoM modification. Avoid recomputation and just replace the
        many2one field on the impacted models.
        """
        return True

    def _check_duplicated_product_barcodes(self, barcodes_within_company, company_id):
        domain = self._get_barcode_search_domain(barcodes_within_company, company_id)
        products_by_barcode = self.sudo()._read_group(
            domain,
            ["barcode"],
            ["id:recordset"],
            having=[("__count", ">", 1)],
        )

        duplicates_as_str = "\n".join(
            self.env._(
                '- Barcode "%(barcode)s" already assigned to product(s): %(product_list)s',
                barcode=barcode,
                product_list=duplicate_products._filtered_access("read").mapped(
                    "display_name",
                ),
            )
            for barcode, duplicate_products in products_by_barcode
        )
        if duplicates_as_str:
            duplicates_as_str += self.env._(
                "\n\nNote: products that you don't have access to will not be shown above.",
            )
            raise ValidationError(
                self.env._("Barcode(s) already assigned:\n\n%s", duplicates_as_str),
            )

    def _check_duplicated_packaging_barcodes(self, barcodes_within_company, company_id):
        packaging_domain = self._get_barcode_search_domain(
            barcodes_within_company,
            company_id,
        )
        if self.env["product.uom"].sudo().search_count(packaging_domain, limit=1):
            raise ValidationError(self.env._("A packaging already uses the barcode"))
