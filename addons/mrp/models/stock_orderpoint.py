from collections import defaultdict
from datetime import datetime, time

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    show_bom = fields.Boolean(
        string="Show BoM column",
        compute="_compute_show_bom",
    )
    bom_id = fields.Many2one(
        comodel_name="mrp.bom",
        string="Bill of Materials",
        inverse="_inverse_bom_id",
        domain="[('type', '=', 'normal'), '&', '|', ('company_id', '=', company_id), ('company_id', '=', False), '|', ('product_id', '=', product_id), '&', ('product_id', '=', False), ('product_tmpl_id', '=', product_tmpl_id)]",
        check_company=True,
        tracking=True,
    )
    bom_id_placeholder = fields.Char(compute="_compute_bom_id_placeholder")
    effective_bom_id = fields.Many2one(
        comodel_name="mrp.bom",
        string="Effective Bill of Materials",
        compute="_compute_effective_bom_id",
        search="_search_effective_bom_id",
        store=False,
        help="Either the Bill of Materials set directly or the one computed to be used by this replenishment",
    )

    def _inverse_route_id(self):
        for orderpoint in self:
            if not orderpoint.route_id:
                orderpoint.bom_id = False
        super()._inverse_route_id()

    def _prepare_action_replenishment_order_notification(self):
        self.check_singleton()
        production = self.env["mrp.production"].search(
            self._get_domain_replenishment_source(),
            limit=1,
        )
        if production:
            return self._prepare_action_replenishment_notification(
                self.env._("The following replenishment order has been generated"),
                production.name,
                f"/odoo/action-mrp.action_mrp_production_form/{production.id}",
            )
        return super()._prepare_action_replenishment_order_notification()

    @api.depends(
        "bom_id.produce_delay",
        "bom_id.days_to_prepare_mo",
        "product_id.bom_ids.produce_delay",
        "product_id.bom_ids.days_to_prepare_mo",
    )
    def _compute_deadline_date(self):
        super()._compute_deadline_date()

    @api.depends(
        "bom_id.produce_delay",
        "bom_id.days_to_prepare_mo",
        "product_id.bom_ids.produce_delay",
        "product_id.bom_ids.days_to_prepare_mo",
    )
    def _compute_lead_time(self):
        super()._compute_lead_time()

    def _prepare_lead_time_params(self):
        values = super()._prepare_lead_time_params()
        if self.bom_id:
            values["bom_id"] = self.bom_id
        return values

    def _prepare_lead_time_params_map(self):
        result = super()._prepare_lead_time_params_map()
        default_boms = self.filtered(
            lambda orderpoint: not orderpoint.bom_id
        )._get_default_boms()
        for orderpoint, bom in default_boms.items():
            if bom:
                result[orderpoint.id]["bom_id"] = bom
        return result

    def _get_manufacture_rule_map(self):
        no_rule = self.env["stock.rule"]
        return {
            orderpoint: next(
                (rule for rule in orderpoint.rule_ids if rule.action == "manufacture"),
                no_rule,
            )
            for orderpoint in self
        }

    @api.depends(
        "bom_id.product_uom_id",
        "bom_id.produce_delay",
        "bom_id.days_to_prepare_mo",
        "product_id.bom_ids.product_uom_id",
        "product_id.bom_ids.produce_delay",
        "product_id.bom_ids.days_to_prepare_mo",
    )
    def _compute_qty_to_order_computed(self):
        super()._compute_qty_to_order_computed()

    def _compute_allowed_replenishment_uom_ids(self):
        super()._compute_allowed_replenishment_uom_ids()
        for orderpoint, rule in self._get_manufacture_rule_map().items():
            if rule:
                orderpoint.allowed_replenishment_uom_ids += (
                    orderpoint.product_id.bom_ids.product_uom_id
                )

    @api.depends("product_id.bom_ids")
    def _compute_rule_ids(self):
        super()._compute_rule_ids()

    @api.depends("product_id.bom_ids", "bom_id")
    def _compute_show_supply_warning(self):
        rules = self._get_manufacture_rule_map()
        manufactured = self.filtered(lambda orderpoint: rules[orderpoint])
        default_boms = manufactured._get_default_boms()
        for orderpoint in manufactured:
            orderpoint.show_supply_warning = not (
                orderpoint.bom_id or default_boms[orderpoint]
            )
        super(
            StockWarehouseOrderpoint, self - manufactured
        )._compute_show_supply_warning()

    @api.depends("effective_route_id")
    def _compute_show_bom(self):
        manufacture_routes = self.env["stock.rule"]._get_manufacture_rules().route_id
        for orderpoint in self:
            orderpoint.show_bom = orderpoint.effective_route_id in manufacture_routes

    def _inverse_bom_id(self):
        orderpoints = self.filtered(lambda op: op.bom_id and not op.route_id)
        if not orderpoints:
            return
        manufacture_rules = self.env["stock.rule"]._get_manufacture_rules()
        _debug.pipeline("orderpoint_route_from_bom", orderpoints=orderpoints)
        for orderpoint in orderpoints:
            manufacture_rule = next(
                (
                    rule
                    for rule in manufacture_rules
                    if not rule.company_id or rule.company_id == orderpoint.company_id
                ),
                None,
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

    @api.depends(
        "rule_ids",
        "bom_id.days_to_prepare_mo",
        "product_id.bom_ids.days_to_prepare_mo",
    )
    def _compute_days_to_order(self):
        super()._compute_days_to_order()
        rules = self._get_manufacture_rule_map()
        manufactured = self.filtered(lambda orderpoint: rules[orderpoint])
        default_boms = manufactured._get_default_boms()
        for orderpoint in manufactured:
            bom = orderpoint.bom_id or default_boms[orderpoint]
            if bom:
                orderpoint.days_to_order = bom.days_to_prepare_mo

    def _get_default_route_map(self):
        routes = super()._get_default_route_map()
        Rule = self.env["stock.rule"]
        manufacture_routes = Rule._get_manufacture_rules().route_id
        for company, orderpoints in (
            self.filtered("location_id").grouped("company_id").items()
        ):
            manufacturable = Rule._get_manufacturable(orderpoints.product_id, company)
            for orderpoint in orderpoints:
                route_id = orderpoint.rule_ids.route_id & manufacture_routes
                if route_id and manufacturable[orderpoint.product_id.id]:
                    routes[orderpoint.id] = route_id[0]
        return routes

    def _get_default_boms(self):
        Bom = self.env["mrp.bom"]
        result = dict.fromkeys(self, Bom)
        by_lookup = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint, rule in self._get_manufacture_rule_map().items():
            if rule:
                by_lookup[rule.picking_type_id, orderpoint.company_id] |= orderpoint
        for (picking_type, company), orderpoints in by_lookup.items():
            products = orderpoints.product_id
            boms = Bom._get_bom_by_product(
                products,
                picking_type=picking_type,
                bom_type="normal",
                company_id=company.id,
            )
            unmatched = products.browse(
                [product.id for product in products if not boms[product]]
            )
            _debug.logic(
                "orderpoint_default_boms",
                orderpoints=orderpoints,
                products=len(products),
                unmatched=len(unmatched),
                picking_type=picking_type.id,
            )
            if unmatched:
                boms.update(
                    {
                        product: bom
                        for product, bom in Bom._get_bom_by_product(
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

    def _get_replenishment_multiple_alternative_map(self, qty_by_orderpoint):
        rules = self._get_manufacture_rule_map()
        manufactured = self.filtered(lambda orderpoint: rules[orderpoint])
        result = super(
            StockWarehouseOrderpoint,
            self - manufactured,
        )._get_replenishment_multiple_alternative_map(qty_by_orderpoint)
        default_boms = manufactured._get_default_boms()
        for orderpoint in manufactured:
            bom = orderpoint.bom_id or default_boms[orderpoint]
            result[orderpoint.id] = bom.product_uom_id
        return result

    def _get_quantity_in_progress(self):
        res = super()._get_quantity_in_progress()
        productions_group = self.env["mrp.production"]._read_group(
            [
                ("state", "=", "draft"),
                ("orderpoint_id", "in", self.ids),
                ("id", "not in", self.env.context.get("ignore_mo_ids", [])),
            ],
            ["orderpoint_id", "product_uom_id"],
            ["product_qty:sum"],
        )
        for orderpoint, uom, product_qty_sum in productions_group:
            res[orderpoint.id] += uom._get_quantity_estimate(
                product_qty_sum, orderpoint.product_uom_id, round=False
            )

        in_progress_productions = self.env["mrp.production"].search(
            [
                ("state", "=", "confirmed"),
                ("orderpoint_id", "in", self.ids),
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
                res[orderpoint.id] += prod.product_uom_id._get_quantity_estimate(
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
    def _check_product_is_not_kit(self):
        Bom = self.env["mrp.bom"]
        domain = Bom._get_domain_kit(self.company_id) & (
            Domain("product_id", "in", self.product_id.ids)
            | (
                Domain("product_id", "=", False)
                & Domain("product_tmpl_id", "in", self.product_id.product_tmpl_id.ids)
            )
        )
        if Bom.search_count(domain, limit=1):
            _debug.logic(
                "orderpoint_refused", reason="product_is_kit", orderpoints=self
            )
            raise ValidationError(
                self.env._(
                    "A product with a kit-type bill of materials can not have a reordering rule."
                )
            )
