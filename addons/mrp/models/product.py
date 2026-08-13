# Part of Odoo. See LICENSE file for full copyright and licensing details.

import collections
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.stock.const import PY_OPERATORS


class ProductTemplate(models.Model):
    _inherit = "product.template"

    bom_line_ids = fields.One2many("mrp.bom.line", "product_tmpl_id", "BoM Components")
    bom_ids = fields.One2many("mrp.bom", "product_tmpl_id", "Bill of Materials")
    bom_count = fields.Integer(
        "# Bill of Material", compute="_compute_bom_count", compute_sudo=False
    )
    used_in_bom_count = fields.Integer(
        "# of BoM Where is Used",
        compute="_compute_used_in_bom_count",
        compute_sudo=False,
    )
    mrp_product_qty = fields.Float(
        "Manufactured",
        digits="Product Unit",
        compute="_compute_mrp_product_qty",
        compute_sudo=False,
    )
    is_kits = fields.Boolean(compute="_compute_is_kits", search="_search_is_kits")

    def _compute_bom_count(self):
        # Two grouped queries instead of one `search_count` per template. A BoM
        # reached both ways -- it produces the template and lists it as a
        # by-product -- must still count once, hence the set union.
        bom_ids_by_template = collections.defaultdict(set)
        for template, bom_ids in self.env["mrp.bom"]._read_group(
            [("product_tmpl_id", "in", self.ids)],
            ["product_tmpl_id"],
            ["id:array_agg"],
        ):
            bom_ids_by_template[template.id].update(bom_ids)
        for product, bom_ids in self.env["mrp.bom.byproduct"]._read_group(
            [("product_id.product_tmpl_id", "in", self.ids)],
            ["product_id"],
            ["bom_id:array_agg"],
        ):
            bom_ids_by_template[product.product_tmpl_id.id].update(bom_ids)
        for product in self:
            product.bom_count = len(bom_ids_by_template.get(product.id, ()))

    @api.depends_context("company")
    def _compute_is_kits(self):
        domain = [
            ("product_tmpl_id", "in", self.ids),
            ("type", "=", "phantom"),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
        ]
        bom_mapping = (
            self.env["mrp.bom"].sudo().search_read(domain, ["product_tmpl_id"])
        )
        kits_ids = {b["product_tmpl_id"][0] for b in bom_mapping}
        for template in self:
            template.is_kits = template.id in kits_ids

    def _search_is_kits(self, operator, value):
        if operator != "in":
            return NotImplemented
        bom_tmpl_query = (
            self.env["mrp.bom"]
            .sudo()
            ._search(
                [
                    ("company_id", "in", [False] + self.env.companies.ids),
                    ("type", "=", "phantom"),
                    ("active", "=", True),
                ]
            )
        )
        return [("id", "in", bom_tmpl_query.subselect("product_tmpl_id"))]

    def _compute_show_qty_status_button(self):
        super()._compute_show_qty_status_button()
        for template in self:
            if template.is_kits:
                template.show_on_hand_qty_status_button = (
                    template.product_variant_count <= 1
                )
                template.show_forecasted_qty_status_button = False

    def _should_open_product_quants(self):
        return super()._should_open_product_quants() or self.is_kits

    def _compute_used_in_bom_count(self):
        # One grouped query instead of one `search_count` per template. Distinct
        # BoMs, since a BoM may list the same product on several lines.
        counts = {
            template.id: count
            for template, count in self.env["mrp.bom.line"]._read_group(
                [("product_tmpl_id", "in", self.ids)],
                ["product_tmpl_id"],
                ["bom_id:count_distinct"],
            )
        }
        for template in self:
            template.used_in_bom_count = counts.get(template.id, 0)

    def write(self, vals):
        if "active" in vals:
            self.filtered(lambda p: p.active != vals["active"]).with_context(
                active_test=False
            ).bom_ids.write({"active": vals["active"]})
        return super().write(vals)

    def action_used_in_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_bom_form_action")
        action["domain"] = [("bom_line_ids.product_tmpl_id", "=", self.id)]
        return action

    def _compute_mrp_product_qty(self):
        for template in self:
            template.mrp_product_qty = template.uom_id.round(
                sum(template.mapped("product_variant_ids").mapped("mrp_product_qty"))
            )

    def action_view_mos(self):
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        action["domain"] = [
            ("state", "=", "done"),
            (
                "move_finished_ids",
                "any",
                [
                    ("product_tmpl_id", "in", self.ids),
                    ("state", "!=", "cancel"),
                    ("picked", "=", True),
                ],
            ),
        ]
        action["context"] = {
            "search_default_filter_plan_date": 1,
        }
        return action

    def action_archive(self):
        filtered_products = (
            self.env["mrp.bom.line"]
            .search(
                [
                    ("product_id", "in", self.product_variant_ids.ids),
                    ("bom_id.active", "=", True),
                ]
            )
            .product_id.mapped("display_name")
        )
        res = super().action_archive()
        if filtered_products:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _(
                        "Note that product(s): '%s' is/are still linked to active Bill of Materials, "
                        "which means that the product can still be used on it/them.",
                        filtered_products,
                    ),
                    "type": "warning",
                    "sticky": True,  # True/False will display for few seconds if false
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return res

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("mrp.menu_mrp_root").id
        ]


