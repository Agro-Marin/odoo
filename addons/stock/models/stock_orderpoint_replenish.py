import logging
from collections import defaultdict
from datetime import UTC, datetime, time
from itertools import batched

from dateutil import relativedelta
from psycopg import OperationalError

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.fields import Domain
from odoo.libs.datetime import timezone
from odoo.libs.debug_log import DebugLog
from odoo.modules.registry import Registry
from odoo.tools import format_date

from odoo.addons.stock.models.stock_procurement import ProcurementException

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


class StockWarehouseOrderpointReplenish(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    @_debug.perf.timed
    def action_replenish(self, force_to_max=False):
        _debug.pipeline("action_replenish", orderpoints=self, force_to_max=force_to_max)
        now = self.env.cr.now()
        forced_quantities = None
        if force_to_max:
            forced_quantities = self._get_multiple_rounded_qty_map(
                {
                    orderpoint.id: orderpoint.product_max_qty - orderpoint.qty_forecast
                    for orderpoint in self
                }
            )
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
                self.env._("Edit Product"),
            ) from e
        notification = False
        if len(self) == 1:
            notification = self.with_context(
                written_after=now,
            )._prepare_action_replenishment_order_notification()
        self.action_remove_manual_qty_to_order()
        self._remove_processed_orderpoints()
        return notification

    def action_replenish_auto(self):
        self.trigger = "auto"
        return self.action_replenish()

    def action_remove_manual_qty_to_order(self):
        self.write({"qty_to_order_manual": 0, "qty_to_order_manual_set": False})

    def _get_default_rule_map(self):
        Rule = self.env["stock.rule"]
        procurements = [
            Rule.Procurement(
                orderpoint.product_id,
                0.0,
                orderpoint.product_uom_id,
                orderpoint.location_id,
                orderpoint.name,
                orderpoint.name,
                orderpoint.company_id,
                {
                    "route_ids": orderpoint.route_id,
                    "warehouse_id": orderpoint.warehouse_id,
                },
            )
            for orderpoint in self
        ]
        return dict(zip(self, Rule._get_rules_batch(procurements), strict=True))

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
                | orderpoint.product_id.categ_id.total_route_ids
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

    def _get_replenishment_multiple_alternative_map(self, qty_by_orderpoint):
        return dict.fromkeys(self.ids, False)

    @_debug.perf.timed
    def _get_qty_to_order_map(self):
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.product_id and orderpoint.location_id,
        )
        result = {orderpoint.id: 0.0 for orderpoint in self - orderpoints_to_compute}
        if not orderpoints_to_compute:
            return result
        forecast_by_orderpoint = orderpoints_to_compute._get_qty_forecast_map()
        to_order = {}
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
            to_order[orderpoint.id] = (
                max(orderpoint.product_min_qty, orderpoint.product_max_qty)
                - qty_forecast
            )
        rounded = orderpoints_to_compute.filtered(
            lambda orderpoint: orderpoint.id in to_order
        )._get_multiple_rounded_qty_map(to_order)
        for orderpoint_id, qty_to_order in to_order.items():
            result[orderpoint_id] = rounded[orderpoint_id]
            _debug.logic(
                "qty_to_order",
                orderpoint=orderpoint_id,
                forecast=forecast_by_orderpoint[orderpoint_id],
                qty=qty_to_order,
                rounded=rounded[orderpoint_id],
            )
        return result

    def _prepare_lead_time_params(self):
        self.check_singleton()
        return {
            "days_to_order": self.days_to_order,
        }

    def _prepare_lead_time_params_map(self):
        return {
            orderpoint.id: orderpoint._prepare_lead_time_params() for orderpoint in self
        }

    def _prepare_product_context(self):
        self.check_singleton()
        return {
            "location": self.location_id.id,
            "to_date": self._get_company_moment(self.lead_horizon_date, time.max),
        }

    @api.model
    def _prepare_action_orderpoint_replenish(self):
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
            orderpoints._update_stored_values()
        orderpoints -= orderpoints._remove_processed_orderpoints()
        self.env["stock.replenishment.report"]._create_missing_orderpoints(
            orderpoints,
        )
        return action

    def _update_stored_values(self):
        stored = ("qty_to_order_computed", "deadline_date", "actual_lead_time_avg")
        for field_name in stored:
            self.env.add_to_compute(self._fields[field_name], self)
        self.flush_recordset(stored)

    @api.model
    def _prepare_orderpoint_vals(self, product_id, location_id):
        return {
            "product_id": product_id,
            "location_id": location_id,
            "product_max_qty": 0.0,
            "product_min_qty": 0.0,
            "trigger": "manual",
            "is_autogenerated": True,
        }

    def _get_domain_replenishment_source(self):
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
    def _prepare_action_replenishment_notification(self, title, label, url):
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

    def _prepare_action_replenishment_order_notification(self):
        self.check_singleton()
        move = self.env["stock.move"].search(
            self._get_domain_replenishment_source(),
            limit=1,
        )
        if (
            (
                move.location_id.warehouse_id
                and move.location_id.warehouse_id != self.warehouse_id
            )
            or move.location_id.usage == "transit"
        ) and move.picking_id:
            return self._prepare_action_replenishment_notification(
                self.env._("The inter-warehouse transfers have been generated"),
                move.picking_id.name,
                "/odoo/action-stock.stock_picking_action_picking_type/"
                f"{move.picking_id.id}",
            )
        return False

    def _get_company_timezone(self, company=None):
        company = company or self.company_id[:1] or self.env.company
        return timezone(company.partner_id.tz or "UTC")

    def _get_company_today(self, company=None):
        return (
            fields.Datetime.now()
            .replace(tzinfo=UTC)
            .astimezone(self._get_company_timezone(company))
            .date()
        )

    def _get_company_moment(self, day, at, company=None):
        return (
            datetime.combine(day, at)
            .replace(tzinfo=self._get_company_timezone(company))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def _get_orderpoint_procurement_date(self):
        self.check_singleton()
        return self._get_company_moment(self.lead_horizon_date, time(12))

    def _get_procurement_date(self):
        self.check_singleton()
        date = self._get_orderpoint_procurement_date()
        horizon_days = self._get_horizon_days()
        if horizon_days:
            date -= relativedelta.relativedelta(days=horizon_days)
        return date

    def _get_origin_references(self):
        self.check_singleton()
        origin_ids = (self.env.context.get("origins") or {}).get(self.id)
        return self.env["stock.reference"].browse(sorted(origin_ids or ()))

    def _get_multiple_rounded_qty_map(self, qty_by_orderpoint):
        alternatives = self.filtered(
            lambda orderpoint: not orderpoint.replenishment_uom_id
        )._get_replenishment_multiple_alternative_map(qty_by_orderpoint)
        _debug.perf.count(
            "rounded_qty_map", orderpoints=len(self), alternatives=len(alternatives)
        )
        return {
            orderpoint.id: orderpoint._round_to_multiple(
                qty_by_orderpoint[orderpoint.id],
                orderpoint.replenishment_uom_id or alternatives.get(orderpoint.id),
            )
            for orderpoint in self
        }

    def _round_to_multiple(self, qty_to_order, replenishment_multiple):
        self.check_singleton()
        if replenishment_multiple and self.product_id.uom_id._has_common_reference(
            replenishment_multiple
        ):
            qty_to_order = self.product_id.uom_id._get_quantity_in_unit(
                qty_to_order,
                replenishment_multiple,
            )
            qty_to_order = fields.Float.round(
                qty_to_order,
                precision_digits=0,
                rounding_method="UP",
            )
            qty_to_order = replenishment_multiple._get_quantity_in_unit(
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
        return company.stock_config_id.horizon_days

    def _with_canonical_horizon(self):
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
        date_deadline = date or self._get_company_today()
        dates_info = self.product_id._get_dates_info(
            date_deadline,
            self.location_id,
            route_ids=self.route_id,
            rules=self.rule_ids,
        )
        values = {
            "route_ids": self.route_id,
            "date_planned": dates_info["date_planned"],
            "date_order": dates_info["date_order"],
            "date_deadline": date or False,
            "warehouse_id": self.warehouse_id,
            "orderpoint_id": self.trigger == "auto" and self,
        }
        if self.env.context.get("origins"):
            values["reference_ids"] = self._get_origin_references()
        return values

    def _prepare_procurements(self, forced_quantities):
        procurements = []
        for orderpoint in self:
            quantity = forced_quantities.get(orderpoint.id, orderpoint.qty_to_order)
            if orderpoint.product_uom_id.compare(quantity, 0.0) != 1:
                _debug.logic(
                    "nothing_to_procure", orderpoint=orderpoint.id, qty=quantity
                )
                continue
            references = orderpoint._get_origin_references()
            if references:
                origin = (
                    f"{orderpoint.display_name} - {','.join(references.mapped('name'))}"
                )
            else:
                origin = orderpoint.name
            date = orderpoint._get_procurement_date()
            _debug.pipeline(
                "procurement_prepared",
                orderpoint=orderpoint.id,
                product=orderpoint.product_id.id,
                qty=quantity,
                date=date,
                origin=origin,
            )
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
        failures = []
        pending = [self]
        remaining_retries = self._PROCUREMENT_RETRIES
        while pending:
            orderpoints = pending.pop()
            if not orderpoints:
                continue
            procurements = orderpoints._prepare_procurements(forced_quantities)
            _debug.pipeline(
                "procurement_batch",
                orderpoints=len(orderpoints),
                procurements=len(procurements),
                retries_left=remaining_retries,
            )
            try:
                with self.env.cr.savepoint():
                    self.env["stock.rule"].with_context(from_orderpoint=True).run(
                        procurements,
                        raise_user_error=raise_user_error,
                    )
            except ProcurementException as errors:
                attributed = [
                    (
                        procurement.values.get("orderpoint_id") or self.browse(),
                        error_msg,
                    )
                    for procurement, error_msg in errors.procurement_exceptions
                ]
                failed = self.browse().concat(*[failure[0] for failure in attributed])
                _debug.logic(
                    "procurement_batch_failures",
                    failures=len(attributed),
                    failed=failed,
                )
                if failed:
                    failures += [failure for failure in attributed if failure[0]]
                    pending.append(orderpoints - failed)
                    continue
                isolated, chunks = orderpoints._split_failing_batch(
                    "; ".join(msg for _orderpoint, msg in attributed),
                )
                failures += isolated
                pending += chunks
            except UserError as error:
                if raise_user_error:
                    raise
                isolated, chunks = orderpoints._split_failing_batch(str(error))
                failures += isolated
                pending += chunks
            except OperationalError as error:
                if error.sqlstate not in ("40001", "40P01") or not can_retry:
                    raise
                _debug.logic(
                    "procurement_batch_serialization_failure", sqlstate=error.sqlstate
                )
                self.env.cr.rollback()
                remaining_retries -= 1
                if remaining_retries <= 0:
                    _logger.error(
                        "Serialization failure while processing a batch of %d "
                        "orderpoints; giving up after %d retries.",
                        len(self),
                        self._PROCUREMENT_RETRIES,
                    )
                    return []
                failures = []
                pending = [self]
            else:
                orderpoints._post_process_scheduler()
        return failures

    def _split_failing_batch(self, error_msg):
        if len(self) == 1:
            _debug.logic("procurement_batch_failing", orderpoints=self)
            return [(self, error_msg)], []
        half = len(self) // 2
        _debug.logic("procurement_batch_bisect", orderpoints=self)
        return [], [self[half:], self[:half]]

    def _schedule_procurement_failure_activities(self, failures):
        model_product_template_id = self.env.ref("product.model_product_template").id
        reported = []
        for orderpoint, error_msg in failures:
            if orderpoint:
                reported.append((orderpoint, error_msg))
            else:
                _logger.error("Orderpoint procurement failed: %s", error_msg)

        orderpoints = self.browse()
        for orderpoint, _error_msg in reported:
            orderpoints |= orderpoint
        templates = orderpoints.product_id.product_tmpl_id
        notes_per_template = defaultdict(list)
        for activity in self.env["mail.activity"].search(
            [
                ("res_id", "in", templates.ids),
                ("res_model_id", "=", model_product_template_id),
            ]
        ):
            notes_per_template[activity.res_id].append(activity.note or "")

        for orderpoint, error_msg in reported:
            template = orderpoint.product_id.product_tmpl_id
            if any(error_msg in note for note in notes_per_template[template.id]):
                continue
            template.with_user(SUPERUSER_ID).activity_schedule(
                "mail.mail_activity_data_warning",
                note=error_msg,
                user_id=orderpoint.product_id.responsible_id.id or SUPERUSER_ID,
            )
            notes_per_template[template.id].append(error_msg)

    @_debug.perf.timed
    def _procure_orderpoint_confirm(
        self,
        use_new_cursor=False,
        company_id=None,
        raise_user_error=True,
        forced_quantities=None,
    ):
        if _debug.lifecycle.enabled:
            _debug.lifecycle(
                "procure_orderpoint_confirm",
                orderpoints=self,
                new_cursor=use_new_cursor,
                company=getattr(company_id, "id", company_id),
                forced=len(forced_quantities or ()),
            )
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

    def _get_quantity_in_progress(self):
        return dict.fromkeys(self._ids, 0.0)

    @api.autovacuum
    def _remove_processed_orderpoints(self):
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
        _debug.lifecycle(
            "processed_orderpoints_removed", orderpoints=orderpoints_to_remove
        )
        orderpoints_to_remove.unlink()
        return orderpoints_to_remove

    def action_stock_replenishment_info(self):
        self.check_singleton()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_stock_replenishment_info",
        )
        action["name"] = self.env._(
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

    def action_product_forecast_report(self):
        self.check_singleton()
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
    def action_view_orderpoints(self):
        return self._prepare_action_orderpoint_replenish()
