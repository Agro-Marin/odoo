import collections
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

from odoo.addons.stock.const import PY_OPERATORS, QUANTITY_FIELDS


class ProductProduct(models.Model):
    _name = "product.product"
    _inherit = ["product.product", "mixin.mrp.product"]

    _mrp_product_field = "product_id"
    _mrp_bom_field = "variant_bom_ids"

    variant_bom_ids = fields.One2many("mrp.bom", "product_id", "BOM Product Variants")
    bom_line_ids = fields.One2many("mrp.bom.line", "product_id", "BoM Components")

    product_catalog_product_is_in_bom = fields.Boolean(
        compute="_compute_product_is_in_bom_and_mo",
        search="_search_product_is_in_bom",
    )

    product_catalog_product_is_in_mo = fields.Boolean(
        compute="_compute_product_is_in_bom_and_mo",
        search="_search_product_is_in_mo",
    )

    def _get_mrp_variants(self):
        return self

    # No `@api.depends` -- see the measurement on
    # `product.template._compute_bom_count`.
    def _compute_bom_count(self):
        bom_ids_by_product = collections.defaultdict(set)
        bom_ids_by_template = collections.defaultdict(set)
        Bom = self.env["mrp.bom"]
        for product, bom_ids in Bom._read_group(
            [("product_id", "in", self.ids)], ["product_id"], ["id:array_agg"]
        ):
            bom_ids_by_product[product.id].update(bom_ids)
        for template, bom_ids in Bom._read_group(
            [
                ("product_id", "=", False),
                ("product_tmpl_id", "in", self.product_tmpl_id.ids),
            ],
            ["product_tmpl_id"],
            ["id:array_agg"],
        ):
            bom_ids_by_template[template.id].update(bom_ids)
        for product, bom_ids in self.env["mrp.bom.byproduct"]._read_group(
            [("product_id", "in", self.ids)], ["product_id"], ["bom_id:array_agg"]
        ):
            bom_ids_by_product[product.id].update(bom_ids)
        for product in self:
            product.bom_count = len(
                bom_ids_by_product[product.id]
                | bom_ids_by_template[product.product_tmpl_id.id]
            )

    @api.depends_context("company")
    def _compute_is_kit(self):
        # A variant is a kit through a BoM of its own, or through one its
        # template carries for every variant (`product_id` unset).
        Bom = self.env["mrp.bom"].sudo()
        domain = Bom._get_kit_domain() & (
            Domain("product_id", "in", self.ids)
            | (
                Domain("product_id", "=", False)
                & Domain("product_tmpl_id", "in", self.product_tmpl_id.ids)
            )
        )
        kit_product_ids = set()
        kit_template_ids = set()
        for product, template in Bom._read_group(
            domain, ["product_id", "product_tmpl_id"]
        ):
            if product:
                kit_product_ids.add(product.id)
            else:
                kit_template_ids.add(template.id)
        for product in self:
            product.is_kit = (
                product.id in kit_product_ids
                or product.product_tmpl_id.id in kit_template_ids
            )

    def _search_is_kit(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        Bom = self.env["mrp.bom"].sudo()
        kit_domain = Bom._get_kit_domain()
        bom_tmpl_query = Bom._search(kit_domain & Domain("product_id", "=", False))
        bom_product_query = Bom._search(kit_domain & Domain("product_id", "!=", False))
        return [
            "|",
            ("product_tmpl_id", "in", bom_tmpl_query.subselect("product_tmpl_id")),
            ("id", "in", bom_product_query.subselect("product_id")),
        ]

    def action_archive(self):
        still_used = self._get_still_used_bom_lines()
        res = super().action_archive()
        return still_used._get_still_used_notification() or res

    def _compute_show_qty_status_button(self):
        super()._compute_show_qty_status_button()
        for product in self:
            if product.is_kit:
                product.show_on_hand_qty_status_button = True
                product.show_forecasted_qty_status_button = False

    @api.depends_context("order_id")
    def _compute_product_is_in_bom_and_mo(self):
        # Both fields exist for the product catalog, which reads them through
        # their `search` methods only; the catalog kanban never renders the
        # value, so there is nothing to compute per record.
        self.product_catalog_product_is_in_bom = False
        self.product_catalog_product_is_in_mo = False

    def _search_product_is_in_bom(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        bom = self.env["mrp.bom"].browse(self.env.context.get("order_id"))
        return [("id", "in", bom.bom_line_ids.product_id.ids)]

    def _search_product_is_in_mo(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        # `browse().exists()`, not a `search` on the id: the context key comes
        # from the catalog client, so it can name a record that is gone.
        production = (
            self.env["mrp.production"].browse(self.env.context.get("order_id")).exists()
        )
        return [("id", "in", production.move_raw_ids.product_id.ids)]

    def _get_total_routes_by_product(self):
        result = super()._get_total_routes_by_product()
        manufacture_routes = (
            self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
        )
        if not manufacture_routes:
            return result
        # `_bom_find`, not `product.bom_ids`: the latter is the *template's*
        # o2m, so a variant with no BoM of its own claimed the Manufacture route
        # from a sibling variant's BoM, and a kit -- which `stock_rule.run`
        # explodes rather than manufactures -- claimed it too.
        #
        # Both consumers (`stock.warehouse.orderpoint._compute_rules`,
        # `stock.replenishment.report._get_projected_shortages`) use this dict
        # only inside a memoisation key: `_get_rules_from_location` is never
        # given the routes and reads the product's own. So no rule set changes
        # here -- measured, an orderpoint on the BoM-less sibling still resolves
        # to `['manufacture']`, from the warehouse. What changes is that two
        # variants whose real rules differ stop colliding on one key.
        boms = self.env["mrp.bom"]._bom_find(
            self, bom_type="normal", company_id=self.env.company.id
        )
        for product in self:
            if boms.get(product):
                result[product.id] |= manufacture_routes
        return result

    def _get_components(self):
        self.ensure_one()
        bom_kit = self.env["mrp.bom"]._bom_find(
            self, bom_type="phantom", company_id=self.env.company.id
        )[self]
        if not bom_kit:
            return super()._get_components()
        __, bom_sub_lines = bom_kit._explode(self, 1)
        return self.browse().union(
            *(
                bom_line.product_id
                for bom_line, __ in bom_sub_lines
                if bom_line.product_id.is_storable
            )
        )

    def _compute_mrp_product_qty(self):
        date_from = fields.Datetime.to_string(
            fields.Datetime.now() - timedelta(days=365)
        )
        domain = [
            ("production_id.state", "=", "done"),
            ("product_id", "in", self.ids),
            ("production_id.date_start", ">", date_from),
            ("state", "!=", "cancel"),
            ("picked", "=", True),
        ]
        read_group_res = self.env["stock.move"]._read_group(
            domain, ["product_id", "product_uom_id"], ["quantity:sum"]
        )
        mapped_data = collections.defaultdict(float)
        for product, uom, qty in read_group_res:
            if uom != product.uom_id:
                qty = uom._compute_quantity_estimate(qty, product.uom_id)
            mapped_data[product.id] += qty
        for product in self:
            product.mrp_product_qty = product.uom_id.round(
                mapped_data.get(product.id, 0)
            )

    def _prepare_quantities_vals(self, filters, location_domains=None):
        # `company_id`, like `is_kit`: without it a phantom BoM owned by
        # another company exploded here anyway, so a product whose `is_kit`
        # cell read False on the very same form reported its components'
        # availability instead of its own.
        bom_kits = (
            self.env["mrp.bom"]
            .sudo()
            ._bom_find(self, bom_type="phantom", company_id=self.env.company.id)
        )
        kits = self.filtered(bom_kits.get)
        regular_products = self - kits
        res = (
            super(ProductProduct, regular_products)._prepare_quantities_vals(
                filters, location_domains=location_domains
            )
            if regular_products
            else {}
        )
        if not kits:
            return res
        # One memo per top-level read, threaded through the context: a kit
        # nested inside a kit re-enters this method through the recursive call
        # below and fills the same dict, so two kits sharing a component pay for
        # it once and the recursion terminates.
        qties = self.env.context.get("mrp_compute_quantities", {})
        qties.update(res)
        exploded = {
            product: bom_kits[product]._explode(product, 1)[1] for product in kits
        }
        # Resolve every component of every kit in ONE call, and resolve it with
        # the caller's own `filters` and `location_domains`. Reading
        # `component.qty_available` instead -- which is what this did -- goes
        # back through `_compute_quantities`, which rebuilds both from the
        # context: the scope a caller passed as an argument was dropped, and
        # `_search_quantity_totals` is a caller that passes one.
        components = self.browse(
            {
                bom_line.product_id.id
                for bom_sub_lines in exploded.values()
                for bom_line, __ in bom_sub_lines
            }
            - set(qties)
        )
        if components:
            qties.update(
                components.with_env(self.env)
                .with_context(mrp_compute_quantities=qties)
                ._prepare_quantities_vals(filters, location_domains=location_domains)
            )
        for product in kits:
            res[product.id] = product._prepare_kit_quantities_vals(
                bom_kits[product], exploded[product], qties
            )
        return res

    def _prepare_kit_quantities_vals(self, bom_kit, bom_sub_lines, qties):
        """How many whole kits the scarcest component allows, per quantity field.

        ``bom_sub_lines`` is ``bom_kit._explode(self, 1)[1]``, so every quantity
        in it is what *one BoM* consumes, and one BoM yields
        ``bom_kit.product_qty`` kits. ``qties`` already holds every component's
        quantities, resolved in one batch by ``_prepare_quantities_vals``.

        The per-component ratio is deliberately left unrounded. Rounding it
        DOWN at the 'Product Unit' precision -- which is what this did -- floors
        a count of *BoMs* before it is scaled to kits, so every kit the last
        partial BoM would have yielded is lost: 201 components at 200 per BoM
        for a BoM of 1000 kits reported 1000 instead of 1005, and at 0 decimals
        3 components at 2 per BoM for a BoM of 2 kits reported 2 instead of 3.
        The final `round(..., "DOWN") // 1` still floors the answer to whole
        kits; the round is what keeps float noise (2.9999999996) from flooring
        to 2.
        """
        self.ensure_one()
        lines_by_component = collections.defaultdict(list)
        for bom_line, bom_line_data in bom_sub_lines:
            lines_by_component[bom_line.product_id].append((bom_line, bom_line_data))
        ratios = collections.defaultdict(list)
        for component, component_lines in lines_by_component.items():
            component = component.with_env(self.env)
            qty_per_bom = 0
            for bom_line, bom_line_data in component_lines:
                if not component.is_storable or bom_line.product_uom_id.is_zero(
                    bom_line_data["qty"]
                ):
                    continue
                qty_per_bom += bom_line.product_uom_id._compute_quantity_estimate(
                    bom_line_data["qty"] / bom_line_data["original_qty"],
                    bom_line.product_id.uom_id,
                    round=False,
                )
            if not qty_per_bom:
                continue
            # Every component was resolved into `qties` by the caller; a miss
            # would be a component the explosion did not report.
            component_vals = qties[component.id]
            for field in QUANTITY_FIELDS:
                ratios[field].append(component_vals[field] / qty_per_bom)
        if not ratios:
            # No storable component with a non-zero quantity: nothing bounds
            # the kit, and "unbounded" is not a stock figure.
            return dict.fromkeys(QUANTITY_FIELDS, 0)
        return {
            field: self.uom_id.round(
                min(values) * bom_kit.product_qty, rounding_method="DOWN"
            )
            // 1
            for field, values in ratios.items()
        }

    def action_view_bom(self):
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.product_open_bom")
        template_ids = self.product_tmpl_id.ids
        action["context"] = {
            "default_product_tmpl_id": template_ids[0] if template_ids else False,
            "default_product_id": (
                self.ids[0]
                if self.ids and self.env.user.has_group("product.group_product_variant")
                else False
            ),
        }
        action["domain"] = [
            "|",
            "|",
            ("byproduct_ids.product_id", "in", self.ids),
            ("product_id", "in", self.ids),
            "&",
            ("product_id", "=", False),
            ("product_tmpl_id", "in", template_ids),
        ]
        return action

    def action_view_quants(self):
        bom_kits = self.env["mrp.bom"]._bom_find(
            self, bom_type="phantom", company_id=self.env.company.id
        )
        components = self - self.browse().union(*bom_kits)
        for product, bom_kit in bom_kits.items():
            __, bom_sub_lines = bom_kit._explode(product, 1)
            components |= self.browse().union(
                *(bom_line.product_id for bom_line, __ in bom_sub_lines)
            )
        res = super(ProductProduct, components).action_view_quants()
        if bom_kits:
            res["context"].pop("default_product_tmpl_id", None)
        return res

    def _match_all_variant_values(self, product_template_attribute_value_ids):
        self.ensure_one()
        return len(
            self.product_template_attribute_value_ids
            & product_template_attribute_value_ids
        ) == len(product_template_attribute_value_ids.attribute_id)

    def _get_phantom_bom_products(self):
        """Every product that explodes, for the active company.

        Through `is_kit`, so this and the field cannot drift: the search method
        already resolves both halves -- a BoM of the variant's own and one the
        template carries for every variant -- as two subselects in one query.
        What it replaces loaded every kit BoM in the database as records, then
        read `product_variant_ids` off each template-level one to expand it in
        Python.
        """
        return self.search([("is_kit", "=", True)])

    def _get_quantity_search_candidates(self, location_domains=None):
        return (
            super()._get_quantity_search_candidates(location_domains=location_domains)
            | self._get_phantom_bom_products()
        )

    def _search_qty_available_from_quants(self, operator, value, filters=None):
        op = PY_OPERATORS.get(operator)
        if not op:
            return NotImplemented
        product_ids = super()._search_qty_available_from_quants(
            operator, value, filters
        )
        if product_ids is NotImplemented:
            return NotImplemented
        kits = self._get_phantom_bom_products()
        if not kits:
            return product_ids
        # A kit holds no stock of its own: whatever the quant scan said about
        # one, its components decide the answer.
        matching, not_matching = set(), set()
        for product, qty_available in zip(
            kits, kits.mapped("qty_available"), strict=True
        ):
            (matching if op(qty_available, value) else not_matching).add(product.id)
        return sorted((set(product_ids) - not_matching) | matching)

    def _update_uom(self, to_uom_id):
        # Every mrp model that stamps a unit beside a product quantity. A model
        # missing from this table keeps its old unit while the product moves to
        # the new one, which silently reinterprets the quantity beside it --
        # and skips `_restamp_uom`'s refusal to convert at all when a document
        # already used a different unit.
        for model, product_field, domain, context in (
            (
                "mrp.bom",
                "product_tmpl_id",
                [("product_tmpl_id", "in", self.product_tmpl_id.ids)],
                None,
            ),
            (
                "mrp.bom.line",
                "product_id",
                [("product_id", "in", self.ids)],
                {"mail_notrack": True},
            ),
            (
                "mrp.bom.byproduct",
                "product_id",
                [("product_id", "in", self.ids)],
                {"mail_notrack": True},
            ),
            ("mrp.production", "product_id", [("product_id", "in", self.ids)], None),
            ("mrp.unbuild", "product_id", [("product_id", "in", self.ids)], None),
            # Deliberately absent: `mrp.workcenter.capacity`. Its
            # `product_uom_id` is not a stamp of the product's own unit, it is
            # the unit the capacity is *rated* in -- `_get_capacity`'s ranked
            # lookup explicitly tries `(product, caller's unit)` and the UNIQUE
            # index is `(workcenter_id, product_id, product_uom_id)`, so several
            # rows per product in different units are legal. Restamping them
            # would collide on that index, and `_restamp_uom`'s guard would
            # refuse the product's unit change outright for a configuration
            # that is correct -- verified: two rows, Units and Dozens, made
            # `uom_id = dozen` raise "Other units of measure ... have already
            # been used". Nothing is stale either: the capacity value is
            # expressed in that unit and `_get_capacity` converts it.
        ):
            self._restamp_uom(
                model,
                to_uom_id,
                domain=domain,
                product_field=product_field,
                context=context,
            )
        return super()._update_uom(to_uom_id)
