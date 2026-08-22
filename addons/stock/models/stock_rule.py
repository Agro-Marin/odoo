import logging
from ast import literal_eval
from collections import defaultdict
from functools import partial

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_is_zero

from .stock_procurement import Procurement, ProcurementException

_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    _name = "stock.rule"
    _description = "Stock Rule"
    _order = "sequence, id"
    _check_company_auto = True

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if "company_id" in fields and not res.get("company_id"):
            res["company_id"] = self.env.company.id
        return res

    Procurement = Procurement
    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
        help="This field will fill the packing origin and the name of its moves",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="If unchecked, it will allow you to hide the rule without removing it.",
    )
    sequence = fields.Integer(string="Sequence", default=20)
    action = fields.Selection(
        selection=[
            ("pull", "Pull From"),
            ("push", "Push To"),
            ("pull_push", "Pull & Push"),
        ],
        string="Action",
        required=True,
        default="pull",
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        domain="[('id', '=?', route_company_id)]",
        index=True,
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination Location",
        required=True,
        check_company=True,
        index=True,
    )
    location_src_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source Location",
        check_company=True,
        index=True,
    )
    location_dest_from_rule = fields.Boolean(
        string="Destination location origin from rule",
        default=False,
        help="When set to True the destination location of the stock.move will be the rule."
        "Otherwise, it takes it from the picking type.",
    )
    route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Route",
        required=True,
        ondelete="cascade",
        index=True,
    )
    route_company_id = fields.Many2one(
        related="route_id.company_id",
        string="Route Company",
    )
    procure_method = fields.Selection(
        selection=[
            ("make_to_stock", "Take From Stock"),
            ("make_to_order", "Trigger Another Rule"),
            ("mts_else_mto", "Take From Stock, if unavailable, Trigger Another Rule"),
        ],
        string="Supply Method",
        required=True,
        default="make_to_stock",
        help="Take From Stock: the products will be taken from the available stock of the source location.\n"
        "Trigger Another Rule: the system will try to find a stock rule to bring the products in the source location. The available stock will be ignored.\n"
        "Take From Stock, if Unavailable, Trigger Another Rule: the products will be taken from the available stock of the source location."
        "If there is no stock available, the system will try to find a  rule to bring the products in the source location.",
    )
    route_sequence = fields.Integer(
        related="route_id.sequence",
        string="Route Sequence",
        compute_sudo=True,
        store=True,
    )
    picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation Type",
        required=True,
        check_company=True,
        domain="[('code', 'in', picking_type_code_domain)] if picking_type_code_domain else []",
    )
    picking_type_code_domain = fields.Json(
        compute="_compute_picking_type_code_domain",
    )
    delay = fields.Integer(
        string="Lead Time",
        default=0,
        help="The expected date of the created transfer will be computed based on this lead time.",
    )
    partner_address_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner Address",
        check_company=True,
        help="Address where goods should be delivered. Optional.",
    )
    propagate_cancel = fields.Boolean(
        string="Cancel Next Move",
        default=False,
        help="When ticked, if the move created by this rule is cancelled, the next move will be cancelled too.",
    )
    propagate_carrier = fields.Boolean(
        string="Propagation of carrier",
        default=False,
        help="When ticked, carrier of shipment will be propagated.",
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        check_company=True,
        index=True,
    )
    auto = fields.Selection(
        selection=[
            ("manual", "Manual Operation"),
            ("transparent", "Automatic No Step Added"),
        ],
        string="Automatic Move",
        required=True,
        default="manual",
        help="The 'Manual Operation' value will create a stock move after the current one. "
        "With 'Automatic No Step Added', the location is replaced in the original move.",
    )
    rule_message = fields.Html(compute="_compute_action_message")
    push_domain = fields.Char(string="Push Applicability")

    @api.constrains("push_domain")
    def _check_push_domain(self):
        Move = self.env["stock.move"]
        for rule in self:
            if not rule.push_domain:
                continue
            try:
                Domain(literal_eval(rule.push_domain)).validate(Move)
            except Exception as error:
                raise ValidationError(
                    _(
                        "The push applicability of rule %(rule)s is not a valid "
                        "domain on stock moves: %(error)s",
                        rule=rule.display_name,
                        error=error,
                    ),
                ) from error

    @api.constrains("company_id")
    def _check_company_consistency(self):
        for rule in self:
            route = rule.route_id
            if route.company_id and rule.company_id != route.company_id:
                raise ValidationError(
                    _(
                        "Rule %(rule)s belongs to %(rule_company)s while the route belongs to %(route_company)s.",
                        rule=rule.display_name,
                        rule_company=rule.company_id.display_name,
                        route_company=route.company_id.display_name,
                    )
                )

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for rule, vals in zip(self, vals_list, strict=True):
                vals["name"] = _("%s (copy)", rule.name)
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    @api.onchange("picking_type_id")
    def _onchange_picking_type(self):
        self.location_src_id = self.picking_type_id.default_location_src_id.id
        self.location_dest_id = self.picking_type_id.default_location_dest_id.id

    @api.onchange("route_id", "company_id")
    def _onchange_route(self):
        if self.route_id.company_id:
            self.company_id = self.route_id.company_id
        if self.picking_type_id.company_id != self.company_id:
            self.picking_type_id = False

    def _get_message_values(self):
        source = (self.location_src_id and self.location_src_id.display_name) or _(
            "Source Location"
        )
        destination = (
            self.location_dest_id and self.location_dest_id.display_name
        ) or _("Destination Location")
        direct_destination = (
            self.picking_type_id
            and self.picking_type_id.default_location_dest_id != self.location_dest_id
            and self.picking_type_id.default_location_dest_id.display_name
        )
        operation = (self.picking_type_id and self.picking_type_id.name) or _(
            "Operation Type"
        )
        return source, destination, direct_destination, operation

    def _get_message_dict(self):
        message_dict = {}
        source, destination, direct_destination, operation = self._get_message_values()
        if self.action in ("push", "pull", "pull_push"):
            suffix = ""
            if (
                self.action in ("pull", "pull_push")
                and direct_destination
                and not self.location_dest_from_rule
            ):
                suffix = _(
                    "<br>The products will be moved towards <b>%(destination)s</b>, <br/> as specified from <b>%(operation)s</b> destination.",
                    destination=direct_destination,
                    operation=operation,
                )
            if self.procure_method == "make_to_order" and self.location_src_id:
                suffix += _(
                    "<br>A need is created in <b>%s</b> and a rule will be triggered to fulfill it.",
                    source,
                )
            if self.procure_method == "mts_else_mto" and self.location_src_id:
                suffix += _(
                    "<br>If the products are not available in <b>%s</b>, a rule will be triggered to bring the missing quantity in this location.",
                    source,
                )
            message_dict = {
                "pull": _(
                    "When products are needed in <b>%(destination)s</b>, <br> <b>%(operation)s</b> are created from <b>%(source_location)s</b> to fulfill the need. %(suffix)s",
                    destination=destination,
                    operation=operation,
                    source_location=source,
                    suffix=suffix,
                ),
                "push": _(
                    "When products arrive in <b>%(source_location)s</b>, <br> <b>%(operation)s</b> are created to send them to <b>%(destination)s</b>.",
                    source_location=source,
                    operation=operation,
                    destination=destination,
                ),
            }
        return message_dict

    @api.depends(
        "action",
        "location_dest_id",
        "location_src_id",
        "picking_type_id",
        "procure_method",
        "location_dest_from_rule",
    )
    def _compute_action_message(self):
        for rule in self:
            message_dict = rule._get_message_dict()
            if rule.action == "pull_push":
                rule.rule_message = (
                    message_dict["pull"] + "<br/><br/>" + message_dict["push"]
                )
            else:
                rule.rule_message = message_dict.get(rule.action) or ""

    @api.depends("action")
    def _compute_picking_type_code_domain(self):
        for rule in self:
            rule.picking_type_code_domain = rule._get_picking_type_code_domain()

    def _get_picking_type_code_domain(self):
        return []

    def _get_push_new_date(self, move):
        return fields.Datetime.to_string(move.date + relativedelta(days=self.delay))

    def _run_push(self, moves):
        self.ensure_one()
        if self.auto == "transparent":
            return {move.id: self._run_push_in_place(move) for move in moves}
        return self._run_push_copy(moves)

    def _run_push_in_place(self, move):
        old_dest_location = move.location_dest_id
        move.write(
            {
                "date": self._get_push_new_date(move),
                "location_dest_id": self.location_dest_id.id,
            },
        )
        if move.move_line_ids:
            move.move_line_ids.location_dest_id = (
                move.location_dest_id._get_putaway_strategy(move.product_id)
                or move.location_dest_id
            )
        if self.location_dest_id != old_dest_location:
            return move._push_apply()[:1]
        return self.env["stock.move"]

    def _run_push_copy(self, moves):
        vals_list = []
        for move in moves:
            vals = move.sudo().copy_data(
                self._push_prepare_move_copy_values(
                    move,
                    self._get_push_new_date(move),
                ),
            )[0]
            if not move.location_dest_id.should_bypass_reservation():
                vals["move_orig_ids"] = [Command.link(move.id)]
            vals_list.append(vals)
        new_moves = self.env["stock.move"].sudo().create(vals_list)
        self._correct_pushed_moves(new_moves)
        return dict(zip(moves.ids, new_moves, strict=True))

    def _correct_pushed_moves(self, new_moves):
        moves_by_final_location = defaultdict(list)
        for move in new_moves.filtered(lambda move: move._skip_push()):
            moves_by_final_location[move.location_final_id.id].append(move.id)
        for location_id, move_ids in moves_by_final_location.items():
            new_moves.browse(move_ids).location_dest_id = location_id
        unreserved = new_moves.filtered(
            lambda move: move._should_bypass_reservation(),
        )
        if unreserved:
            unreserved.procure_method = "make_to_stock"

    def _push_prepare_move_copy_values(self, move_to_copy, new_date):
        company_id = self.company_id.id
        copied_quantity = move_to_copy.quantity
        final_location_id = False
        location_dest_id = self.location_dest_id.id
        if (
            move_to_copy.location_final_id
            and not move_to_copy.location_dest_id._child_of(
                move_to_copy.location_final_id
            )
        ):
            final_location_id = move_to_copy.location_final_id.id
        if move_to_copy.location_final_id and move_to_copy.location_final_id._child_of(
            self.location_dest_id
        ):
            location_dest_id = move_to_copy.location_final_id.id
        if move_to_copy.product_uom_id.compare(move_to_copy.product_uom_qty, 0) < 0:
            copied_quantity = move_to_copy.product_uom_qty
        if not company_id:
            rule_sudo = self.sudo()
            company_id = (
                rule_sudo.warehouse_id.company_id.id
                or rule_sudo.picking_type_id.warehouse_id.company_id.id
            )
        return {
            "product_uom_qty": copied_quantity,
            "origin": move_to_copy.origin or move_to_copy.picking_id.name or "/",
            "location_id": move_to_copy.location_dest_id.id,
            "location_dest_id": location_dest_id,
            "location_final_id": final_location_id,
            "rule_id": self.id,
            "date": new_date,
            "date_deadline": move_to_copy.date_deadline,
            "company_id": company_id,
            "picking_id": False,
            "picking_type_id": self.picking_type_id.id,
            "propagate_cancel": self.propagate_cancel,
            "warehouse_id": self.warehouse_id.id
            or move_to_copy.location_dest_id.warehouse_id.id,
            "procure_method": "make_to_order",
        }

    @api.model
    def _run_pull(self, procurements):
        moves_values_by_company = defaultdict(list)

        source_errors = [
            (
                procurement,
                _(
                    "No source location defined on stock rule: %s!",
                    rule.display_name,
                ),
            )
            for procurement, rule in procurements
            if not rule.location_src_id
        ]
        if source_errors:
            raise ProcurementException(source_errors)

        procurements = sorted(
            procurements,
            key=lambda proc: (
                proc[0].product_uom_id.compare(proc[0].product_qty, 0.0) > 0
            ),
        )
        for procurement, rule in procurements:
            procure_method = rule.procure_method
            if rule.procure_method == "mts_else_mto":
                procure_method = "make_to_stock"

            move_values = rule._get_stock_move_values(procurement)
            move_values["procure_method"] = procure_method
            moves_values_by_company[procurement.company_id.id].append(move_values)
        self._propagate_transit_partner(procurements)

        for company_id, moves_values in moves_values_by_company.items():
            moves = (
                self.env["stock.move"]
                .sudo()
                .with_company(company_id)
                .create(moves_values)
            )
            moves._action_confirm()
        return True

    @api.model
    def _get_action_runners(self):
        return {"pull": "_run_pull"}

    def _get_fields_custom_move(self):
        return []

    def _get_stock_move_values(self, procurement):
        product_uom_id = procurement.product_uom_id
        values = procurement.values
        date_scheduled = fields.Datetime.to_string(
            fields.Datetime.from_string(values["date_planned"])
            - relativedelta(days=self.delay)
        )
        date_deadline = (
            values.get("date_deadline")
            and (
                fields.Datetime.to_datetime(values["date_deadline"])
                - relativedelta(days=self.delay)
            )
        ) or False
        dest_moves = values.get("move_dest_ids") or self.env["stock.move"]
        move_dest_ids = [Command.link(move_id) for move_id in dest_moves.ids]
        partner = self._get_move_partner(procurement, dest_moves)

        if product_uom_id.compare(procurement.product_qty, 0.0) < 0:
            values = dict(values, to_refund=True)

        move_values = {
            "company_id": self.company_id.id
            or self.location_src_id.company_id.id
            or self.location_dest_id.company_id.id
            or procurement.company_id.id,
            "product_id": procurement.product_id.id,
            "product_uom_id": product_uom_id.id,
            "product_uom_qty": procurement.product_qty,
            "partner_id": partner,
            "location_id": self.location_src_id.id,
            "location_final_id": procurement.location_id.id,
            "move_dest_ids": move_dest_ids,
            "rule_id": self.id,
            "reference_ids": [
                Command.set(
                    (values.get("reference_ids") or self.env["stock.reference"]).ids
                ),
            ],
            "procure_method": self.procure_method,
            "origin": procurement.origin,
            "picking_type_id": self.picking_type_id.id,
            "route_ids": [
                Command.set((values.get("route_ids") or self.env["stock.route"]).ids),
            ],
            "never_product_template_attribute_value_ids": values.get(
                "never_product_template_attribute_value_ids"
            ),
            "warehouse_id": self.warehouse_id.id,
            "date": date_scheduled,
            "date_deadline": date_deadline,
            "propagate_cancel": self.propagate_cancel,
            "priority": values.get("priority", "0"),
            "orderpoint_id": values.get("orderpoint_id") and values["orderpoint_id"].id,
        }
        if self.location_dest_from_rule:
            move_values["location_dest_id"] = self.location_dest_id.id
        decided = set(move_values)
        for field in self._get_fields_custom_move():
            if field in values and field not in decided:
                move_values[field] = values.get(field)
        return move_values

    def _get_move_partner(self, procurement, dest_moves):
        partner = self.partner_address_id.id or procurement.values.get(
            "partner_id",
            False,
        )
        if (
            partner
            or not dest_moves
            or procurement.location_id
            != procurement.company_id.internal_transit_location_id
        ):
            return partner
        partners = dest_moves.location_dest_id.warehouse_id.partner_id
        return partners.id if len(partners) == 1 else partner

    @api.model
    def _propagate_transit_partner(self, procurements):
        moves_by_partner = defaultdict(lambda: self.env["stock.move"])
        for procurement, rule in procurements:
            dest_moves = procurement.values.get("move_dest_ids")
            if not dest_moves or (
                procurement.location_id
                != procurement.company_id.internal_transit_location_id
            ):
                continue
            partner = (
                rule.location_src_id.warehouse_id.partner_id
                or rule.company_id.partner_id
            )
            moves_by_partner[partner.id] |= dest_moves
        for partner_id, moves in moves_by_partner.items():
            moves.partner_id = partner_id

    def _get_lead_days(self, product, **values):
        _ = self.env._
        delays = defaultdict(float)
        delay_description = []
        bypass_delay_description = self.env.context.get("bypass_delay_description")
        delaying_rules = self.filtered(
            lambda r: r.action in ["pull", "pull_push"] and r.delay
        )
        if delaying_rules:
            delays["total_delay"] += sum(delaying_rules.mapped("delay"))
            if not bypass_delay_description:
                delay_description = [
                    (_("Delay on %s", rule.name), _("+ %d day(s)", rule.delay))
                    for rule in delaying_rules
                ]
        global_horizon_days = self.env["stock.warehouse.orderpoint"]._get_horizon_days(
            self.company_id[:1],
        )
        if global_horizon_days:
            delays["horizon_time"] += global_horizon_days
            if not bypass_delay_description:
                delay_description.append(
                    (_("Time Horizon"), _("+ %d day(s)", global_horizon_days))
                )
        return delays, delay_description

    @api.model
    def _get_procurement_defaults(self, procurement):
        return {
            "company_id": procurement.location_id.company_id,
            "priority": "0",
            **procurement.values,
            "date_planned": procurement.values.get("date_planned")
            or fields.Datetime.now(),
        }

    @api.model
    def _skip_procurement(self, procurement):
        return procurement.product_id.type != "consu" or float_is_zero(
            procurement.product_qty,
            precision_rounding=procurement.product_uom_id.rounding,
        )

    @api.model
    def run(self, procurements, raise_user_error=True):
        def raise_exception(procurement_errors):
            if raise_user_error:
                _dummy, errors = zip(*procurement_errors, strict=False)
                raise UserError("\n".join(errors))
            raise ProcurementException(procurement_errors)

        actions_to_run = defaultdict(list)
        procurement_errors = []
        valid_procurements = [
            procurement._replace(
                values=self._get_procurement_defaults(procurement),
            )
            for procurement in procurements
            if not self._skip_procurement(procurement)
        ]
        rules = self._get_rules_batch(valid_procurements)
        for procurement, rule in zip(valid_procurements, rules, strict=True):
            if not rule:
                error = _(
                    'No rule has been found to replenish "%(product)s" in "%(location)s".\nVerify the routes configuration on the product.',
                    product=procurement.product_id.display_name,
                    location=procurement.location_id.display_name,
                )
                procurement_errors.append((procurement, error))
            else:
                action = "pull" if rule.action == "pull_push" else rule.action
                actions_to_run[action].append((procurement, rule))

        if procurement_errors:
            raise_exception(procurement_errors)

        runners = self._get_action_runners()
        for action, action_procurements in actions_to_run.items():
            run_action = (
                getattr(self, runners[action], None) if action in runners else None
            )
            if run_action is None:
                _logger.error(
                    "The method _run_%s doesn't exist on the procurement rules", action
                )
                for procurement, rule in action_procurements:
                    procurement_errors.append(
                        (
                            procurement,
                            _(
                                'The rule "%(rule)s" cannot replenish "%(product)s" in'
                                ' "%(location)s": nothing in this database implements'
                                " its “%(action)s” action. Install the module providing"
                                " it, or change the routes on the product.",
                                rule=rule.display_name,
                                product=procurement.product_id.display_name,
                                location=procurement.location_id.display_name,
                                action=action,
                            ),
                        )
                    )
                continue
            try:
                run_action(action_procurements)
            except ProcurementException as e:
                procurement_errors += e.procurement_exceptions

        if procurement_errors:
            raise_exception(procurement_errors)
        return True

    def _get_route_buckets(self, route_ids, packaging_uom_id, product_id, warehouse_id):
        if route_ids:
            yield route_ids
        if packaging_uom_id:
            yield packaging_uom_id.package_type_id.route_ids
        yield product_id.route_ids | product_id.categ_id.total_route_ids
        if warehouse_id:
            yield warehouse_id.route_ids

    @api.model
    def _get_valid_route_ids(
        self, route_ids, packaging_uom_id, product_id, warehouse_ids
    ):
        valid_route_ids = set()
        no_warehouse = self.env["stock.warehouse"]
        for routes in self._get_route_buckets(
            route_ids, packaging_uom_id, product_id, no_warehouse
        ):
            valid_route_ids |= set(routes.ids)
        if warehouse_ids:
            valid_route_ids |= set(
                warehouse_ids.route_ids.filtered(
                    partial(self._is_route_usable_for, product_id),
                ).ids,
            )
        return valid_route_ids

    @api.model
    def _get_rule_candidates(self, values, locations, warehouse_ids, valid_route_ids):
        domain = self._get_rule_location_domain(
            locations,
        ) & self._get_rule_scope_domain(values)
        if warehouse_ids:
            domain &= Domain("warehouse_id", "in", [False, *warehouse_ids.ids])
        if valid_route_ids:
            domain &= Domain("route_id", "in", list(valid_route_ids))
        candidates = defaultdict(lambda: defaultdict(lambda: self.env["stock.rule"]))
        for location, route, rules in self.env["stock.rule"]._read_group(
            domain,
            groupby=["location_dest_id", "route_id"],
            aggregates=["id:recordset"],
        ):
            candidates[location.id][route.id] |= rules
        return candidates

    def _is_route_usable_for(self, product, route):
        return True

    @api.model
    def _sorted_by_precedence(self, rules, warehouse_id):
        return rules.sorted(
            key=lambda rule: (
                bool(warehouse_id) and rule.warehouse_id != warehouse_id,
                rule.route_sequence,
                rule.sequence,
                rule.id,
            ),
        )

    @api.model
    def _sorted_bucket_routes(self, routes, product_id):
        product_route_ids = set(product_id.route_ids.ids)
        return routes.sorted(
            key=lambda route: (
                route.id not in product_route_ids,
                route.sequence,
                route.id,
            ),
        )

    @api.model
    def _get_sorted_buckets(self, product_id, warehouse_id, values):
        return [
            self._sorted_bucket_routes(routes, product_id)
            for routes in self._get_route_buckets(
                values.get("route_ids") or self.env["stock.route"],
                values.get("packaging_uom_id") or self.env["uom.uom"],
                product_id,
                warehouse_id,
            )
        ]

    @api.model
    def _get_best_rule(self, candidates_by_route, sorted_buckets, warehouse_id):
        for routes in sorted_buckets:
            for route in routes:
                candidates = candidates_by_route.get(route.id)
                if not candidates:
                    continue
                if warehouse_id:
                    candidates = candidates.filtered(
                        lambda rule: (
                            not rule.warehouse_id or rule.warehouse_id == warehouse_id
                        ),
                    )
                if candidates:
                    return self._sorted_by_precedence(candidates, warehouse_id)[:1]
        return self.env["stock.rule"]

    def _get_rule_by_domain(
        self, route_ids, packaging_uom_id, product_id, warehouse_id, domain
    ):
        values = {"route_ids": route_ids, "packaging_uom_id": packaging_uom_id}
        domain = Domain(domain)
        if warehouse_id:
            domain &= Domain("warehouse_id", "in", [False, warehouse_id.id])
        valid_route_ids = self._get_valid_route_ids(
            route_ids, packaging_uom_id, product_id, warehouse_id
        )
        if valid_route_ids:
            domain &= Domain("route_id", "in", list(valid_route_ids))
        candidates_by_route = defaultdict(lambda: self.env["stock.rule"])
        for route, rules in self.env["stock.rule"]._read_group(
            domain, groupby=["route_id"], aggregates=["id:recordset"]
        ):
            candidates_by_route[route.id] |= rules
        return self._get_best_rule(
            candidates_by_route,
            self._get_sorted_buckets(product_id, warehouse_id, values),
            warehouse_id,
        )

    @api.model
    def _get_location_hierarchy(self, location_id):
        locations = location_id
        while locations[-1].location_id:
            locations |= locations[-1].location_id
        return locations

    @api.model
    def _get_rule_from_hierarchy(self, candidates, product_id, locations, values):
        intercomp_transit = self._get_intercomp_transit_location()
        intercomp_customers = self.env["stock.location"]
        if self._check_intercomp_location(locations):
            intercomp_customers = self.env.ref(
                "stock.stock_location_customers", raise_if_not_found=False
            )
        buckets_by_warehouse = {}
        for location in locations:
            candidate_locations = location
            if intercomp_customers and location == intercomp_transit:
                candidate_locations = location | intercomp_customers
            for candidate_location in candidate_locations:
                warehouse_id = values.get(
                    "warehouse_id",
                    candidate_location.warehouse_id,
                )
                if warehouse_id.id not in buckets_by_warehouse:
                    buckets_by_warehouse[warehouse_id.id] = self._get_sorted_buckets(
                        product_id, warehouse_id, values
                    )
                rule = self._get_best_rule(
                    candidates.get(candidate_location.id) or {},
                    buckets_by_warehouse[warehouse_id.id],
                    warehouse_id,
                )
                if rule:
                    return rule
        return self.env["stock.rule"]

    @api.model
    def _get_rule(self, product_id, location_id, values):
        Rule = self.env["stock.rule"]
        if not location_id:
            return Rule
        locations = self._get_location_hierarchy(location_id)
        warehouse_ids = values.get("warehouse_id", locations.warehouse_id)
        candidates = self._get_rule_candidates(
            values,
            locations,
            warehouse_ids,
            self._get_valid_route_ids(
                values.get("route_ids", False),
                values.get("packaging_uom_id", False),
                product_id,
                warehouse_ids,
            ),
        )
        return self._get_rule_from_hierarchy(candidates, product_id, locations, values)

    @api.model
    def _get_rules_batch(self, procurements):
        Rule = self.env["stock.rule"]
        rules = [Rule] * len(procurements)
        groups = defaultdict(list)
        for index, procurement in enumerate(procurements):
            if not procurement.location_id:
                continue
            values = procurement.values
            locations = self._get_location_hierarchy(procurement.location_id)
            warehouse_ids = values.get("warehouse_id", locations.warehouse_id)
            valid_route_ids = self._get_valid_route_ids(
                values.get("route_ids", False),
                values.get("packaging_uom_id", False),
                procurement.product_id,
                warehouse_ids,
            )
            key = (
                str(self._get_rule_scope_domain(values)),
                locations[-1].id,
                tuple(warehouse_ids.ids),
                frozenset(valid_route_ids),
            )
            groups[key].append((index, procurement, locations, valid_route_ids))
        for group in groups.values():
            group_locations = self.env["stock.location"].union(
                *(locations for _index, _procurement, locations, _routes in group),
            )
            _index0, representative, _locations0, valid_route_ids = group[0]
            warehouse_ids = representative.values.get(
                "warehouse_id",
                group[0][2].warehouse_id,
            )
            candidates = self._get_rule_candidates(
                representative.values,
                group_locations,
                warehouse_ids,
                valid_route_ids,
            )
            for index, procurement, locations, _routes in group:
                rules[index] = self._get_rule_from_hierarchy(
                    candidates, procurement.product_id, locations, procurement.values
                )
        return rules

    @api.model
    def _get_intercomp_transit_location(self):
        return (
            self.env.ref(
                "stock.stock_location_inter_company",
                raise_if_not_found=False,
            )
            or self.env["stock.location"]
        )

    @api.model
    def _check_intercomp_location(self, locations):
        if not locations.filtered(lambda location: location.usage == "transit"):
            return False
        return self._get_intercomp_transit_location().id in locations.ids

    @api.model
    def _get_rule_domain(self, locations, values):
        return self._get_rule_location_domain(
            locations,
        ) & self._get_rule_scope_domain(values)

    @api.model
    def _get_rule_location_domain(self, locations):
        location_ids = locations.ids
        if self._check_intercomp_location(locations):
            customers_location = self.env.ref(
                "stock.stock_location_customers", raise_if_not_found=False
            )
            if customers_location:
                location_ids.append(customers_location.id)
        return Domain("location_dest_id", "in", location_ids) & Domain(
            "action", "!=", "push"
        )

    @api.model
    def _get_rule_scope_domain(self, values):
        domain = Domain.TRUE
        if self.env.su and values.get("company_id"):
            company_ids = set(values["company_id"].ids)
            if values.get("route_ids"):
                company_ids |= set(values["route_ids"].company_id.ids)
            domain &= Domain(
                [
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "child_of", list(company_ids)),
                ],
            )
        return domain

    @api.model
    def _get_push_rule(self, product_id, location_dest_id, values):
        found_rule = self.env["stock.rule"]
        location = location_dest_id
        while (not found_rule) and location:
            domain = Domain("location_src_id", "=", location.id) & Domain(
                "action", "in", ("push", "pull_push")
            )
            if dom := values.get("domain"):
                domain &= Domain(dom)
            found_rule = self._get_rule_by_domain(
                values.get("route_ids"),
                values.get("packaging_uom_id"),
                product_id,
                values.get("warehouse_id"),
                domain,
            )
            location = location.location_id
        return found_rule
