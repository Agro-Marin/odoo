import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, time
from itertools import batched

from dateutil import relativedelta
from psycopg import OperationalError

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.db import BaseCursor
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.datetime import timezone
from odoo.modules.registry import Registry
from odoo.tools import float_compare, format_date, frozendict

from odoo.addons.stock.const import PY_OPERATORS
from odoo.addons.stock.models.stock_procurement import ProcurementException

_logger = logging.getLogger(__name__)


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
    snoozed_until = fields.Date(string="Snoozed", help="Hidden until next scheduler.")
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
        name="Product Category",
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
    allowed_location_ids = fields.One2many(
        comodel_name="stock.location",
        compute="_compute_allowed_location_ids",
    )

    rule_ids = fields.Many2many(
        comodel_name="stock.rule",
        string="Rules used",
        compute="_compute_rules",
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
    qty_to_order_manual_zero = fields.Boolean(
        string="Suggestion Suppressed",
        default=False,
        help="Technical: the user explicitly set the quantity to order to 0 on this "
        "manually-triggered orderpoint, suppressing the computed suggestion until a "
        "non-zero quantity is entered or the replenishment is processed.",
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

    _QTY_TO_ORDER_SOURCE_FIELDS = frozenset(
        {
            "product_id",
            "location_id",
            "warehouse_id",
            "route_id",
            "product_min_qty",
            "product_max_qty",
            "replenishment_uom_id",
            "trigger",
            "company_id",
        },
    )

    @api.model
    def _drop_echoed_qty_to_order(self, vals):
        """Return `vals` without `qty_to_order` when its falsy value is an
        onchange echo rather than an explicit user entry.

        In a Form/list edit, changing any field the suggestion depends on makes
        the virtual record's `qty_to_order` compute to 0 (the stored suggestion
        skips NewId records on purpose), and the client sends that 0 back in the
        save payload together with the edited field. Writing it through would
        wrongly latch the explicit-zero suppression; dropping it lets the
        recompute produce the fresh suggestion. A `qty_to_order = 0` written
        without any suggestion-source sibling remains a genuine user zero and
        goes through to the inverse.
        """
        if (
            "qty_to_order" in vals
            and not vals["qty_to_order"]
            and self._QTY_TO_ORDER_SOURCE_FIELDS.intersection(vals)
        ):
            vals = {key: value for key, value in vals.items() if key != "qty_to_order"}
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._drop_echoed_qty_to_order(vals) for vals in vals_list]
        if any(
            val.get("snoozed_until", False)
            and val.get("trigger", self.default_get(["trigger"])["trigger"]) == "auto"
            for val in vals_list
        ):
            raise UserError(
                _(
                    "You can not create a snoozed orderpoint that is not manually triggered.",
                ),
            )
        return super().create(vals_list)

    def write(self, vals):
        vals = self._drop_echoed_qty_to_order(vals)
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

    def _compute_show_supply_warning(self):
        for orderpoint in self:
            orderpoint.show_supply_warning = not orderpoint.rule_ids

    @api.depends(
        "location_id",
        "product_min_qty",
        "route_id",
        "product_id.route_ids",
        "product_id.stock_move_ids.date",
        "product_id.stock_move_ids.state",
        "product_id.seller_ids",
        "product_id.seller_ids.delay",
        "company_id.horizon_days",
    )
    def _compute_deadline_date(self):
        """Set deadline_date to today if qty_on_hand is already below product_min_qty.
        Otherwise, walk incoming/outgoing moves up to the horizon date (today + horizon_days),
        applying them to qty_on_hand day by day, and use the date of the first move that brings
        it below product_min_qty (shifted back by lead_days) as the deadline.
        """
        self.fetch(["qty_on_hand"])
        critical_orderpoints = self.filtered(
            lambda o: o.product_uom_id.compare(o.qty_on_hand, o.product_min_qty) < 0,
        )
        critical_orderpoints.deadline_date = fields.Date.today()
        orderpoints_to_compute = self - critical_orderpoints
        if not orderpoints_to_compute:
            return

        for company in orderpoints_to_compute.company_id:
            company_orderpoints = orderpoints_to_compute.filtered(
                lambda c, company=company: c.company_id == company,
            )
            horizon_date = fields.Date.today() + relativedelta.relativedelta(
                days=company_orderpoints.get_horizon_days(),
            )
            _, domain_move_in, domain_move_out = (
                company_orderpoints.product_id._get_domain_locations_new(
                    company_orderpoints.location_id.ids,
                )
            )
            domain_move_in = Domain.AND(
                [
                    [("product_id", "in", company_orderpoints.product_id.ids)],
                    [
                        (
                            "state",
                            "in",
                            ("waiting", "confirmed", "assigned", "partially_available"),
                        ),
                    ],
                    domain_move_in,
                    [("date", "<=", horizon_date)],
                ],
            )
            domain_move_out = Domain.AND(
                [
                    [("product_id", "in", company_orderpoints.product_id.ids)],
                    [
                        (
                            "state",
                            "in",
                            ("waiting", "confirmed", "assigned", "partially_available"),
                        ),
                    ],
                    domain_move_out,
                    [("date", "<=", horizon_date)],
                ],
            )

            Move = self.env["stock.move"].with_context(active_test=False)
            incoming_moves_by_product_date = Move._read_group(
                domain_move_in,
                ["product_id", "location_dest_id", "location_final_id", "date:day"],
                ["product_qty:sum"],
            )
            outgoing_moves_by_product_date = Move._read_group(
                domain_move_out,
                ["product_id", "location_id", "date:day"],
                ["product_qty:sum"],
            )

            moves_by_product = defaultdict(list)
            for (
                product,
                location_dest,
                location_final,
                in_date,
                in_qty,
            ) in incoming_moves_by_product_date:
                arrival = location_final or location_dest
                moves_by_product[product.id].append(
                    (arrival.parent_path or "", in_date.date(), in_qty),
                )
            for product, location, out_date, out_qty in outgoing_moves_by_product_date:
                moves_by_product[product.id].append(
                    (location.parent_path or "", out_date.date(), -out_qty),
                )

            for orderpoint in company_orderpoints:
                location_path = orderpoint.location_id.parent_path or ""
                qty_by_date = defaultdict(float)
                for move_path, move_date, move_qty in moves_by_product.get(
                    orderpoint.product_id.id,
                    (),
                ):
                    if location_path and move_path.startswith(location_path):
                        qty_by_date[move_date] += move_qty
                qty_on_hand_at_date = orderpoint.qty_on_hand
                tentative_deadline = horizon_date
                for move_date, move_qty in sorted(qty_by_date.items()):
                    qty_on_hand_at_date += move_qty
                    if (
                        orderpoint.product_uom_id.compare(
                            qty_on_hand_at_date, orderpoint.product_min_qty
                        )
                        < 0
                    ):
                        tentative_deadline = move_date - relativedelta.relativedelta(
                            days=orderpoint.lead_days,
                        )
                        break
                orderpoint.deadline_date = (
                    tentative_deadline if tentative_deadline < horizon_date else False
                )

    @api.depends("product_id", "warehouse_id")
    def _compute_lead_time_stats(self):
        """Store avg/stddev/count of actual lead times per product/warehouse.

        The stored fields only ORM-recompute on `product_id`/`warehouse_id`, which never
        change after creation, so a newly completed receipt is never reflected. The
        scheduler (`stock.rule._run_scheduler_tasks`) and the replenishment report
        (`force_orderpoint_recompute`) call this explicitly to keep them fresh.
        """
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
        """Return {(product_id, warehouse_id): (avg_days, stddev_days, sample_count)}
        measured from the most recent completed incoming transfers (see
        `_LEAD_TIME_SAMPLE_SIZE`) landing in each warehouse's stock location tree
        within the last `_LEAD_TIME_LOOKBACK_DAYS` days.

        One sample per (product, picking): a receipt holding several done moves
        of the same product still counts once. Backorder receipts are excluded:
        they are created when their parent is validated, so their
        create -> done span is near zero and would drag the average down.
        Receipts whose create -> done span is under one hour are excluded for
        the same reason: they are ad-hoc immediate receipts (created and
        validated on the spot), not planned procurements, so their ~0-day
        "lead time" is noise that would skew the average and the standard
        deviation consumed by reordering engines.
        """
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
            parent_path = warehouse.lot_stock_id.parent_path
            if not product_ids or not parent_path:
                continue

            self.env.cr.execute(
                """
                WITH receipts AS (
                    SELECT DISTINCT ON (sm.product_id, sp.id)
                        sm.product_id,
                        sp.date_done,
                        EXTRACT(EPOCH FROM (sp.date_done - sp.create_date)) / 86400.0
                            AS lead_time_days
                    FROM stock_move sm
                    JOIN stock_picking sp ON sm.picking_id = sp.id
                    JOIN stock_picking_type spt ON sp.picking_type_id = spt.id
                    WHERE sp.state = 'done'
                      AND sm.state = 'done'
                      AND sp.date_done IS NOT NULL
                      AND sp.create_date IS NOT NULL
                      AND sp.backorder_id IS NULL
                      AND sp.date_done - sp.create_date >= interval '1 hour'
                      AND sp.date_done >= %s
                      AND spt.code = 'incoming'
                      AND sm.product_id = ANY(%s)
                      AND sp.location_dest_id IN (
                          SELECT id FROM stock_location
                          WHERE parent_path LIKE %s
                      )
                    ORDER BY sm.product_id, sp.id
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
                """,
                (
                    date_done_cutoff,
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
    def _compute_lead_days(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        for orderpoint in orderpoints_to_compute.with_context(
            bypass_delay_description=True,
        ):
            values = orderpoint._get_lead_days_values()
            lead_days, _dummy = orderpoint.rule_ids.with_context(
                global_horizon_days=orderpoint.get_horizon_days(),
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
        (self - orderpoints_to_compute).lead_horizon_date = False
        (self - orderpoints_to_compute).lead_days = 0

    @api.depends(
        "route_id",
        "product_id",
        "location_id",
        "company_id",
        "warehouse_id",
        "product_id.route_ids",
    )
    def _compute_rules(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        rules_cache = {}
        for orderpoint in orderpoints_to_compute:
            all_product_routes = (
                orderpoint.product_id.route_ids
                | orderpoint.product_id.categ_id.total_route_ids
                | orderpoint.product_id._get_total_routes()
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

    @api.depends("allowed_replenishment_uom_ids")
    def _compute_replenishment_uom_id_placeholder(self):
        for orderpoint in self:
            replenishment_alternative = (
                orderpoint._get_replenishment_multiple_alternative(
                    orderpoint.qty_to_order,
                )
            )
            orderpoint.replenishment_uom_id_placeholder = (
                replenishment_alternative.display_name
                if replenishment_alternative
                else ""
            )

    @api.depends("route_id", "product_id")
    def _compute_days_to_order(self):
        self.days_to_order = 0

    @api.depends("location_id", "company_id")
    def _compute_warehouse_id(self):
        for orderpoint in self:
            if orderpoint.location_id.warehouse_id:
                orderpoint.warehouse_id = orderpoint.location_id.warehouse_id
            elif orderpoint.company_id:
                orderpoint.warehouse_id = orderpoint.env["stock.warehouse"].search(
                    [("company_id", "=", orderpoint.company_id.id)],
                    limit=1,
                )
            if not orderpoint.warehouse_id:
                self.env["stock.warehouse"]._warehouse_redirect_warning()

    @api.depends("warehouse_id", "company_id")
    def _compute_location_id(self):
        """Finds location id for changed warehouse."""
        for orderpoint in self:
            warehouse = orderpoint.warehouse_id
            if not warehouse:
                warehouse = orderpoint.env["stock.warehouse"].search(
                    [("company_id", "=", orderpoint.company_id.id)],
                    limit=1,
                )
            orderpoint.location_id = warehouse.lot_stock_id.id

    @api.depends("product_id", "qty_to_order", "product_max_qty")
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

    @api.depends(
        "product_id",
        "location_id",
        "product_id.stock_move_ids",
        "product_id.stock_move_ids.state",
        "product_id.stock_move_ids.date",
        "product_id.stock_move_ids.product_uom_qty",
        "product_id.seller_ids.delay",
    )
    def _compute_qty(self):
        orderpoints_contexts = defaultdict(
            lambda: self.env["stock.warehouse.orderpoint"],
        )
        for orderpoint in self:
            if not orderpoint.product_id or not orderpoint.location_id:
                orderpoint.qty_on_hand = False
                orderpoint.qty_forecast = False
                continue
            orderpoint_context = orderpoint._get_product_context()
            product_context = frozendict({**orderpoint_context})
            orderpoints_contexts[product_context] |= orderpoint
        for orderpoint_context, orderpoints_by_context in orderpoints_contexts.items():
            products_qty = {
                p["id"]: p
                for p in orderpoints_by_context.product_id.with_context(
                    orderpoint_context,
                ).read(["qty_available", "qty_available_virtual"])
            }
            products_qty_in_progress = orderpoints_by_context._quantity_in_progress()
            for orderpoint in orderpoints_by_context:
                orderpoint.qty_on_hand = products_qty[orderpoint.product_id.id][
                    "qty_available"
                ]
                orderpoint.qty_forecast = (
                    products_qty[orderpoint.product_id.id]["qty_available_virtual"]
                    + products_qty_in_progress[orderpoint.id]
                )

    @api.depends(
        "qty_to_order_manual",
        "qty_to_order_computed",
        "qty_to_order_manual_zero",
    )
    def _compute_qty_to_order(self):
        for orderpoint in self:
            if orderpoint.qty_to_order_manual_zero:
                orderpoint.qty_to_order = 0.0
            else:
                orderpoint.qty_to_order = (
                    orderpoint.qty_to_order_manual or orderpoint.qty_to_order_computed
                )

    @api.depends(
        "replenishment_uom_id",
        "product_min_qty",
        "product_max_qty",
        "product_id",
        "location_id",
        "product_id.seller_ids.delay",
        "company_id.horizon_days",
    )
    def _compute_qty_to_order_computed(self):
        orderpoints = self.filtered(
            lambda orderpoint: orderpoint.id and orderpoint._is_below_min(),
        )
        (self - orderpoints).qty_to_order_computed = False
        if not orderpoints:
            return
        qty_in_progress_by_orderpoint = orderpoints._quantity_in_progress()
        orderpoints_contexts = defaultdict(
            lambda: self.env["stock.warehouse.orderpoint"],
        )
        for orderpoint in orderpoints:
            product_context = frozendict(orderpoint._get_product_context())
            orderpoints_contexts[product_context] |= orderpoint
        for orderpoint_context, orderpoints_by_context in orderpoints_contexts.items():
            qty_by_product = {
                p["id"]: p["qty_available_virtual"]
                for p in orderpoints_by_context.product_id.with_context(
                    orderpoint_context,
                ).read(["qty_available_virtual"])
            }
            for orderpoint in orderpoints_by_context:
                orderpoint.qty_to_order_computed = orderpoint._get_qty_to_order(
                    qty_in_progress_by_orderpoint=qty_in_progress_by_orderpoint,
                    qty_available_virtual=qty_by_product[orderpoint.product_id.id],
                )

    def _inverse_route_id(self):
        pass

    def _inverse_qty_to_order(self):
        for orderpoint in self:
            if orderpoint.trigger == "auto":
                orderpoint.qty_to_order_manual = 0
                orderpoint.qty_to_order_manual_zero = False
            elif not orderpoint.qty_to_order:
                orderpoint.qty_to_order_manual = 0
                orderpoint.qty_to_order_manual_zero = True
            else:
                orderpoint.qty_to_order_manual_zero = False
                if orderpoint.product_uom_id.compare(
                    orderpoint.qty_to_order, orderpoint.qty_to_order_computed
                ):
                    orderpoint.qty_to_order_manual = orderpoint.qty_to_order

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
            [("route_id", "=", False)],
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
        base_domain = Domain("qty_to_order_manual_zero", "=", False) & Domain(
            [
                "|",
                "&",
                ("qty_to_order_manual", "not in", [0, False]),
                ("qty_to_order_manual", operator, value),
                "&",
                ("qty_to_order_manual", "in", [0, False]),
                ("qty_to_order_computed", operator, value),
            ],
        )
        py_op = PY_OPERATORS.get(operator)
        if py_op is None:
            return NotImplemented
        if isinstance(value, Iterable) and not isinstance(value, str):
            compare_value = {float(v) for v in value}
        else:
            compare_value = float(value)
        if py_op(0.0, compare_value):
            return base_domain | Domain("qty_to_order_manual_zero", "=", True)
        return base_domain

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.product_id.action_product_forecast_report()
        action["context"] = {
            "active_id": self.product_id.id,
            "active_model": "product.product",
            "lead_horizon_date": format_date(self.env, self.lead_horizon_date),
            "qty_to_order": self._get_qty_to_order(),
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
        action = self.env["ir.actions.actions"]._for_xml_id(
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
        self._compute_qty_to_order()
        self._unlink_processed_orderpoints()
        return notification

    def action_replenish_auto(self):
        self.trigger = "auto"
        return self.action_replenish()

    def action_remove_manual_qty_to_order(self):
        self.write({"qty_to_order_manual": 0, "qty_to_order_manual_zero": False})

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
        """Return {orderpoint.id: default stock.route} for the whole recordset in a
        single grouped query, instead of one `_read_group` per record.

        Override-friendly: modules layering action-specific routes (buy, manufacture)
        call `super()` first, then overwrite the ids they own. Applying overrides
        bottom-up reproduces the top-down short-circuit precedence of the old
        per-record `_get_default_route`.
        """
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
        """Return a fallback replenishment UoM when replenishment_uom_id isn't set manually.
        To be overridden in relevant modules.
        """
        return False

    def _is_below_min(self):
        """Whether the lead-time-horizon forecast is below product_min_qty, i.e. there
        is a shortage to resupply. Shared by the qty_to_order computation and filter.
        """
        self.ensure_one()
        return (
            float_compare(
                self.qty_forecast,
                self.product_min_qty,
                precision_rounding=self.product_uom_id.rounding,
            )
            < 0
        )

    def _get_qty_to_order(
        self,
        qty_in_progress_by_orderpoint=None,
        qty_available_virtual=None,
    ):
        """Compute how much to order to reach min/max, given the horizon forecast.

        The forecast is always re-derived here from ``qty_available_virtual``
        plus a fresh ``_quantity_in_progress()`` — never from the cached
        ``qty_forecast`` field: pending replenishments that involve no stock
        move yet (draft RFQs, sibling procurements) don't invalidate that
        field's cache, so reusing it re-orders quantities they already cover.

        :param qty_in_progress_by_orderpoint: optional pre-batched result of
            ``_quantity_in_progress()`` covering ``self``, to avoid one call
            per orderpoint in loops.
        :param qty_available_virtual: optional pre-batched virtual availability
            of this orderpoint's product under ``_get_product_context()``
            (see ``_compute_qty_to_order_computed``), to avoid one full
            forecast read per orderpoint in loops.
        """
        self.ensure_one()
        if not self._is_below_min():
            return 0.0
        qty_in_progress_by_orderpoint = qty_in_progress_by_orderpoint or {}
        qty_in_progress = qty_in_progress_by_orderpoint.get(self.id)
        if qty_in_progress is None:
            qty_in_progress = self._quantity_in_progress()[self.id]
        if qty_available_virtual is None:
            product_context = self._get_product_context()
            qty_available_virtual = self.product_id.with_context(product_context).read(
                ["qty_available_virtual"],
            )[0]["qty_available_virtual"]
        qty_forecast = qty_available_virtual + qty_in_progress
        qty_to_order = max(self.product_min_qty, self.product_max_qty) - qty_forecast
        return self._get_multiple_rounded_qty(qty_to_order)

    def _get_lead_days_values(self):
        self.ensure_one()
        return {
            "days_to_order": self.days_to_order,
        }

    def _get_product_context(self):
        """Used to call `qty_available_virtual` when running an orderpoint."""
        self.ensure_one()
        return {
            "location": self.location_id.id,
            "to_date": datetime.combine(self.lead_horizon_date, time.max),
        }

    def _get_orderpoint_action(self):
        """Create manual orderpoints for products projected to run short in replenishable
        locations, and remove auto-created orderpoints that have already been resolved.

        For each product/location, the projected quantity (on hand + incoming - outgoing,
        re-evaluated over each product's lead-time horizon) is netted against quantities
        already covered by other sources (e.g. RFQs) or by other orderpoints on the same
        product/location, before creating or updating orderpoints for the remaining shortage.

        :return: the replenishment report action.
        """

        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_orderpoint_replenish",
        )
        action["context"] = self.env.context
        orderpoints = (
            self.env["stock.warehouse.orderpoint"]
            .with_context(active_test=False)
            .search([])
        )
        orderpoints_removed = orderpoints._unlink_processed_orderpoints()
        orderpoints -= orderpoints_removed
        if self.env.context.get("force_orderpoint_recompute", False):
            orderpoints._compute_qty_to_order_computed()
            orderpoints._compute_deadline_date()
            orderpoints._compute_lead_time_stats()
        to_refill = defaultdict(float)
        all_product_ids = self._get_orderpoint_products()
        all_replenish_location_ids = self._get_orderpoint_locations()
        ploc_per_day = defaultdict(set)

        Move = self.env["stock.move"].with_context(active_test=False)
        Quant = self.env["stock.quant"].with_context(active_test=False)
        domain_quant, domain_move_in_loc, domain_move_out_loc = (
            all_product_ids._get_domain_locations_new(all_replenish_location_ids.ids)
        )
        domain_state = Domain(
            "state",
            "in",
            ("waiting", "confirmed", "assigned", "partially_available"),
        )
        domain_product = Domain("product_id", "in", all_product_ids.ids)

        domain_quant = Domain.AND((domain_product, domain_quant))
        domain_move_in = Domain.AND((domain_product, domain_state, domain_move_in_loc))
        domain_move_out = Domain.AND(
            (domain_product, domain_state, domain_move_out_loc),
        )

        replenish_ids = set(all_replenish_location_ids.ids)
        replenish_ancestors_by_location = {}

        def replenish_ancestors(location):
            """Ids of the replenish locations whose subtree contains `location`."""
            if not location:
                return ()
            ancestors = replenish_ancestors_by_location.get(location.id)
            if ancestors is None:
                ancestors = tuple(
                    ancestor_id
                    for ancestor_id in map(
                        int,
                        (location.parent_path or "").split("/")[:-1],
                    )
                    if ancestor_id in replenish_ids
                )
                replenish_ancestors_by_location[location.id] = ancestors
            return ancestors

        net_qty_by_product_loc = defaultdict(float)
        for product, location_dest, location_final, qty in Move._read_group(
            domain_move_in,
            ["product_id", "location_dest_id", "location_final_id"],
            ["product_qty:sum"],
        ):
            for replenish_id in {
                *replenish_ancestors(location_dest),
                *replenish_ancestors(location_final),
            }:
                net_qty_by_product_loc[product, replenish_id] += qty
        for product, location, qty in Move._read_group(
            domain_move_out,
            ["product_id", "location_id"],
            ["product_qty:sum"],
        ):
            for replenish_id in replenish_ancestors(location):
                net_qty_by_product_loc[product, replenish_id] -= qty
        for product, location, qty in Quant._read_group(
            domain_quant,
            ["product_id", "location_id"],
            ["quantity:sum"],
        ):
            for replenish_id in replenish_ancestors(location):
                net_qty_by_product_loc[product, replenish_id] += qty

        replenish_location_by_id = {loc.id: loc for loc in all_replenish_location_ids}
        for (product, replenish_id), net_qty in net_qty_by_product_loc.items():
            if product.uom_id.compare(net_qty, 0) >= 0:
                continue
            loc = replenish_location_by_id[replenish_id]
            loc_horizon_days = self.env.context.get(
                "global_horizon_days",
                (loc.company_id or self.env.company).horizon_days,
            )
            rules = product._get_rules_from_location(loc)
            lead_days = rules.with_context(
                bypass_delay_description=True,
                global_horizon_days=loc_horizon_days,
            )._get_lead_days(product)[0]
            ploc_per_day[
                lead_days["total_delay"] + lead_days["horizon_time"],
                loc,
            ].add(product.id)

        today = fields.Datetime.now().replace(hour=23, minute=59, second=59)
        product_ids = set()
        location_ids = set()
        for (days, loc), prod_ids in ploc_per_day.items():
            products = self.env["product.product"].browse(prod_ids)
            qties = products.with_context(
                location=loc.id,
                to_date=today + relativedelta.relativedelta(days=days),
            ).read(["qty_available_virtual"])
            for product, qty in zip(products, qties, strict=False):
                if product.uom_id.compare(qty["qty_available_virtual"], 0) < 0:
                    to_refill[qty["id"], loc.id] = qty["qty_available_virtual"]
                    product_ids.add(qty["id"])
                    location_ids.add(loc.id)
            products.invalidate_recordset()
        if not to_refill:
            return action

        product_ids = list(product_ids)
        location_ids = list(location_ids)
        qty_by_product_loc = (
            self.env["product.product"]
            .browse(product_ids)
            ._get_quantity_in_progress(location_ids=location_ids)[0]
        )
        rounding = self.env["decimal.precision"].precision_get("Product Unit")
        orderpoint_by_product_location = self.env[
            "stock.warehouse.orderpoint"
        ]._read_group(
            [("id", "in", orderpoints.ids), ("product_id", "in", product_ids)],
            ["product_id", "location_id"],
            ["id:recordset"],
        )
        orderpoint_by_product_location = {
            (product.id, location.id): sum(group_orderpoints.mapped("qty_to_order"))
            for product, location, group_orderpoints in orderpoint_by_product_location
        }
        for (product, location), product_qty in to_refill.items():
            qty_in_progress = qty_by_product_loc.get((product, location)) or 0.0
            qty_in_progress += orderpoint_by_product_location.get(
                (product, location),
                0.0,
            )
            if not qty_in_progress:
                continue
            to_refill[product, location] = product_qty + qty_in_progress
        to_refill = {
            k: v
            for k, v in to_refill.items()
            if float_compare(v, 0.0, precision_digits=rounding) < 0.0
        }

        orderpoint_by_product_location = (
            self.env["stock.warehouse.orderpoint"]
            .with_context(active_test=False)
            ._read_group(
                [("id", "in", orderpoints.ids), ("product_id", "in", product_ids)],
                ["product_id", "location_id"],
                ["id:recordset"],
            )
        )
        orderpoint_by_product_location = {
            (product.id, location.id): orderpoint
            for product, location, orderpoint in orderpoint_by_product_location
        }

        orderpoint_values_list = []
        for (product, location_id), product_qty in to_refill.items():
            orderpoint = orderpoint_by_product_location.get((product, location_id))
            if orderpoint:
                orderpoint.qty_forecast += product_qty
            else:
                orderpoint_values = self.env[
                    "stock.warehouse.orderpoint"
                ]._get_orderpoint_values(product, location_id)
                location = self.env["stock.location"].browse(location_id)
                orderpoint_values.update(
                    {
                        "name": _("Replenishment Report"),
                        "warehouse_id": location.warehouse_id.id
                        or self.env["stock.warehouse"]
                        .search([("company_id", "=", location.company_id.id)], limit=1)
                        .id,
                        "company_id": location.company_id.id,
                    },
                )
                orderpoint_values_list.append(orderpoint_values)

        orderpoints = (
            self.env["stock.warehouse.orderpoint"]
            .with_user(SUPERUSER_ID)
            .create(orderpoint_values_list)
        )
        return action

    @api.model
    def _get_orderpoint_values(self, product, location):
        return {
            "product_id": product,
            "location_id": location,
            "product_max_qty": 0.0,
            "product_min_qty": 0.0,
            "trigger": "manual",
            "is_autogenerated": True,
        }

    def _get_replenishment_order_notification(self):
        self.ensure_one()
        domain = Domain("orderpoint_id", "in", self.ids)
        if self.env.context.get("written_after"):
            domain &= Domain("write_date", ">=", self.env.context.get("written_after"))
        move = self.env["stock.move"].search(domain, limit=1)
        if (
            (
                move.location_id.warehouse_id
                and move.location_id.warehouse_id != self.warehouse_id
            )
            or move.location_id.usage == "transit"
        ) and move.picking_id:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("The inter-warehouse transfers have been generated"),
                    "message": "%s",
                    "links": [
                        {
                            "label": move.picking_id.name,
                            "url": f"/odoo/action-stock.stock_picking_action_picking_type/{move.picking_id.id}",
                        },
                    ],
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return False

    def _get_orderpoint_procurement_date(self):
        return (
            datetime.combine(self.lead_horizon_date, time(12))
            .replace(tzinfo=timezone(self.company_id.partner_id.tz or "UTC"))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _get_orderpoint_products(self):
        return self.env["product.product"].search(
            [("is_storable", "=", True), ("stock_move_ids", "!=", False)],
        )

    def _get_orderpoint_locations(self):
        return self.env["stock.location"].search([("replenish_location", "=", True)])

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
        """Return the horizon in days: the context value set by the replenishment view if
        present, otherwise the horizon_days of self's company (self should have at most one
        company), falling back to the current user's company.
        """
        return self.env.context.get(
            "global_horizon_days",
            (self.company_id or self.env.company).horizon_days,
        )

    def _prepare_procurement_vals(self, date=False):
        """Prepare procurement values for the stock rule triggered by this orderpoint.
        Can be overridden to add custom keys used in move/PO creation.
        """
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

    def _procure_orderpoint_confirm(
        self,
        use_new_cursor=False,
        company_id=None,
        raise_user_error=True,
        forced_quantities=None,
    ):
        """Create procurements based on orderpoints.
        :param bool use_new_cursor: if set, use a dedicated cursor and auto-commit after processing
            1000 orderpoints.
            This is appropriate for batch jobs only.
        :param dict forced_quantities: optional {orderpoint_id: qty} mapping
            overriding `qty_to_order` for the procurement quantities (e.g.
            `action_replenish(force_to_max=True)`), without round-tripping the
            override through the field and its inverse.
        """
        self = self.with_company(company_id)
        forced_quantities = forced_quantities or {}

        for orderpoints_batch_ids in batched(self.ids, 1000, strict=False):
            if use_new_cursor:
                assert isinstance(self.env.cr, BaseCursor)
                cr = Registry(self.env.cr.dbname).cursor()
                self = self.with_env(self.env(cr=cr))
            try:
                orderpoints_batch = self.env["stock.warehouse.orderpoint"].browse(
                    orderpoints_batch_ids,
                )
                all_orderpoints_exceptions = []
                remaining_retries = self._PROCUREMENT_RETRIES
                while orderpoints_batch:
                    procurements = []
                    for orderpoint in orderpoints_batch:
                        origins = orderpoint.env.context.get("origins", {}).get(
                            orderpoint.id,
                            False,
                        )
                        if origins:
                            origins = self.env["stock.reference"].browse(origins)
                            origin = "%s - %s" % (
                                orderpoint.display_name,
                                ",".join(origins.mapped("name")),
                            )
                        else:
                            origin = orderpoint.name
                        qty_to_order = forced_quantities.get(
                            orderpoint.id,
                            orderpoint.qty_to_order,
                        )
                        if orderpoint.product_uom_id.compare(qty_to_order, 0.0) == 1:
                            date = orderpoint._get_orderpoint_procurement_date()
                            global_horizon_days = orderpoint.get_horizon_days()
                            if global_horizon_days:
                                date -= relativedelta.relativedelta(
                                    days=global_horizon_days,
                                )
                            values = orderpoint._prepare_procurement_vals(date=date)
                            procurements.append(
                                self.env["stock.rule"].Procurement(
                                    orderpoint.product_id,
                                    qty_to_order,
                                    orderpoint.product_uom_id,
                                    orderpoint.location_id,
                                    orderpoint.name,
                                    origin,
                                    orderpoint.company_id,
                                    values,
                                ),
                            )

                    try:
                        with self.env.cr.savepoint():
                            self.env["stock.rule"].with_context(
                                from_orderpoint=True,
                            ).run(procurements, raise_user_error=raise_user_error)
                    except ProcurementException as errors:
                        orderpoints_exceptions = []
                        for procurement, error_msg in errors.procurement_exceptions:
                            orderpoints_exceptions += [
                                (
                                    procurement.values.get("orderpoint_id")
                                    or self.env["stock.warehouse.orderpoint"],
                                    error_msg,
                                ),
                            ]
                        all_orderpoints_exceptions += orderpoints_exceptions
                        failed_orderpoints = self.env[
                            "stock.warehouse.orderpoint"
                        ].concat(*[o[0] for o in orderpoints_exceptions])
                        if not failed_orderpoints:
                            _logger.error("Unable to process orderpoints")
                            break
                        orderpoints_batch -= failed_orderpoints

                    except OperationalError as e:
                        if e.sqlstate not in ("40001", "40P01"):
                            raise
                        if use_new_cursor:
                            cr.rollback()
                            remaining_retries -= 1
                            if remaining_retries <= 0:
                                _logger.error(
                                    "Serialization failure while processing a batch "
                                    "of %d orderpoints; giving up after %d retries.",
                                    len(orderpoints_batch),
                                    self._PROCUREMENT_RETRIES,
                                )
                                break
                            continue
                        raise
                    else:
                        orderpoints_batch._post_process_scheduler()
                        break

                for orderpoint, error_msg in all_orderpoints_exceptions:
                    if not orderpoint:
                        _logger.error("Orderpoint procurement failed: %s", error_msg)
                        continue
                    existing_activity = self.env["mail.activity"].search_count(
                        [
                            ("res_id", "=", orderpoint.product_id.product_tmpl_id.id),
                            (
                                "res_model_id",
                                "=",
                                self.env.ref("product.model_product_template").id,
                            ),
                            ("note", "like", error_msg),
                        ],
                        limit=1,
                    )
                    if not existing_activity:
                        orderpoint.product_id.product_tmpl_id.with_user(
                            SUPERUSER_ID,
                        ).activity_schedule(
                            "mail.mail_activity_data_warning",
                            note=error_msg,
                            user_id=orderpoint.product_id.responsible_id.id
                            or SUPERUSER_ID,
                        )

            finally:
                if use_new_cursor:
                    try:
                        cr.commit()
                    finally:
                        cr.close()
                    _logger.info(
                        "A batch of %d orderpoints is processed and committed",
                        len(orderpoints_batch_ids),
                    )

        return {}

    def _post_process_scheduler(self):
        return True

    def _quantity_in_progress(self):
        """Return, per orderpoint id, the quantity not yet reflected in virtual stock but
        already accounted for by this rule (e.g. purchases created from orderpoints).
        To be overridden; returns 0 for all orderpoints by default.
        """
        return dict(self.mapped(lambda x: (x.id, 0.0)))

    @api.autovacuum
    def _unlink_processed_orderpoints(self):
        """Delete auto-created manual orderpoints (`is_autogenerated`) that no longer
        have anything to order, i.e. the shortage they were created for has been resolved.

        Keyed on the explicit `is_autogenerated` flag, not `create_uid = SUPERUSER_ID`:
        the latter also matched manual orderpoints genuinely created by an
        administrator, silently deleting them.
        """
        domain = Domain(
            [
                ("is_autogenerated", "=", True),
                ("trigger", "=", "manual"),
            ],
        )
        if self.ids:
            domain &= Domain("id", "in", self.ids)
        manual_orderpoints = (
            self.env["stock.warehouse.orderpoint"]
            .with_context(active_test=False)
            .search(domain)
        )
        orderpoints_to_remove = manual_orderpoints.filtered(
            lambda o: o.product_uom_id.compare(o.qty_to_order, 0.0) <= 0,
        )
        orderpoints_to_remove.unlink()
        return orderpoints_to_remove