class ProductProduct(models.Model):
    _inherit = "product.product"

    variant_bom_ids = fields.One2many("mrp.bom", "product_id", "BOM Product Variants")
    bom_line_ids = fields.One2many("mrp.bom.line", "product_id", "BoM Components")
    bom_count = fields.Integer(
        "# Bill of Material", compute="_compute_bom_count", compute_sudo=False
    )
    used_in_bom_count = fields.Integer(
        "# BoM Where Used", compute="_compute_used_in_bom_count", compute_sudo=False
    )
    mrp_product_qty = fields.Float(
        "Manufactured",
        digits="Product Unit",
        compute="_compute_mrp_product_qty",
        compute_sudo=False,
    )
    is_kits = fields.Boolean(compute="_compute_is_kits", search="_search_is_kits")

    # Catalog related fields
    product_catalog_product_is_in_bom = fields.Boolean(
        compute="_compute_product_is_in_bom_and_mo",
        search="_search_product_is_in_bom",
    )

    product_catalog_product_is_in_mo = fields.Boolean(
        compute="_compute_product_is_in_bom_and_mo",
        search="_search_product_is_in_mo",
    )

    def _compute_bom_count(self):
        # Three grouped queries instead of one `search_count` per variant --
        # the same treatment `product.template` already had, which this half of
        # the pair was left out of. A BoM reachable by more than one route
        # (variant BoM, template BoM, by-product) must still count once, hence
        # the set union.
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
    def _compute_is_kits(self):
        domain = [
            "&",
            "&",
            ("type", "=", "phantom"),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
            "|",
            ("product_id", "in", self.ids),
            "&",
            ("product_id", "=", False),
            ("product_tmpl_id", "in", self.product_tmpl_id.ids),
        ]
        bom_mapping = (
            self.env["mrp.bom"]
            .sudo()
            .search_read(domain, ["product_tmpl_id", "product_id"])
        )
        kits_template_ids = set()
        kits_product_ids = set()
        for bom_data in bom_mapping:
            if bom_data["product_id"]:
                kits_product_ids.add(bom_data["product_id"][0])
            else:
                kits_template_ids.add(bom_data["product_tmpl_id"][0])
        for product in self:
            product.is_kits = (
                product.id in kits_product_ids
                or product.product_tmpl_id.id in kits_template_ids
            )

    def _search_is_kits(self, operator, value):
        if operator != "in":
            return NotImplemented
        bom_tmpl_query = (
            self.env["mrp.bom"]
            .sudo()
            ._search(
                [
                    ("company_id", "in", [False] + self.env.companies.ids),
                    ("active", "=", True),
                    ("type", "=", "phantom"),
                    ("product_id", "=", False),
                ]
            )
        )
        bom_product_query = (
            self.env["mrp.bom"]
            .sudo()
            ._search(
                [
                    ("company_id", "in", [False] + self.env.companies.ids),
                    ("type", "=", "phantom"),
                    ("product_id", "!=", False),
                ]
            )
        )
        return [
            "|",
            ("product_tmpl_id", "in", bom_tmpl_query.subselect("product_tmpl_id")),
            ("id", "in", bom_product_query.subselect("product_id")),
        ]

    def _compute_show_qty_status_button(self):
        super()._compute_show_qty_status_button()
        for product in self:
            if product.is_kits:
                product.show_on_hand_qty_status_button = True
                product.show_forecasted_qty_status_button = False

    def _compute_used_in_bom_count(self):
        # One grouped query instead of one `search_count` per variant. Distinct
        # BoMs, since a BoM may list the same component on several lines.
        counts = {
            product.id: count
            for product, count in self.env["mrp.bom.line"]._read_group(
                [("product_id", "in", self.ids)],
                ["product_id"],
                ["bom_id:count_distinct"],
            )
        }
        for product in self:
            product.used_in_bom_count = counts.get(product.id, 0)

    @api.depends_context("order_id")
    def _compute_product_is_in_bom_and_mo(self):
        # Just to enable the _search method
        self.product_catalog_product_is_in_bom = False
        self.product_catalog_product_is_in_mo = False

    def _search_product_is_in_bom(self, operator, value):
        if operator != "in":
            return NotImplemented
        product_ids = (
            self.env["mrp.bom.line"]
            .search(
                [
                    ("bom_id", "=", self.env.context.get("order_id", "")),
                ]
            )
            .product_id.ids
        )
        return [("id", operator, product_ids)]

    def _search_product_is_in_mo(self, operator, value):
        if operator != "in":
            return NotImplemented
        product_ids = (
            self.env["mrp.production"]
            .search(
                [
                    ("id", "in", [self.env.context.get("order_id", "")]),
                ]
            )
            .move_raw_ids.product_id.ids
        )
        return [("id", operator, product_ids)]

    def write(self, vals):
        if "active" in vals:
            self.filtered(lambda p: p.active != vals["active"]).with_context(
                active_test=False
            ).variant_bom_ids.write({"active": vals["active"]})
        return super().write(vals)

    def _get_total_routes(self):
        routes = super()._get_total_routes()
        if self.bom_ids:
            manufacture_routes = (
                self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
            )
            routes |= manufacture_routes
        return routes

    def _get_components(self):
        """The storable components of a kit; the product itself otherwise."""
        self.ensure_one()
        bom_kit = self.env["mrp.bom"]._bom_find(self, bom_type="phantom")[self]
        if not bom_kit:
            return super()._get_components()
        __, bom_sub_lines = bom_kit.explode(self, 1)
        return self.browse().union(
            *(
                bom_line.product_id
                for bom_line, __ in bom_sub_lines
                if bom_line.product_id.is_storable
            )
        )

    def action_used_in_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_bom_form_action")
        action["domain"] = [("bom_line_ids.product_id", "=", self.id)]
        return action

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
            if not product.id:
                product.mrp_product_qty = 0.0
                continue
            product.mrp_product_qty = product.uom_id.round(
                mapped_data.get(product.id, 0)
            )

    def _prepare_quantities_vals(
        self,
        lot_id,
        owner_id,
        package_id,
        from_date=False,
        to_date=False,
        location_domains=None,
    ):
        """When the product is a kit, this override computes the fields :
         - 'qty_available_virtual'
         - 'qty_available'
         - 'qty_incoming'
         - 'qty_outgoing'
         - 'qty_free'

        This override is used to get the correct quantities of products
        with 'phantom' as BoM type.
        """
        bom_kits = self.env["mrp.bom"]._bom_find(self, bom_type="phantom")
        kits = self.filtered(bom_kits.get)
        regular_products = self - kits
        res = (
            super(ProductProduct, regular_products)._prepare_quantities_vals(
                lot_id,
                owner_id,
                package_id,
                from_date=from_date,
                to_date=to_date,
                location_domains=location_domains,
            )
            if regular_products
            else {}
        )
        qties = self.env.context.get("mrp_compute_quantities", {})
        qties.update(res)
        # pre-compute bom lines and identify missing kit components to prefetch
        bom_sub_lines_per_kit = {}
        prefetch_component_ids = set()
        for product in bom_kits:
            __, bom_sub_lines = bom_kits[product].explode(product, 1)
            bom_sub_lines_per_kit[product] = bom_sub_lines
            for bom_line, __ in bom_sub_lines:
                if bom_line.product_id.id not in qties:
                    prefetch_component_ids.add(bom_line.product_id.id)
        # compute kit quantities
        for product in bom_kits:
            bom_sub_lines = bom_sub_lines_per_kit[product]
            # group lines by component
            bom_sub_lines_grouped = collections.defaultdict(list)
            for info in bom_sub_lines:
                bom_sub_lines_grouped[info[0].product_id].append(info)
            ratios_virtual_available = []
            ratios_qty_available = []
            ratios_incoming_qty = []
            ratios_outgoing_qty = []
            ratios_free_qty = []

            for component, component_bom_lines in bom_sub_lines_grouped.items():
                component = component.with_context(
                    mrp_compute_quantities=qties
                ).with_prefetch(prefetch_component_ids)
                qty_per_kit = 0
                for bom_line, bom_line_data in component_bom_lines:
                    if not component.is_storable or bom_line.product_uom_id.is_zero(
                        bom_line_data["qty"]
                    ):
                        # BoMs allow components with 0 qty (optional ones): skip them to
                        # avoid a division by zero. Non-storable products are skipped for
                        # the same reason, their available qty being 0.
                        continue
                    uom_qty_per_kit = (
                        bom_line_data["qty"] / bom_line_data["original_qty"]
                    )
                    qty_per_kit += bom_line.product_uom_id._compute_quantity_estimate(
                        uom_qty_per_kit,
                        bom_line.product_id.uom_id,
                        round=False,
                    )
                if not qty_per_kit:
                    continue
                component_res = (
                    qties.get(component.id)
                    if component.id in qties
                    else {
                        "qty_available_virtual": component.uom_id.round(
                            component.qty_available_virtual
                        ),
                        "qty_available": component.uom_id.round(
                            component.qty_available
                        ),
                        "qty_incoming": component.uom_id.round(component.qty_incoming),
                        "qty_outgoing": component.uom_id.round(component.qty_outgoing),
                        "qty_free": component.uom_id.round(component.qty_free),
                    }
                )
                ratios_virtual_available.append(
                    component.uom_id.round(
                        component_res["qty_available_virtual"] / qty_per_kit,
                        rounding_method="DOWN",
                    )
                )
                ratios_qty_available.append(
                    component.uom_id.round(
                        component_res["qty_available"] / qty_per_kit,
                        rounding_method="DOWN",
                    )
                )
                ratios_incoming_qty.append(
                    component.uom_id.round(
                        component_res["qty_incoming"] / qty_per_kit,
                        rounding_method="DOWN",
                    )
                )
                ratios_outgoing_qty.append(
                    component.uom_id.round(
                        component_res["qty_outgoing"] / qty_per_kit,
                        rounding_method="DOWN",
                    )
                )
                ratios_free_qty.append(
                    component.uom_id.round(
                        component_res["qty_free"] / qty_per_kit, rounding_method="DOWN"
                    )
                )
            if (
                bom_sub_lines and ratios_virtual_available
            ):  # Guard against an all-consumable bom: at least one ratio must be present.
                res[product.id] = {
                    # Round in the KIT's own UoM (not the last-iterated `component`) and
                    # DOWN before flooring to whole kits: rounding a fractional shortfall
                    # up would over-report the number of buildable kits.
                    "qty_available_virtual": product.uom_id.round(
                        min(ratios_virtual_available) * bom_kits[product].product_qty,
                        rounding_method="DOWN",
                    )
                    // 1,
                    "qty_available": product.uom_id.round(
                        min(ratios_qty_available) * bom_kits[product].product_qty,
                        rounding_method="DOWN",
                    )
                    // 1,
                    "qty_incoming": product.uom_id.round(
                        min(ratios_incoming_qty) * bom_kits[product].product_qty,
                        rounding_method="DOWN",
                    )
                    // 1,
                    "qty_outgoing": product.uom_id.round(
                        min(ratios_outgoing_qty) * bom_kits[product].product_qty,
                        rounding_method="DOWN",
                    )
                    // 1,
                    "qty_free": product.uom_id.round(
                        min(ratios_free_qty) * bom_kits[product].product_qty,
                        rounding_method="DOWN",
                    )
                    // 1,
                }
            else:
                res[product.id] = {
                    "qty_available_virtual": 0,
                    "qty_available": 0,
                    "qty_incoming": 0,
                    "qty_outgoing": 0,
                    "qty_free": 0,
                }

        return res

    def action_view_bom(self):
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.product_open_bom")
        template_ids = self.mapped("product_tmpl_id").ids
        # bom specific to this variant or global to template or that contains the product as a byproduct
        action["context"] = {
            "default_product_tmpl_id": template_ids[0],
            "default_product_id": (
                self.env.user.has_group("product.group_product_variant") and self.ids[0]
            )
            or False,
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

    def action_view_mos(self):
        action = self.product_tmpl_id.action_view_mos()
        action["domain"] = [
            ("state", "=", "done"),
            (
                "move_finished_ids",
                "any",
                [
                    ("product_id", "in", self.ids),
                    ("state", "!=", "cancel"),
                    ("picked", "=", True),
                ],
            ),
        ]
        return action

    def action_view_quants(self):
        bom_kits = self.env["mrp.bom"]._bom_find(self, bom_type="phantom")
        components = self - self.env["product.product"].concat(*list(bom_kits.keys()))
        for product in bom_kits:
            _boms, bom_sub_lines = bom_kits[product].explode(product, 1)
            components |= self.env["product.product"].concat(
                *[l[0].product_id for l in bom_sub_lines]
            )
        res = super(ProductProduct, components).action_view_quants()
        if bom_kits:
            res["context"].pop("default_product_tmpl_id", None)
        return res

    def _match_all_variant_values(self, product_template_attribute_value_ids):
        """It currently checks that all variant values (`product_template_attribute_value_ids`)
        are in the product (`self`).

        If multiple values are encoded for the same attribute line, only one of
        them has to be found on the variant.
        """
        self.ensure_one()
        # The intersection of the values of the product and those of the line satisfy:
        # * the number of items equals the number of attributes (since a product cannot
        #   have multiple values for the same attribute),
        # * the attributes are a subset of the attributes of the line.
        return len(
            self.product_template_attribute_value_ids
            & product_template_attribute_value_ids
        ) == len(product_template_attribute_value_ids.attribute_id)

    def _count_returned_sn_products_domain(self, sn_lot, or_domains):
        or_domains.append(
            [
                ("production_id", "=", False),
                ("location_id.usage", "=", "production"),
                ("move_id.unbuild_id", "!=", False),
            ]
        )
        return super()._count_returned_sn_products_domain(sn_lot, or_domains)

    def _get_phantom_bom_products(self):
        """Products manufactured as a kit (phantom BoM). Their quantity is derived from
        their components, so quantity searches must consider them explicitly.

        Scoped to the environment's companies: an unscoped search handed back
        kits the caller cannot even read, and every one of them costs a full kit
        explosion downstream in `_search_qty_available_new`.
        """
        kit_boms = self.env["mrp.bom"].search(
            [
                ("type", "=", "phantom"),
                ("company_id", "in", [False, *self.env.companies.ids]),
            ]
        )
        # `product_variant_ids` in one prefetch rather than one read per BoM.
        return (
            kit_boms.product_id
            | (
                kit_boms.filtered(lambda bom: not bom.product_id)
            ).product_tmpl_id.product_variant_ids
        )

    def _get_quantity_search_candidates(self, location_domains=None):
        # Kits can have a non-zero quantity without any quants/moves of their own (it comes
        # from their components), so they must be added to the candidate set.
        return (
            super()._get_quantity_search_candidates(location_domains=location_domains)
            | self._get_phantom_bom_products()
        )

    def _search_qty_available_new(
        self, operator, value, lot_id=False, owner_id=False, package_id=False
    ):
        """extending the method in stock's product.product to take into account kits"""
        op = PY_OPERATORS.get(operator)
        if not op:
            return NotImplemented
        product_ids = super()._search_qty_available_new(
            operator, value, lot_id, owner_id, package_id
        )
        kits = self._get_phantom_bom_products()
        if not kits:
            return product_ids
        # A kit's quantity is derived from its components, so it has to be
        # evaluated in Python -- but once for the whole set. Reading
        # `qty_available` off each record in turn made every kit its own
        # explosion and its own round trip; one `mapped` lets the ORM batch the
        # component reads behind them.
        matching, not_matching = set(), set()
        for product, qty_available in zip(
            kits, kits.mapped("qty_available"), strict=True
        ):
            (matching if op(qty_available, value) else not_matching).add(product.id)
        # A set from the start: this rebuilt a list with `pop(index(...))`, which
        # is quadratic, and then `list(set(...))` threw away super()'s ordering
        # anyway.
        return list((set(product_ids) - not_matching) | matching)

    def action_archive(self):
        filtered_products = (
            self.env["mrp.bom.line"]
            .search([("product_id", "in", self.ids), ("bom_id.active", "=", True)])
            .product_id.mapped("display_name")
        )
        res = super().action_archive()
        if filtered_products:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _(
                        "Note that product(s): '%s' is/are still linked to active Bill of Materials, "
                        "which means that the product can still be used on it/them.",
                        filtered_products,
                    ),
                    "type": "warning",
                    "sticky": True,  # True/False will display for few seconds if false
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return res

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("mrp.menu_mrp_root").id
        ]

    def _update_uom(self, to_uom_id):
        # mrp.bom, mrp.bom.line and mrp.production carried three copies of the
        # same fifteen lines, differing only in the model, what identifies the
        # product on it, and the domain that selects its rows.
        for model, product_field, domain in (
            (
                "mrp.bom",
                "product_tmpl_id",
                [("product_tmpl_id", "in", self.product_tmpl_id.ids)],
            ),
            ("mrp.bom.line", "product_id", [("product_id", "in", self.ids)]),
            ("mrp.production", "product_id", [("product_id", "in", self.ids)]),
        ):
            for uom, product, records in self.env[model]._read_group(
                domain, ["product_uom_id", product_field], ["id:recordset"]
            ):
                template = (
                    product
                    if product._name == "product.template"
                    else product.product_tmpl_id
                )
                if template.uom_id != uom:
                    raise UserError(
                        _(
                            "As other units of measure (ex : %(problem_uom)s) "
                            "than %(uom)s have already been used for this product, the change of unit of measure can not be done."
                            "If you want to change it, please archive the product and create a new one.",
                            problem_uom=uom.name,
                            uom=template.uom_id.name,
                        )
                    )
                records.product_uom_id = to_uom_id

        return super()._update_uom(to_uom_id)
