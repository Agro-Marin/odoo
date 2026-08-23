import logging
from collections import defaultdict
from datetime import UTC, datetime, time
from itertools import batched

from dateutil import relativedelta
from psycopg import OperationalError

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.datetime import timezone
from odoo.modules.registry import Registry
from odoo.tools import escape_psql, format_date, frozendict

from odoo.addons.stock.const import PY_OPERATORS
from odoo.addons.stock.models.stock_procurement import ProcurementException

_logger = logging.getLogger(__name__)

_LEAD_TIME_STATS_QUERY = """
WITH RECURSIVE receipt AS (
    SELECT DISTINCT
        sp.id,
        sp.backorder_id,
        sp.create_date,
        sp.date_done
    FROM stock_picking sp
    JOIN stock_picking_type spt ON sp.picking_type_id = spt.id
    JOIN stock_move sm ON sm.picking_id = sp.id
    WHERE sp.state = 'done'
      AND sm.state = 'done'
      AND sp.date_done IS NOT NULL
      AND sp.date_done >= %s
      AND spt.code = 'incoming'
      AND sm.product_id = ANY(%s)
      AND sm.location_dest_id IN (
          SELECT id FROM stock_location
          WHERE parent_path LIKE %s
      )
),
chain AS (
    SELECT r.id AS receipt_id, r.backorder_id, r.create_date
    FROM receipt r
    UNION ALL
    SELECT c.receipt_id, sp.backorder_id, sp.create_date
    FROM chain c
    JOIN stock_picking sp ON sp.id = c.backorder_id
),
ordered AS (
    SELECT receipt_id, create_date AS ordered_date
    FROM chain
    WHERE backorder_id IS NULL
      AND create_date IS NOT NULL
),
receipts AS (
    SELECT DISTINCT ON (sm.product_id, r.id)
        sm.product_id,
        r.date_done,
        EXTRACT(EPOCH FROM (r.date_done - o.ordered_date)) / 86400.0
            AS lead_time_days
    FROM stock_move sm
    JOIN receipt r ON sm.picking_id = r.id
    JOIN ordered o ON o.receipt_id = r.id
    WHERE sm.state = 'done'
      AND r.date_done - o.ordered_date >= interval '1 hour'
      AND sm.product_id = ANY(%s)
      AND sm.location_dest_id IN (
          SELECT id FROM stock_location
          WHERE parent_path LIKE %s
      )
    ORDER BY sm.product_id, r.id
),
ranked_receipts AS (
    SELECT
        product_id,
        lead_time_days,
        ROW_NUMBER() OVER (
            PARTITION BY product_id
            ORDER BY date_done DESC
        ) AS rn
    FROM receipts
)
SELECT
    product_id,
    COALESCE(AVG(lead_time_days), 0),
    COALESCE(STDDEV_POP(lead_time_days), 0),
    COUNT(*)
FROM ranked_receipts
WHERE rn <= %s
GROUP BY product_id
"""


