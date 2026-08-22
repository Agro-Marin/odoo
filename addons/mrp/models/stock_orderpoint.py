from collections import defaultdict
from datetime import datetime, time
from itertools import batched

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    show_bom = fields.Boolean("Show BoM column", compute="_compute_show_bom")
    bom_id = fields.Many2one(
        "mrp.bom",
        string="Bill of Materials",
        check_company=True,
        domain="[('type', '=', 'normal'), '&', '|', ('company_id', '=', company_id), ('company_id', '=', False), '|', ('product_id', '=', product_id), '&', ('product_id', '=', False), ('product_tmpl_id', '=', product_tmpl_id)]",
        inverse="_inverse_bom_id",
    )
    bom_id_placeholder = fields.Char(compute="_compute_bom_id_placeholder")
    effective_bom_id = fields.Many2one(
        "mrp.bom",
        string="Effective Bill of Materials",
        search="_search_effective_bom_id",
        compute="_compute_effective_bom_id",
        store=False,
        help="Either the Bill of Materials set directly or the one computed to be used by this replenishment",
    )

    def _inverse_route_id(self):
        for orderpoint in self:
            if not orderpoint.route_id:
                orderpoint.bom_id = False
        super()._inverse_route_id()

    def _get_replenishment_order_notification(self):
        self.ensure_one()
        domain = Domain("orderpoint_id", "in", self.ids)
        if self.env.context.get("written_after"):
            domain &= Domain("write_date", ">=", self.env.context.get("written_after"))
        production = self.env["mrp.production"].search(domain, limit=1)
        if production:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("The following replenishment order has been generated"),
                    "message": "%s",
                    "links": [
                        {
                            "label": production.name,
                            "url": f"/odoo/action-mrp.action_mrp_production_form/{production.id}",
                        }
                    ],
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return super()._get_replenishment_order_notification()

    @api.depends("bom_id", "product_id.bom_ids.produce_delay")
    def _compute_deadline_date(self):
        super()._compute_deadline_date()

    def _get_lead_days_values(self):
        values = super()._get_lead_days_values()
        if self.bom_id:
            values["bom"] = self.bom_id
        return values

    @api.depends(
        "bom_id",
        "bom_id.product_uom_id",
        "product_id.bom_ids",
        "product_id.bom_ids.product_uom_id",
    )
    def _compute_qty_to_order_computed(self):
        super()._compute_qty_to_order_computed()

    def _compute_allowed_replenishment_uom_ids(self):
        super()._compute_allowed_replenishment_uom_ids()
        for orderpoint in self:
            if "manufacture" in orderpoint.rule_ids.mapped("action"):
                orderpoint.allowed_replenishment_uom_ids += (
                    orderpoint.product_id.bom_ids.product_uom_id
                )

    def _compute_show_supply_warning(self):
        for orderpoint in self:
            if (
                "manufacture" in orderpoint.rule_ids.mapped("action")
                and not orderpoint.show_supply_warning
            ):
                orderpoint.show_supply_warning = not orderpoint.product_id.bom_ids
                continue
            super(StockWarehouseOrderpoint, orderpoint)._compute_show_supply_warning()

    @api.depends("effective_route_id")
    def _compute_show_bom(self):
        manufacture_route = [
            res["route_id"][0]
            for res in self.env["stock.rule"].search_read(
                [("action", "=", "manufacture")], ["route_id"]
            )
        ]
        for orderpoint in self:
            orderpoint.show_bom = orderpoint.effective_route_id.id in manufacture_route

    def _inverse_bom_id(self):
        for orderpoint in self:
            if orderpoint.route_id or not orderpoint.bom_id:
                continue
            manufacture_rule = self.env["stock.rule"].search(
                [
                    ("action", "=", "manufacture"),
                    ("company_id", "in", [orderpoint.company_id.id, False]),
                ],
                limit=1,
            )
            if manufacture_rule:
                orderpoint.route_id = manufacture_rule.route_id

    @api.depends("effective_route_id", "bom_id", "rule_ids", "product_id.bom_ids")
    def _compute_bom_id_placeholder(self):
        default_boms = self._get_default_boms()
        for orderpoint in self:
            default_bom = default_boms[orderpoint]
            orderpoint.bom_id_placeholder = (
                default_bom.display_name if default_bom else ""
            )

    @api.depends("effective_route_id", "bom_id", "rule_ids", "product_id.bom_ids")
    def _compute_effective_bom_id(self):
        empty_bom = self.env["mrp.bom"]
        default_boms = self.filtered(
            lambda orderpoint: not orderpoint.bom_id
        )._get_default_boms()
        for orderpoint in self:
            orderpoint.effective_bom_id = orderpoint.bom_id or default_boms.get(
                orderpoint, empty_bom
            )

    def _search_effective_bom_id(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        boms = self.env["mrp.bom"].search([("id", "in", value)])
        candidates = self.env["stock.warehouse.orderpoint"].search(
            [("bom_id", "=", False)]
        )
        resolved_ids = [
            orderpoint.id
            for orderpoint, bom in candidates._get_default_boms().items()
            if bom in boms
        ]
        matching = Domain("bom_id", "in", boms.ids) | Domain("id", "in", resolved_ids)
        return matching if operator == "in" else ~matching

    def _compute_days_to_order(self):
        res = super()._compute_days_to_order()
        if not self.env["stock.rule"].search([("action", "=", "manufacture")]):
            return res
        orderpoints_with_bom = self.filtered(
            lambda orderpoint: (
                orderpoint.product_id.variant_bom_ids or orderpoint.product_id.bom_ids
            )
        )
        for orderpoint in orderpoints_with_bom:
            if "manufacture" in orderpoint.rule_ids.mapped("action"):
                boms = (
                    orderpoint.bom_id
                    or orderpoint.product_id.variant_bom_ids
                    or orderpoint.product_id.bom_ids
                )
                orderpoint.days_to_order = (boms and boms[0].days_to_prepare_mo) or 0
        return res

    def _get_default_route_map(self):
        routes = super()._get_default_route_map()
        manufacture_routes = (
            self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
        )
        for orderpoint in self.filtered("location_id"):
            route_id = orderpoint.rule_ids.route_id & manufacture_routes
            if orderpoint.product_id.bom_ids and route_id:
                routes[orderpoint.id] = route_id[0]
        return routes

    def _get_default_bom(self):
        self.ensure_one()
        return self._get_default_boms()[self]

    def _get_default_boms(self):
        Bom = self.env["mrp.bom"]
        result = dict.fromkeys(self, Bom)
        by_lookup = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint in self:
            if orderpoint.show_bom:
                by_lookup[(orderpoint._get_default_rule(), orderpoint.company_id)] |= (
                    orderpoint
                )
        for (rule, company), orderpoints in by_lookup.items():
            products = orderpoints.product_id
            boms = Bom._bom_find(
                products,
                picking_type=rule.picking_type_id,
                bom_type="normal",
                company_id=company.id,
            )
            unmatched = products.filtered(lambda product, boms=boms: not boms[product])
            if unmatched:
                boms.update(
                    {
                        product: bom
                        for product, bom in Bom._bom_find(
                            unmatched,
                            picking_type=False,
                            bom_type="normal",
                            company_id=company.id,
                        ).items()
                        if bom
                    }
                )
            for orderpoint in orderpoints:
                result[orderpoint] = boms[orderpoint.product_id]
        return result

    def _get_replenishment_multiple_alternative(self, qty_to_order):
        self.ensure_one()
        routes = self.effective_route_id or self.product_id.route_ids
        if not any(r.action == "manufacture" for r in routes.rule_ids):
            return super()._get_replenishment_multiple_alternative(qty_to_order)
        bom = (
            self.bom_id
            or self.env["mrp.bom"]._bom_find(
                self.product_id,
                picking_type=False,
                bom_type="normal",
                company_id=self.company_id.id,
            )[self.product_id]
        )
        return bom.product_uom_id

    def _quantity_in_progress(self):
        bom_kits = self.env["mrp.bom"]._bom_find(self.product_id, bom_type="phantom")
        bom_kit_orderpoints = {
            orderpoint: bom_kits[orderpoint.product_id]
            for orderpoint in self
            if orderpoint.product_id in bom_kits
        }
        orderpoints_without_kit = self - self.env["stock.warehouse.orderpoint"].concat(
            *bom_kit_orderpoints.keys()
        )
        res = super(
            StockWarehouseOrderpoint, orderpoints_without_kit
        )._quantity_in_progress()
        for orderpoint, bom_kit in bom_kit_orderpoints.items():
            _dummy, bom_sub_lines = bom_kit.explode(orderpoint.product_id, 1)
            ratios_qty_available = []
            ratios_total = []
            for bom_line, bom_line_data in bom_sub_lines:
                component = bom_line.product_id
                if not component.is_storable or bom_line.product_uom_id.is_zero(
                    bom_line_data["qty"]
                ):
                    continue
                uom_qty_per_kit = bom_line_data["qty"] / bom_line_data["original_qty"]
                qty_per_kit = bom_line.product_uom_id._compute_quantity_estimate(
                    uom_qty_per_kit, bom_line.product_id.uom_id
                )
                if not qty_per_kit:
                    continue
                qty_by_product_location, _dummy = component._get_quantity_in_progress(
                    orderpoint.location_id.ids
                )
                qty_in_progress = qty_by_product_location.get(
                    (component.id, orderpoint.location_id.id), 0.0
                )
                qty_available = component.qty_available / qty_per_kit
                ratios_qty_available.append(qty_available)
                ratios_total.append(qty_available + (qty_in_progress / qty_per_kit))
            product_qty = min(ratios_total or [0]) - min(ratios_qty_available or [0])
            res[orderpoint.id] = (
                orderpoint.product_id.uom_id._compute_quantity_estimate(
                    product_qty, orderpoint.product_uom_id, round=False
                )
            )

        productions_group = self.env["mrp.production"]._read_group(
            [
                ("state", "=", "draft"),
                ("orderpoint_id", "in", orderpoints_without_kit.ids),
                ("id", "not in", self.env.context.get("ignore_mo_ids", [])),
            ],
            ["orderpoint_id", "product_uom_id"],
            ["product_qty:sum"],
        )
        for orderpoint, uom, product_qty_sum in productions_group:
            res[orderpoint.id] += uom._compute_quantity_estimate(
                product_qty_sum, orderpoint.product_uom_id, round=False
            )

        in_progress_productions = self.env["mrp.production"].search(
            [
                ("state", "=", "confirmed"),
                ("orderpoint_id", "in", orderpoints_without_kit.ids),
                ("id", "not in", self.env.context.get("ignore_mo_ids", [])),
            ]
        )
        for prod in in_progress_productions:
            date_start, date_end, orderpoint = (
                prod.date_start,
                prod.date_end,
                prod.orderpoint_id,
            )
            lead_horizon_date = datetime.combine(orderpoint.lead_horizon_date, time.max)
            if date_start <= lead_horizon_date < date_end:
                res[orderpoint.id] += prod.product_uom_id._compute_quantity_estimate(
                    prod.product_qty, orderpoint.product_uom_id, round=False
                )
        return res

    def _prepare_procurement_vals(self, date=False):
        values = super()._prepare_procurement_vals(date=date)
        values["bom_id"] = self.bom_id
        return values

    def _post_process_scheduler(self):
        self.env["mrp.production"].sudo().search(
            [
                ("orderpoint_id", "in", self.ids),
                ("move_raw_ids", "!=", False),
                ("state", "=", "draft"),
            ]
        ).action_confirm()
        return super()._post_process_scheduler()

    @api.constrains("product_id")
    def check_product_is_not_kit(self):
        domain = [
            "&",
            "|",
            ("product_id", "in", self.product_id.ids),
            "&",
            ("product_id", "=", False),
            ("product_tmpl_id", "in", self.product_id.product_tmpl_id.ids),
            ("type", "=", "phantom"),
            "|",
            ("company_id", "in", self.company_id.ids),
            ("company_id", "=", False),
        ]
        if self.env["mrp.bom"].search_count(domain, limit=1):
            raise ValidationError(
                _(
                    "A product with a kit-type bill of materials can not have a reordering rule."
                )
            )

    def _get_orderpoint_products(self):
        non_kit_ids = []
        for batch_ids in batched(
            super()._get_orderpoint_products().ids, 2000, strict=False
        ):
            products = self.env["product.product"].browse(batch_ids)
            kit_ids = {
                k.id
                for k in self.env["mrp.bom"]._bom_find(products, bom_type="phantom")
            }
            non_kit_ids.extend(id_ for id_ in products.ids if id_ not in kit_ids)
            products.invalidate_recordset()
        return self.env["product.product"].browse(non_kit_ids)