class StockWarehouseOrderpoint(models.Model):
    _name = "stock.warehouse.orderpoint"
    _description = "Minimum Inventory Rule"
    _check_company_auto = True
    _order = "location_id,company_id,id"

    _LEAD_TIME_SAMPLE_SIZE = 20
    _LEAD_TIME_LOOKBACK_DAYS = 730
    _PROCUREMENT_RETRIES = 5

    name = fields.Char(
        string="Name",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("stock.orderpoint"),
        readonly=True,
        copy=False,
    )
    trigger = fields.Selection(
        selection=[("auto", "Auto"), ("manual", "Manual")],
        string="Trigger",
        required=True,
        default="auto",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="If the active field is set to False, it will allow you to hide the orderpoint without removing it.",
    )
    snoozed_until = fields.Date(
        string="Snoozed",
        help="Hidden from the replenishment report until this date has passed.",
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        required=True,
        compute="_compute_warehouse_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        ondelete="cascade",
        index=True,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        required=True,
        compute="_compute_location_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        ondelete="cascade",
        index=True,
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id",
        comodel_name="product.template",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
        domain=(
            "[('product_tmpl_id', '=', context.get('active_id', False))] if context.get('active_model') == 'product.template' else"
            " [('id', '=', context.get('default_product_id', False))] if context.get('default_product_id') else"
            " [('is_storable', '=', True)]"
        ),
        ondelete="cascade",
        index=True,
    )
    product_category_id = fields.Many2one(
        related="product_id.categ_id",
        comodel_name="product.category",
        string="Product Category",
    )
    product_uom_id = fields.Many2one(
        related="product_id.uom_id",
        comodel_name="uom.uom",
        string="Unit",
    )
    product_uom_name = fields.Char(
        related="product_uom_id.display_name",
        string="Product unit of measure label",
        readonly=True,
    )
    product_min_qty = fields.Float(
        string="Min Quantity",
        digits="Product Unit",
        required=True,
        default=0.0,
        help="The minimum Stock level that will trigger a replenishment.",
    )
    product_max_qty = fields.Float(
        string="Max Quantity",
        digits="Product Unit",
        required=True,
        default=0.0,
        compute="_compute_product_max_qty",
        store=True,
        readonly=False,
        help="Stock level to reach when replenishing.",
    )
    allowed_replenishment_uom_ids = fields.Many2many(
        comodel_name="uom.uom",
        compute="_compute_allowed_replenishment_uom_ids",
    )
    replenishment_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Multiple",
        domain="[('id', 'in', allowed_replenishment_uom_ids)]",
        help="The procurement quantity will be rounded up to a multiple of this unit/packaging. If it is not set, it is not rounded.",
    )
    replenishment_uom_id_placeholder = fields.Char(
        compute="_compute_replenishment_uom_id_placeholder",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    allowed_location_ids = fields.Many2many(
        comodel_name="stock.location",
        compute="_compute_allowed_location_ids",
    )

    rule_ids = fields.Many2many(
        comodel_name="stock.rule",
        string="Rules used",
        compute="_compute_rule_ids",
    )
    lead_horizon_date = fields.Date(compute="_compute_lead_days")
    lead_days = fields.Float(compute="_compute_lead_days")
    route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Route",
        inverse="_inverse_route_id",
        domain="['|', ('product_selectable', '=', True), ('rule_ids.action', 'in', ['buy', 'manufacture'])]",
    )
    route_id_placeholder = fields.Char(compute="_compute_route_id_placeholder")
    effective_route_id = fields.Many2one(
        comodel_name="stock.route",
        compute="_compute_effective_route_id",
        store=False,
        search="_search_effective_route_id",
        help="Either the route set directly or the one computed to be used by this replenishment",
    )
    qty_on_hand = fields.Float(
        string="On Hand",
        digits="Product Unit",
        compute="_compute_qty",
        readonly=True,
    )
    qty_forecast = fields.Float(
        string="Forecast",
        digits="Product Unit",
        compute="_compute_qty",
        readonly=True,
    )
    qty_to_order = fields.Float(
        string="To Order",
        digits="Product Unit",
        compute="_compute_qty_to_order",
        inverse="_inverse_qty_to_order",
        search="_search_qty_to_order",
    )
    qty_to_order_computed = fields.Float(
        string="To Order Computed",
        digits="Product Unit",
        compute="_compute_qty_to_order_computed",
        store=True,
    )
    qty_to_order_manual = fields.Float(string="To Order Manual", digits="Product Unit")
    qty_to_order_manual_set = fields.Boolean(
        string="Quantity Overridden",
        default=False,
        help="Technical: the user entered a quantity to order on this "
        "manually-triggered orderpoint that differs from the computed suggestion, "
        "and `qty_to_order_manual` holds it. A Float cannot tell an explicit 0 from "
        "no value at all, so whether an override exists is recorded separately from "
        "what it is -- which is why an override of 0 needs no special case.",
    )
    is_autogenerated = fields.Boolean(
        string="Autogenerated",
        default=False,
        help="Technical: set on orderpoints created automatically by the "
        "replenishment report for a projected shortage. Only these are "
        "auto-vacuumed once their shortage is resolved. Rows created before "
        "this field existed conservatively keep it unset and are therefore "
        "no longer auto-vacuumed.",
    )

    days_to_order = fields.Float(
        compute="_compute_days_to_order",
        help="Numbers of days  in advance that replenishments demands are created.",
    )

    unwanted_replenish = fields.Boolean(
        string="Unwanted Replenish",
        compute="_compute_unwanted_replenish",
    )
    show_supply_warning = fields.Boolean(compute="_compute_show_supply_warning")
    deadline_date = fields.Date(
        string="Deadline",
        compute="_compute_deadline_date",
        store=True,
        readonly=True,
        help="Date before which you should order to avoid falling below the minimum. If you "
        "have nothing to order while a deadline is found, it may be because a future "
        "arrival is expected after the minimum quantity is reached (potential stockout). "
        "Check the Forecast Report.",
    )

    actual_lead_time_avg = fields.Float(
        string="Avg Lead Time (days)",
        digits=(10, 2),
        compute="_compute_lead_time_stats",
        store=True,
        help="Average actual procurement lead time in days, measured from "
        "completed incoming transfers for this product and warehouse.",
    )
    actual_lead_time_stddev = fields.Float(
        string="Lead Time Std Dev (days)",
        digits=(10, 2),
        compute="_compute_lead_time_stats",
        store=True,
        help="Standard deviation of actual procurement lead times. "
        "Higher values indicate less predictable suppliers.",
    )
    lead_time_sample_count = fields.Integer(
        string="Lead Time Samples",
        compute="_compute_lead_time_stats",
        store=True,
        help="Number of completed incoming transfers used to compute lead time statistics.",
    )

    _product_location_check = models.Constraint(
        "unique (product_id, location_id, company_id)",
        "A replenishment rule already exists for this product on this location.",
    )

    @api.constrains("product_min_qty", "product_max_qty")
    def _check_min_max_qty(self):
        if any(
            orderpoint.product_uom_id.compare(
                orderpoint.product_min_qty, orderpoint.product_max_qty
            )
            > 0
            for orderpoint in self
        ):
            raise ValidationError(
                _(
                    "The minimum quantity must be less than or equal to the maximum quantity.",
                ),
            )

    @api.model
    def _mark_manual_qty_override(self, vals):
        if "qty_to_order_manual" in vals and "qty_to_order_manual_set" not in vals:
            vals = dict(vals, qty_to_order_manual_set=True)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._mark_manual_qty_override(vals) for vals in vals_list]
        default_trigger = None
        if any(vals.get("snoozed_until") for vals in vals_list):
            default_trigger = self.default_get(["trigger"])["trigger"]
        if any(
            vals.get("snoozed_until") and vals.get("trigger", default_trigger) == "auto"
            for vals in vals_list
        ):
            raise UserError(
                _(
                    "You can not create a snoozed orderpoint that is not manually triggered.",
                ),
            )
        return super().create(vals_list)

    def write(self, vals):
        vals = self._mark_manual_qty_override(vals)
        if "company_id" in vals:
            for orderpoint in self:
                if orderpoint.company_id.id != vals["company_id"]:
                    raise UserError(
                        _(
                            "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one.",
                        ),
                    )
        if vals.get("snoozed_until"):
            new_trigger = vals.get("trigger")
            if any(
                (new_trigger or orderpoint.trigger) == "auto" for orderpoint in self
            ):
                raise UserError(
                    _(
                        "You can only snooze manual orderpoints. You should rather archive 'auto-trigger' orderpoints if you do not want them to be triggered.",
                    ),
                )
        return super().write(vals)

    @api.depends("warehouse_id", "company_id")
    def _compute_allowed_location_ids(self):
        all_warehouses = self.env["stock.warehouse"].search([])
        orderpoints_by_key = defaultdict(
            lambda: self.env["stock.warehouse.orderpoint"],
        )
        for orderpoint in self:
            orderpoints_by_key[orderpoint.company_id, orderpoint.warehouse_id] |= (
                orderpoint
            )
        for (company, warehouse), orderpoints in orderpoints_by_key.items():
            loc_domain = Domain("usage", "in", ("internal", "view")) & Domain(
                "company_id",
                "in",
                [False, company.id],
            )
            for other_warehouse in all_warehouses:
                if other_warehouse == warehouse:
                    continue
                if other_warehouse.view_location_id:
                    loc_domain &= ~Domain(
                        "id",
                        "child_of",
                        other_warehouse.view_location_id.id,
                    )
            orderpoints.allowed_location_ids = self.env["stock.location"].search(
                loc_domain,
            )

    @api.depends("rule_ids")
    def _compute_show_supply_warning(self):
        for orderpoint in self:
            orderpoint.show_supply_warning = not orderpoint.rule_ids

    @api.depends(
        "location_id",
        "warehouse_id",
        "product_min_qty",
        "route_id",
        "rule_ids",
        "product_id.route_ids",
        "product_id.stock_move_ids.date",
        "product_id.stock_move_ids.state",
        "product_id.seller_ids",
        "product_id.seller_ids.delay",
        "company_id.horizon_days",
    )
    def _compute_deadline_date(self):
        canonical = self._canonical()
        critical_orderpoints = canonical.filtered(
            lambda o: o.product_uom_id.compare(o.qty_on_hand, o.product_min_qty) < 0,
        )
        critical_orderpoints.deadline_date = fields.Date.today()
        orderpoints_to_compute = canonical - critical_orderpoints
        if not orderpoints_to_compute:
            return

        for company in orderpoints_to_compute.company_id:
            company_orderpoints = orderpoints_to_compute.filtered(
                lambda c, company=company: c.company_id == company,
            )
            horizon_date = fields.Date.today() + relativedelta.relativedelta(
                days=company.horizon_days,
            )
            moves_by_product = company_orderpoints._read_pending_moves_by_product(
                horizon_date,
            )
            for orderpoint in company_orderpoints:
                orderpoint.deadline_date = orderpoint._get_deadline_from_timeline(
                    moves_by_product.get(orderpoint.product_id.id, ()),
                    horizon_date,
                )

    def _get_pending_move_domains(self, horizon_date):
        _dummy, domain_move_in, domain_move_out = (
            self.env["stock.location"]._quantity_domains(self.location_id.ids)
        )
        scope = Domain.AND(
            [
                [("product_id", "in", self.product_id.ids)],
                [
                    (
                        "state",
                        "in",
                        ("waiting", "confirmed", "assigned", "partially_available"),
                    ),
                ],
                [("date", "<=", horizon_date)],
            ],
        )
        return scope & domain_move_in, scope & domain_move_out

    def _read_pending_moves_by_product(self, horizon_date):
        domain_move_in, domain_move_out = self._get_pending_move_domains(horizon_date)
        Move = self.env["stock.move"].with_context(active_test=False)
        moves_by_product = defaultdict(list)
        for product, location_dest, location_final, in_date, in_qty in Move._read_group(
            domain_move_in,
            ["product_id", "location_dest_id", "location_final_id", "date:day"],
            ["product_qty:sum"],
        ):
            arrival = location_final or location_dest
            moves_by_product[product.id].append(
                (arrival.parent_path or "", in_date.date(), in_qty),
            )
        for product, location, out_date, out_qty in Move._read_group(
            domain_move_out,
            ["product_id", "location_id", "date:day"],
            ["product_qty:sum"],
        ):
            moves_by_product[product.id].append(
                (location.parent_path or "", out_date.date(), -out_qty),
            )
        return moves_by_product

    def _get_deadline_from_timeline(self, timeline, horizon_date):
        self.ensure_one()
        location_path = self.location_id.parent_path or ""
        qty_by_date = defaultdict(float)
        for move_path, move_date, move_qty in timeline:
            if location_path and move_path.startswith(location_path):
                qty_by_date[move_date] += move_qty
        qty_on_hand_at_date = self.qty_on_hand
        for move_date, move_qty in sorted(qty_by_date.items()):
            qty_on_hand_at_date += move_qty
            if (
                self.product_uom_id.compare(qty_on_hand_at_date, self.product_min_qty)
                < 0
            ):
                deadline = move_date - relativedelta.relativedelta(days=self.lead_days)
                return deadline if deadline < horizon_date else False
        return False

    @api.depends("product_id", "warehouse_id")
    def _compute_lead_time_stats(self):
        result_map = self._read_lead_time_stats()
        for orderpoint in self:
            avg, stddev, count = result_map.get(
                (orderpoint.product_id.id, orderpoint.warehouse_id.id),
                (0.0, 0.0, 0),
            )
            orderpoint.actual_lead_time_avg = avg
            orderpoint.actual_lead_time_stddev = stddev
            orderpoint.lead_time_sample_count = count

    def _read_lead_time_stats(self):
        self.env["stock.move"].flush_model()
        self.env["stock.picking"].flush_model()
        wh_orderpoints = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint in self:
            if orderpoint.product_id and orderpoint.warehouse_id:
                wh_orderpoints[orderpoint.warehouse_id] |= orderpoint

        date_done_cutoff = fields.Datetime.now() - relativedelta.relativedelta(
            days=self._LEAD_TIME_LOOKBACK_DAYS,
        )
        result_map = {}
        for warehouse, orderpoints in wh_orderpoints.items():
            product_ids = orderpoints.product_id.ids
            parent_path = warehouse.view_location_id.parent_path
            if not product_ids or not parent_path:
                continue

            self.env.cr.execute(
                _LEAD_TIME_STATS_QUERY,
                (
                    date_done_cutoff,
                    product_ids,
                    f"{parent_path}%",
                    product_ids,
                    f"{parent_path}%",
                    self._LEAD_TIME_SAMPLE_SIZE,
                ),
            )

            for product_id, avg_lt, stddev_lt, count in self.env.cr.fetchall():
                result_map[(product_id, warehouse.id)] = (
                    max(avg_lt, 0.0),
                    max(stddev_lt, 0.0),
                    count,
                )
        return result_map

    @api.depends(
        "rule_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.delay",
        "company_id.horizon_days",
    )
    @api.depends_context("global_horizon_days")
    def _compute_lead_days(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        values_by_orderpoint = orderpoints_to_compute._get_lead_days_values_map()
        for orderpoint in orderpoints_to_compute.with_context(
            bypass_delay_description=True,
        ):
            values = values_by_orderpoint[orderpoint.id]
            lead_days, _dummy = orderpoint.rule_ids.with_context(
                global_horizon_days=orderpoint._get_horizon_days(),
            )._get_lead_days(
                orderpoint.product_id,
                **values,
            )
            orderpoint.lead_horizon_date = (
                fields.Date.today()
                + relativedelta.relativedelta(
                    days=lead_days["total_delay"] + lead_days["horizon_time"],
                )
            )
            orderpoint.lead_days = lead_days["total_delay"]
        excluded = self - orderpoints_to_compute
        excluded.lead_horizon_date = False
        excluded.lead_days = 0.0

    @api.depends(
        "route_id",
        "product_id",
        "location_id",
        "company_id",
        "warehouse_id",
        "product_id.route_ids",
    )
    def _compute_rule_ids(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        rules_cache = {}
        extra_routes = orderpoints_to_compute.product_id._get_total_routes_by_product()
        for orderpoint in orderpoints_to_compute:
            all_product_routes = (
                orderpoint.product_id.route_ids
                | orderpoint.product_id.categ_id.total_route_ids
                | extra_routes[orderpoint.product_id.id]
            )
            cache_key = (
                orderpoint.location_id,
                orderpoint.route_id,
                orderpoint.product_id.route_ids,
                all_product_routes,
            )
            if cache_key in rules_cache:
                rule_ids = rules_cache[cache_key]
            else:
                rule_ids = orderpoint.product_id._get_rules_from_location(
                    orderpoint.location_id,
                    route_ids=orderpoint.route_id,
                )
                rules_cache[cache_key] = rule_ids
            orderpoint.rule_ids = rule_ids
        (self - orderpoints_to_compute).rule_ids = False

    @api.depends("product_min_qty")
    def _compute_product_max_qty(self):
        for orderpoint in self:
            if (
                orderpoint.product_uom_id.compare(
                    orderpoint.product_max_qty, orderpoint.product_min_qty
                )
                < 0
                or not orderpoint.product_max_qty
            ):
                orderpoint.product_max_qty = orderpoint.product_min_qty

    @api.depends(
        "rule_ids",
        "route_id",
        "product_id",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_replenishment_uom_ids(self):
        for orderpoint in self:
            orderpoint.allowed_replenishment_uom_ids = orderpoint.product_id.uom_ids
            if "buy" in orderpoint.rule_ids.mapped("action"):
                orderpoint.allowed_replenishment_uom_ids += (
                    orderpoint.product_id.seller_ids.product_uom_id
                )

    @api.depends(
        "allowed_replenishment_uom_ids", "replenishment_uom_id", "qty_to_order"
    )
    @api.depends_context("global_horizon_days")
    def _compute_replenishment_uom_id_placeholder(self):
        alternatives = self._get_replenishment_multiple_alternative_map(
            {orderpoint.id: orderpoint.qty_to_order for orderpoint in self},
        )
        for orderpoint in self:
            alternative = alternatives.get(orderpoint.id)
            orderpoint.replenishment_uom_id_placeholder = (
                alternative.display_name if alternative else ""
            )

    @api.depends("route_id", "product_id")
    def _compute_days_to_order(self):
        self.days_to_order = 0

    def _get_default_warehouse_by_company(self, companies):
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "in", companies.ids)],
            order="company_id, sequence, id",
        )
        default_by_company = {}
        for warehouse in warehouses:
            default_by_company.setdefault(warehouse.company_id.id, warehouse)
        return default_by_company

    @api.depends("location_id", "company_id")
    def _compute_warehouse_id(self):
        default_by_company = self._get_default_warehouse_by_company(self.company_id)
        for orderpoint in self:
            if orderpoint.location_id.warehouse_id:
                orderpoint.warehouse_id = orderpoint.location_id.warehouse_id
            elif orderpoint.company_id:
                orderpoint.warehouse_id = default_by_company.get(
                    orderpoint.company_id.id,
                    self.env["stock.warehouse"],
                )
            if not orderpoint.warehouse_id:
                self.env["stock.warehouse"]._warehouse_redirect_warning()

    @api.depends("warehouse_id", "company_id")
    def _compute_location_id(self):
        default_by_company = self._get_default_warehouse_by_company(
            (self - self.filtered("warehouse_id")).company_id,
        )
        for orderpoint in self:
            warehouse = orderpoint.warehouse_id or default_by_company.get(
                orderpoint.company_id.id,
                self.env["stock.warehouse"],
            )
            orderpoint.location_id = warehouse.lot_stock_id.id

    @api.depends("product_id", "qty_to_order", "product_max_qty")
    @api.depends_context("global_horizon_days")
    def _compute_unwanted_replenish(self):
        for orderpoint in self:
            if (
                not orderpoint.product_id
                or orderpoint.product_uom_id.is_zero(orderpoint.qty_to_order)
                or orderpoint.product_uom_id.compare(orderpoint.product_max_qty, 0)
                == -1
            ):
                orderpoint.unwanted_replenish = False
            else:
                after_replenish_qty = (
                    orderpoint.product_id.with_context(
                        company_id=orderpoint.company_id.id,
                        location=orderpoint.location_id.id,
                    ).qty_available_virtual
                    + orderpoint.qty_to_order
                )
                orderpoint.unwanted_replenish = (
                    orderpoint.product_uom_id.compare(
                        after_replenish_qty,
                        orderpoint.product_max_qty,
                    )
                    > 0
                )

    @api.depends(
        "product_id",
        "product_id.categ_id",
        "product_id.route_ids",
        "product_id.categ_id.route_ids",
        "location_id",
    )
    def _compute_route_id_placeholder(self):
        default_routes = self._get_default_route_map()
        empty_route = self.env["stock.route"]
        for orderpoint in self:
            default_route = default_routes.get(orderpoint.id, empty_route)
            orderpoint.route_id_placeholder = (
                default_route.display_name if default_route else ""
            )

    @api.depends(
        "route_id",
        "product_id",
        "product_id.categ_id",
        "product_id.route_ids",
        "product_id.categ_id.route_ids",
        "location_id",
    )
    def _compute_effective_route_id(self):
        default_routes = self.filtered(
            lambda orderpoint: not orderpoint.route_id,
        )._get_default_route_map()
        empty_route = self.env["stock.route"]
        for orderpoint in self:
            orderpoint.effective_route_id = orderpoint.route_id or default_routes.get(
                orderpoint.id,
                empty_route,
            )

    def _get_qty_forecast_map(self):
        values_by_orderpoint = self._read_product_qty_by_context(
            ["qty_available_virtual"],
        )
        qty_in_progress = self._quantity_in_progress()
        return {
            orderpoint.id: (
                values_by_orderpoint[orderpoint.id]["qty_available_virtual"]
                + qty_in_progress[orderpoint.id]
            )
            for orderpoint in self
        }

    def _read_product_qty_by_context(self, field_names):
        result = {}
        orderpoints_by_context = defaultdict(self.browse)
        for orderpoint in self:
            orderpoints_by_context[frozendict(orderpoint._get_product_context())] |= (
                orderpoint
            )
        for product_context, orderpoints in orderpoints_by_context.items():
            values_by_product = {
                values["id"]: values
                for values in orderpoints.product_id.with_context(
                    product_context,
                ).read(field_names)
            }
            for orderpoint in orderpoints:
                result[orderpoint.id] = values_by_product[orderpoint.product_id.id]
        return result

    @api.depends(
        "product_id",
        "location_id",
        "product_id.qty_available",
        "product_id.qty_available_virtual",
        "product_id.seller_ids.delay",
    )
    @api.depends_context("global_horizon_days")
    def _compute_qty(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        excluded = self - orderpoints_to_compute
        excluded.qty_on_hand = 0.0
        excluded.qty_forecast = 0.0
        if not orderpoints_to_compute:
            return
        values_by_orderpoint = orderpoints_to_compute._read_product_qty_by_context(
            ["qty_available"],
        )
        qty_forecast = orderpoints_to_compute._get_qty_forecast_map()
        for orderpoint in orderpoints_to_compute:
            orderpoint.qty_on_hand = values_by_orderpoint[orderpoint.id]["qty_available"]
            orderpoint.qty_forecast = qty_forecast[orderpoint.id]

    @api.depends(
        "qty_to_order_manual",
        "qty_to_order_computed",
        "qty_to_order_manual_set",
    )
    @api.depends_context("global_horizon_days")
    def _compute_qty_to_order(self):
        what_if = self._get_horizon_suggestion_map()
        for orderpoint in self:
            if orderpoint.qty_to_order_manual_set:
                orderpoint.qty_to_order = orderpoint.qty_to_order_manual
            else:
                orderpoint.qty_to_order = what_if.get(
                    orderpoint.id,
                    orderpoint.qty_to_order_computed,
                )

    def _get_horizon_suggestion_map(self):
        override = self.env.context.get("global_horizon_days")
        if override is None:
            return {}
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: (
                not orderpoint.qty_to_order_manual_set
                and override != orderpoint._get_canonical_horizon_days()
            ),
        )
        if not orderpoints_to_compute:
            return {}
        return orderpoints_to_compute._get_qty_to_order_map()

    @api.depends(
        "replenishment_uom_id",
        "product_min_qty",
        "product_max_qty",
        "product_id",
        "location_id",
        "rule_ids",
        "product_id.seller_ids.delay",
        "company_id.horizon_days",
    )
    def _compute_qty_to_order_computed(self):
        canonical = self._canonical()
        suggestions = canonical._get_qty_to_order_map()
        for orderpoint in canonical:
            orderpoint.qty_to_order_computed = suggestions[orderpoint.id]

    def _inverse_route_id(self):
        pass

    def _inverse_qty_to_order(self):
        suggestions = self._canonical()._get_qty_to_order_map()
        overridden = self.browse()
        for orderpoint in self:
            if orderpoint.trigger != "auto" and orderpoint.product_uom_id.compare(
                orderpoint.qty_to_order,
                suggestions.get(orderpoint.id, orderpoint.qty_to_order_computed),
            ):
                overridden |= orderpoint
        by_quantity = defaultdict(self.browse)
        for orderpoint in overridden:
            by_quantity[orderpoint.qty_to_order] |= orderpoint
        for quantity, group in by_quantity.items():
            group.write(
                {"qty_to_order_manual_set": True, "qty_to_order_manual": quantity},
            )
        (self - overridden).write(
            {"qty_to_order_manual_set": False, "qty_to_order_manual": 0},
        )

    def _get_unset_route_candidate_domain(self, routes, match_unset):
        domain = Domain("route_id", "=", False)
        if match_unset or not routes:
            return domain
        return domain & (
            Domain("product_id.route_ids", "in", routes.ids)
            | Domain("product_id.categ_id.route_ids", "in", routes.ids)
        )

    def _search_effective_route_id(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        Route = self.env["stock.route"]
        match_unset = False
        if operator == "any":
            routes = Route.search(
                value if isinstance(value, Domain) else [("id", "in", value)],
            )
        elif operator == "in":
            ids = set(value)
            match_unset = False in ids or None in ids
            routes = Route.browse(id_ for id_ in ids if id_)
        else:
            routes = Route.search([("display_name", operator, value)])
        unset_orderpoints = self.env["stock.warehouse.orderpoint"].search(
            self._get_unset_route_candidate_domain(routes, match_unset),
        )
        default_routes = unset_orderpoints._get_default_route_map()
        empty_route = Route
        matched_ids = [
            orderpoint.id
            for orderpoint in unset_orderpoints
            if (
                (default_route := default_routes.get(orderpoint.id, empty_route))
                and default_route in routes
            )
            or (match_unset and not default_route)
        ]
        return Domain("route_id", "in", routes.ids) | Domain("id", "in", matched_ids)

    def _search_qty_to_order(self, operator, value):
        if PY_OPERATORS.get(operator) is None:
            return NotImplemented
        return Domain(
            [
                "|",
                "&",
                ("qty_to_order_manual_set", "=", True),
                ("qty_to_order_manual", operator, value),
                "&",
                ("qty_to_order_manual_set", "=", False),
                ("qty_to_order_computed", operator, value),
            ],
        )

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.product_id.action_product_forecast_report()
        action["context"] = {
            "active_id": self.product_id.id,
            "active_model": "product.product",
            "lead_horizon_date": format_date(self.env, self.lead_horizon_date),
            "qty_to_order": self.qty_to_order,
        }
        warehouse = self.warehouse_id
        if warehouse:
            action["context"]["warehouse_id"] = warehouse.id
        return action

    @api.model
    def action_open_orderpoints(self):
        return self._get_orderpoint_action()

    def action_stock_replenishment_info(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_stock_replenishment_info",
        )
        action["name"] = _(
            "Replenishment Information for %(product)s in %(warehouse)s",
            product=self.product_id.display_name,
            warehouse=self.warehouse_id.display_name,
        )
        res = self.env["stock.replenishment.info"].create(
            {
                "orderpoint_id": self.id,
            },
        )
        action["res_id"] = res.id
        return action

    def action_replenish(self, force_to_max=False):
        now = self.env.cr.now()
        forced_quantities = None
        if force_to_max:
            forced_quantities = {
                orderpoint.id: orderpoint._get_multiple_rounded_qty(
                    orderpoint.product_max_qty - orderpoint.qty_forecast,
                )
                for orderpoint in self
            }
        try:
            self._procure_orderpoint_confirm(
                company_id=self.env.company,
                forced_quantities=forced_quantities,
            )
        except UserError as e:
            if len(self) != 1:
                raise
            raise RedirectWarning(
                e,
                {
                    "name": self.product_id.display_name,
                    "type": "ir.actions.act_window",
                    "res_model": "product.product",
                    "res_id": self.product_id.id,
                    "views": [
                        (
                            self.env.ref("product.view_product_product_form_normal").id,
                            "form",
                        ),
                    ],
                },
                _("Edit Product"),
            ) from e
        notification = False
        if len(self) == 1:
            notification = self.with_context(
                written_after=now,
            )._get_replenishment_order_notification()
        self.action_remove_manual_qty_to_order()
        self._unlink_processed_orderpoints()
        return notification

    def action_replenish_auto(self):
        self.trigger = "auto"
        return self.action_replenish()

    def action_remove_manual_qty_to_order(self):
        self.write({"qty_to_order_manual": 0, "qty_to_order_manual_set": False})

    def _get_default_rule(self):
        self.ensure_one()
        return self.env["stock.rule"]._get_rule(
            self.product_id,
            self.location_id,
            {
                "route_ids": self.route_id,
                "warehouse_id": self.warehouse_id,
            },
        )

    def _get_default_route(self):
        self.ensure_one()
        return self._get_default_route_map().get(self.id, self.env["stock.route"])

    def _get_default_route_map(self):
        to_compute = self.filtered("location_id")
        empty_route = self.env["stock.route"]
        result = {orderpoint.id: empty_route for orderpoint in self}
        if not to_compute:
            return result
        rules_groups = self.env["stock.rule"]._read_group(
            [
                "|",
                ("route_id.product_selectable", "!=", False),
                ("route_id.product_categ_selectable", "!=", False),
                ("location_dest_id", "in", to_compute.location_id.ids),
                ("action", "in", ["pull_push", "pull"]),
                ("route_id.active", "!=", False),
            ],
            ["location_dest_id", "route_id"],
        )
        routes_by_location = defaultdict(list)
        for location_dest, route in rules_groups:
            routes_by_location[location_dest.id].append(route)
        for orderpoint in to_compute:
            product_routes = (
                orderpoint.product_id.route_ids
                | orderpoint.product_id.categ_id.route_ids
            )
            result[orderpoint.id] = next(
                (
                    route
                    for route in routes_by_location.get(orderpoint.location_id.id, ())
                    if route in product_routes
                ),
                empty_route,
            )
        return result

    def _get_replenishment_multiple_alternative(self, qty_to_order):
        self.ensure_one()
        return self._get_replenishment_multiple_alternative_map(
            {self.id: qty_to_order},
        ).get(self.id, False)

    def _get_replenishment_multiple_alternative_map(self, qty_by_orderpoint):
        return dict.fromkeys(self.ids, False)

    def _get_qty_to_order_map(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        result = {orderpoint.id: 0.0 for orderpoint in self - orderpoints_to_compute}
        if not orderpoints_to_compute:
            return result
        forecast_by_orderpoint = orderpoints_to_compute._get_qty_forecast_map()
        for orderpoint in orderpoints_to_compute:
            qty_forecast = forecast_by_orderpoint[orderpoint.id]
            if (
                orderpoint.product_uom_id.compare(
                    qty_forecast, orderpoint.product_min_qty
                )
                >= 0
            ):
                result[orderpoint.id] = 0.0
                continue
            qty_to_order = (
                max(orderpoint.product_min_qty, orderpoint.product_max_qty)
                - qty_forecast
            )
            result[orderpoint.id] = orderpoint._get_multiple_rounded_qty(qty_to_order)
        return result

    def _get_qty_to_order(self):
        self.ensure_one()
        return self._get_qty_to_order_map()[self.id]

    def _get_lead_days_values(self):
        self.ensure_one()
        return {
            "days_to_order": self.days_to_order,
        }

    def _get_lead_days_values_map(self):
        return {
            orderpoint.id: orderpoint._get_lead_days_values() for orderpoint in self
        }

    def _get_product_context(self):
        self.ensure_one()
        return {
            "location": self.location_id.id,
            "to_date": datetime.combine(self.lead_horizon_date, time.max),
        }

    @api.model
    def _get_orderpoint_action(self):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_orderpoint_replenish",
        )
        action["context"] = {
            key: value
            for key, value in self.env.context.items()
            if key.startswith(("search_default_", "searchpanel_default_", "default_"))
            or key in ("global_horizon_days", "allowed_company_ids", "lang", "tz")
        }
        orderpoints = (
            self.env["stock.warehouse.orderpoint"]
            .with_context(active_test=False)
            .search([])
        )
        if self.env.context.get("force_orderpoint_recompute", False):
            orderpoints._refresh_stored_values()
        orderpoints -= orderpoints._unlink_processed_orderpoints()
        self.env["stock.replenishment.report"]._create_missing_orderpoints(
            orderpoints,
        )
        return action

    def _refresh_stored_values(self):
        self._compute_qty_to_order_computed()
        self._compute_deadline_date()
        self._compute_lead_time_stats()

    @api.model
    def _get_orderpoint_values(self, product_id, location_id):
        return {
            "product_id": product_id,
            "location_id": location_id,
            "product_max_qty": 0.0,
            "product_min_qty": 0.0,
            "trigger": "manual",
            "is_autogenerated": True,
        }

    def _get_replenishment_source_domain(self):
        auto = self.filtered(lambda orderpoint: orderpoint.trigger == "auto")
        domain = Domain("orderpoint_id", "in", auto.ids)
        written_after = self.env.context.get("written_after")
        if not written_after:
            return domain
        manual = self - auto
        if manual:
            domain |= Domain("product_id", "in", manual.product_id.ids) & Domain(
                "company_id",
                "in",
                manual.company_id.ids,
            )
        return domain & Domain("write_date", ">=", written_after)

    @api.model
    def _build_replenishment_notification(self, title, label, url):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": "%s",
                "links": [{"label": label, "url": url}],
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _get_replenishment_order_notification(self):
        self.ensure_one()
        move = self.env["stock.move"].search(
            self._get_replenishment_source_domain(),
            limit=1,
        )
        if (
            (
                move.location_id.warehouse_id
                and move.location_id.warehouse_id != self.warehouse_id
            )
            or move.location_id.usage == "transit"
        ) and move.picking_id:
            return self._build_replenishment_notification(
                _("The inter-warehouse transfers have been generated"),
                move.picking_id.name,
                "/odoo/action-stock.stock_picking_action_picking_type/"
                f"{move.picking_id.id}",
            )
        return False

    def _get_orderpoint_procurement_date(self):
        self.ensure_one()
        return (
            datetime.combine(self.lead_horizon_date, time(12))
            .replace(tzinfo=timezone(self.company_id.partner_id.tz or "UTC"))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _get_multiple_rounded_qty(self, qty_to_order):
        replenishment_multiple = (
            self.replenishment_uom_id
            or self._get_replenishment_multiple_alternative(qty_to_order)
        )
        if replenishment_multiple and self.product_id.uom_id._has_common_reference(
            replenishment_multiple
        ):
            qty_to_order = self.product_id.uom_id._compute_quantity(
                qty_to_order,
                replenishment_multiple,
            )
            qty_to_order = fields.Float.round(
                qty_to_order,
                precision_digits=0,
                rounding_method="UP",
            )
            qty_to_order = replenishment_multiple._compute_quantity(
                qty_to_order,
                self.product_id.uom_id,
            )
        return qty_to_order

    def get_horizon_days(self):
        return self._get_canonical_horizon_days()

    def _get_horizon_days(self, company=None):
        return self.env.context.get(
            "global_horizon_days",
            self._get_canonical_horizon_days(company),
        )

    def _get_canonical_horizon_days(self, company=None):
        company = company or self.company_id or self.env.company
        return company.horizon_days

    def _canonical(self):
        if "global_horizon_days" not in self.env.context:
            return self
        return self.with_context(
            {
                key: value
                for key, value in self.env.context.items()
                if key != "global_horizon_days"
            },
        )

    def _prepare_procurement_vals(self, date=False):
        date_deadline = date or fields.Date.today()
        dates_info = self.product_id._get_dates_info(
            date_deadline,
            self.location_id,
            route_ids=self.route_id,
        )
        values = {
            "route_ids": self.route_id,
            "date_planned": dates_info["date_planned"],
            "date_order": dates_info["date_order"],
            "date_deadline": date or False,
            "warehouse_id": self.warehouse_id,
            "orderpoint_id": self.trigger == "auto" and self,
        }
        reference = self.env.context.get("origins")
        if reference:
            values["reference_ids"] = self.env["stock.reference"].browse(
                reference.get(self.id),
            )
        return values

    def _prepare_procurements(self, forced_quantities):
        procurements = []
        origins_by_orderpoint = self.env.context.get("origins", {})
        for orderpoint in self:
            quantity = forced_quantities.get(orderpoint.id, orderpoint.qty_to_order)
            if orderpoint.product_uom_id.compare(quantity, 0.0) != 1:
                continue
            origin_ids = origins_by_orderpoint.get(orderpoint.id, False)
            if origin_ids:
                references = self.env["stock.reference"].browse(origin_ids)
                origin = (
                    f"{orderpoint.display_name} - "
                    f"{','.join(references.mapped('name'))}"
                )
            else:
                origin = orderpoint.name
            date = orderpoint._get_orderpoint_procurement_date()
            horizon_days = orderpoint._get_horizon_days()
            if horizon_days:
                date -= relativedelta.relativedelta(days=horizon_days)
            procurements.append(
                self.env["stock.rule"].Procurement(
                    orderpoint.product_id,
                    quantity,
                    orderpoint.product_uom_id,
                    orderpoint.location_id,
                    orderpoint.name,
                    origin,
                    orderpoint.company_id,
                    orderpoint._prepare_procurement_vals(date=date),
                ),
            )
        return procurements

    def _run_procurement_batch(
        self,
        forced_quantities,
        raise_user_error=True,
        can_retry=False,
    ):
        orderpoints = self
        failures = []
        remaining_retries = self._PROCUREMENT_RETRIES
        while orderpoints:
            procurements = orderpoints._prepare_procurements(forced_quantities)
            try:
                with self.env.cr.savepoint():
                    self.env["stock.rule"].with_context(from_orderpoint=True).run(
                        procurements,
                        raise_user_error=raise_user_error,
                    )
            except ProcurementException as errors:
                batch_failures = [
                    (
                        procurement.values.get("orderpoint_id") or self.browse(),
                        error_msg,
                    )
                    for procurement, error_msg in errors.procurement_exceptions
                ]
                failures += batch_failures
                failed = self.browse().concat(
                    *[failure[0] for failure in batch_failures]
                )
                if not failed:
                    # Only a procurement that names its orderpoint can be dropped
                    # from the retry, and `_prepare_procurement_vals` records
                    # `orderpoint_id` for *auto* rows only -- deliberately, see
                    # `test_a_manual_orderpoint_is_told_what_its_order_created`. Every
                    # caller that reaches this branch selects `trigger = auto`
                    # (`stock.scheduler._replenish`, `stock_move._trigger_scheduler`)
                    # or passes `raise_user_error=True` (`action_replenish`), so it
                    # is unreachable today; a caller that broke that would land here,
                    # and the savepoint has already discarded the batch's successes.
                    _logger.error(
                        "Unable to attribute a procurement failure to an orderpoint;"
                        " %d orderpoints were rolled back and not retried: %s",
                        len(orderpoints),
                        "; ".join(msg for _op, msg in batch_failures),
                    )
                    break
                orderpoints -= failed
            except OperationalError as error:
                if error.sqlstate not in ("40001", "40P01") or not can_retry:
                    raise
                self.env.cr.rollback()
                remaining_retries -= 1
                if remaining_retries <= 0:
                    _logger.error(
                        "Serialization failure while processing a batch of %d "
                        "orderpoints; giving up after %d retries.",
                        len(orderpoints),
                        self._PROCUREMENT_RETRIES,
                    )
                    break
            else:
                orderpoints._post_process_scheduler()
                break
        return failures

    def _schedule_procurement_failure_activities(self, failures):
        model_product_template_id = self.env.ref("product.model_product_template").id
        for orderpoint, error_msg in failures:
            if not orderpoint:
                _logger.error("Orderpoint procurement failed: %s", error_msg)
                continue
            template = orderpoint.product_id.product_tmpl_id
            if self.env["mail.activity"].search_count(
                [
                    ("res_id", "=", template.id),
                    ("res_model_id", "=", model_product_template_id),
                    ("note", "=like", f"%{escape_psql(error_msg)}%"),
                ],
                limit=1,
            ):
                continue
            template.with_user(SUPERUSER_ID).activity_schedule(
                "mail.mail_activity_data_warning",
                note=error_msg,
                user_id=orderpoint.product_id.responsible_id.id or SUPERUSER_ID,
            )

    def _procure_orderpoint_confirm(
        self,
        use_new_cursor=False,
        company_id=None,
        raise_user_error=True,
        forced_quantities=None,
    ):
        scoped = self.with_company(company_id)
        forced_quantities = forced_quantities or {}
        dbname = self.env.cr.dbname

        for batch_ids in batched(scoped.ids, 1000, strict=False):
            cr = Registry(dbname).cursor() if use_new_cursor else None
            batch_env = scoped.env(cr=cr) if cr is not None else scoped.env
            committed = False
            try:
                batch = batch_env["stock.warehouse.orderpoint"].browse(batch_ids)
                failures = batch._run_procurement_batch(
                    forced_quantities,
                    raise_user_error=raise_user_error,
                    can_retry=use_new_cursor,
                )
                batch._schedule_procurement_failure_activities(failures)
                if cr is not None:
                    cr.commit()
                    committed = True
                    _logger.info(
                        "A batch of %d orderpoints is processed and committed",
                        len(batch_ids),
                    )
            finally:
                if cr is not None:
                    try:
                        if not committed:
                            cr.rollback()
                            _logger.warning(
                                "A batch of %d orderpoints failed and was rolled back",
                                len(batch_ids),
                            )
                    finally:
                        cr.close()

        return {}

    def _post_process_scheduler(self):
        return True

    def _quantity_in_progress(self):
        return dict.fromkeys(self._ids, 0.0)

    @api.autovacuum
    def _unlink_processed_orderpoints(self):
        domain = Domain(
            [
                ("is_autogenerated", "=", True),
                ("trigger", "=", "manual"),
                ("qty_to_order", "<=", 0.0),
            ],
        )
        if self.ids:
            domain &= Domain("id", "in", self.ids)
        orderpoints_to_remove = (
            self.env["stock.warehouse.orderpoint"]
            .with_context(active_test=False)
            .search(domain)
        )
        orderpoints_to_remove.unlink()
        return orderpoints_to_remove
