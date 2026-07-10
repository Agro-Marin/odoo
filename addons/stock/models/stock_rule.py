from collections import defaultdict, OrderedDict
import datetime
from functools import partial
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_is_zero
from itertools import batched

from .stock_procurement import Procurement, ProcurementException

_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    """A rule describes what a procurement should do: produce, buy, move, ..."""

    _name = "stock.rule"
    _description = "Stock Rule"
    _order = "sequence, id"
    _check_company_auto = True

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Force a company even when the caller explicitly clears it through the
        # `default_company_id=False` context: a rule created from the UI should
        # default to the current company rather than to a company-less rule.
        if "company_id" in fields_list and not res.get("company_id"):
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

    @api.constrains("company_id")
    def _check_company_consistency(self):
        for rule in self:
            route = rule.route_id
            if route.company_id and rule.company_id.id != route.company_id.id:
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
            for rule, vals in zip(self, vals_list):
                vals["name"] = _("%s (copy)", rule.name)
        return vals_list

    @api.onchange("picking_type_id")
    def _onchange_picking_type(self):
        """Default the source/destination locations from the picking type."""
        self.location_src_id = self.picking_type_id.default_location_src_id.id
        self.location_dest_id = self.picking_type_id.default_location_dest_id.id

    @api.onchange("route_id", "company_id")
    def _onchange_route(self):
        """Ensure that the rule's company is the same as the route's company."""
        if self.route_id.company_id:
            self.company_id = self.route_id.company_id
        if self.picking_type_id.warehouse_id.company_id != self.route_id.company_id:
            self.picking_type_id = False

    def _get_message_values(self):
        """Return the source, destination and picking_type applied on a stock
        rule. The purpose of this function is to avoid code duplication in
        _get_message_dict functions since it often requires those data.
        """
        source = (
            self.location_src_id
            and self.location_src_id.display_name
            or _("Source Location")
        )
        destination = (
            self.location_dest_id
            and self.location_dest_id.display_name
            or _("Destination Location")
        )
        direct_destination = (
            self.picking_type_id
            and self.picking_type_id.default_location_dest_id != self.location_dest_id
            and self.picking_type_id.default_location_dest_id.display_name
        )
        operation = (
            self.picking_type_id and self.picking_type_id.name or _("Operation Type")
        )
        return source, destination, direct_destination, operation

    def _get_message_dict(self):
        """Return a dict with the different possible message used for the
        rule message. It has one entry per stock.rule action, except
        'pull_push' which is built by combining the 'pull' and 'push'
        messages in `_compute_action_message`. This function is overridden
        in mrp and purchase_stock in order to complete the dictionary.
        """
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
        """Generate a message describing the rule's purpose for the end user."""
        action_rules = self.filtered(lambda rule: rule.action)
        for rule in action_rules:
            message_dict = rule._get_message_dict()
            message = message_dict.get(rule.action) or ""
            if rule.action == "pull_push":
                message = message_dict["pull"] + "<br/><br/>" + message_dict["push"]
            rule.rule_message = message
        (self - action_rules).rule_message = None

    @api.depends("action")
    def _compute_picking_type_code_domain(self):
        self.picking_type_code_domain = []

    def _get_push_new_date(self, move):
        """Return the move's date shifted by the rule's lead time."""
        return fields.Datetime.to_string(move.date + relativedelta(days=self.delay))

    def _run_push(self, move):
        """Apply a push rule on a move.

        If the rule is 'no step added' the move's destination location is
        modified in place. If the rule is 'manual operation' a new move is
        generated to cover the leg defined by the rule.

        Not called from `run`: called directly by `stock_move._push_apply`.

        :return: the move that continues the push chain, as a ``stock.move``
            recordset (empty when the push adds no step).
        """
        self.ensure_one()
        new_date = self._get_push_new_date(move)
        if self.auto == "transparent":
            old_dest_location = move.location_dest_id
            move.write({"date": new_date, "location_dest_id": self.location_dest_id.id})
            # make sure the location_dest_id is consistent with the move line location dest
            if move.move_line_ids:
                move.move_line_ids.location_dest_id = (
                    move.location_dest_id._get_putaway_strategy(move.product_id)
                    or move.location_dest_id
                )

            # avoid looping if a push rule is not well configured; otherwise call again push_apply to see if a next step is defined
            if self.location_dest_id != old_dest_location:
                # TDE FIXME: should probably be done in the move model IMO
                return move._push_apply()[:1]
            return self.env["stock.move"]

        new_move_vals = self._push_prepare_move_copy_values(move, new_date)
        new_move = move.sudo().copy(new_move_vals)
        # when no more push we should reach final destination
        if new_move._skip_push():
            new_move.write({"location_dest_id": new_move.location_final_id.id})
        if new_move._should_bypass_reservation():
            new_move.write({"procure_method": "make_to_stock"})
        if not new_move.location_id.should_bypass_reservation():
            move.sudo().write({"move_dest_ids": [Command.link(new_move.id)]})
        return new_move

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
        if move_to_copy.product_uom.compare(move_to_copy.product_uom_qty, 0) < 0:
            copied_quantity = move_to_copy.product_uom_qty
        if not company_id:
            rule_sudo = self.sudo()
            company_id = (
                rule_sudo.warehouse_id.company_id.id
                or rule_sudo.picking_type_id.warehouse_id.company_id.id
            )
        new_move_vals = {
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
        return new_move_vals

    @api.model
    def _run_pull(self, procurements):
        moves_values_by_company = defaultdict(list)

        # Sanity check: every rule must define a source location.
        for procurement, rule in procurements:
            if not rule.location_src_id:
                msg = _("No source location defined on stock rule: %s!", rule.name)
                raise ProcurementException([(procurement, msg)])

        # Prepare the move values, adapt the `procure_method` if needed.
        # Process non-positive quantities (e.g. returns) before positive ones so
        # that, within a company batch, refund moves are created first. The sort
        # key is a bool: `compare(...) > 0` is False for qty <= 0 (sorted first)
        # and True for qty > 0 (sorted last); Python's stable sort keeps the
        # original order within each group.
        procurements = sorted(
            procurements,
            key=lambda proc: proc[0].product_uom.compare(proc[0].product_qty, 0.0) > 0,
        )
        for procurement, rule in procurements:
            procure_method = rule.procure_method
            if rule.procure_method == "mts_else_mto":
                procure_method = "make_to_stock"

            move_values = rule._get_stock_move_values(*procurement)
            move_values["procure_method"] = procure_method
            rule._propagate_transit_partner(procurement)
            moves_values_by_company[procurement.company_id.id].append(move_values)

        for company_id, moves_values in moves_values_by_company.items():
            # create the move as SUPERUSER because the current user may not have the rights to do it (mto product launched by a sale for example)
            moves = (
                self.env["stock.move"]
                .sudo()
                .with_company(company_id)
                .create(moves_values)
            )
            # create() doesn't auto-confirm; _action_confirm() is what triggers
            # the next rule in the chain for make_to_order/mts_else_mto moves.
            moves._action_confirm()
        return True

    def _get_custom_move_fields(self):
        """Override to add fields from the procurement `values` to the move values."""
        return []

    def _get_stock_move_values(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
    ):
        """Return the values used to create a stock move from a procurement.

        Assumes the procurement's rule has action 'pull' or 'pull_push'.

        `location_dest_id` is the procurement's need location (i.e. the
        `Procurement.location_id` positional field); it becomes the move's
        `location_final_id`, while the move's own `location_dest_id` comes from
        the rule/picking type.
        """
        date_scheduled = fields.Datetime.to_string(
            fields.Datetime.from_string(values["date_planned"])
            - relativedelta(days=self.delay or 0)
        )
        date_deadline = (
            values.get("date_deadline")
            and (
                fields.Datetime.to_datetime(values["date_deadline"])
                - relativedelta(days=self.delay or 0)
            )
            or False
        )
        partner = self.partner_address_id.id or values.get("partner_id", False)

        # `or` (not a default arg): callers may pass move_dest_ids=False explicitly.
        dest_moves = values.get("move_dest_ids") or self.env["stock.move"]
        move_dest_ids = [Command.link(move.id) for move in dest_moves]

        # For inter-warehouse transfers, default the new move's partner to the
        # destination warehouse's partner. Tagging the *destination* moves with
        # the source warehouse's partner is a write on existing records, so it
        # is done in `_propagate_transit_partner` rather than in this getter.
        if (
            move_dest_ids
            and not partner
            and location_dest_id == company_id.internal_transit_location_id
        ):
            partners = dest_moves.location_dest_id.warehouse_id.partner_id
            if len(partners) == 1:
                partner = partners.id

        if product_uom.compare(product_qty, 0.0) < 0:
            values["to_refund"] = True

        move_values = {
            "company_id": self.company_id.id
            or self.location_src_id.company_id.id
            or self.location_dest_id.company_id.id
            or company_id.id,
            "product_id": product_id.id,
            "product_uom": product_uom.id,
            "product_uom_qty": product_qty,
            "partner_id": partner,
            "location_id": self.location_src_id.id,
            "location_final_id": location_dest_id.id,
            "move_dest_ids": move_dest_ids,
            "rule_id": self.id,
            # `values` entries may be recordsets or plain lists of records
            # (procurement callers across modules use both), so iterate
            # instead of assuming a recordset.
            "reference_ids": [
                Command.set(
                    [reference.id for reference in values.get("reference_ids") or []],
                ),
            ],
            "procure_method": self.procure_method,
            "origin": origin,
            "picking_type_id": self.picking_type_id.id,
            "procurement_values": self._serialize_procurement_values(values),
            "route_ids": [
                Command.set([route.id for route in values.get("route_ids") or []]),
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
        for field in self._get_custom_move_fields():
            if field in values:
                move_values[field] = values.get(field)
        return move_values

    def _propagate_transit_partner(self, procurement):
        """Tag the procurement's destination moves with the source warehouse's
        partner when creating chained moves for an inter-warehouse transfer, so
        the transit document shows the right counterparty.

        Kept out of `_get_stock_move_values`, which prepares values and must not
        write to records.
        """
        self.ensure_one()
        move_dest = procurement.values.get("move_dest_ids")
        if not move_dest:
            return
        if (
            procurement.location_id
            == procurement.company_id.internal_transit_location_id
        ):
            move_dest.partner_id = (
                self.location_src_id.warehouse_id.partner_id
                or self.company_id.partner_id
            )

    def _serialize_procurement_values(self, values):
        """Serialize procurement values for storage on the move:
        - BaseModel instances are converted to their IDs
        - Datetime and Date values are converted to their ISO string
        - Other values are kept as is
        """
        serialized = {}
        for key, value in values.items():
            if isinstance(value, models.BaseModel):
                serialized[key] = value.ids
            elif isinstance(value, (datetime.datetime, datetime.date)):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized

    def _get_lead_days(self, product, **values):
        """Returns the cumulative delay and its description encountered by a
        procurement going through the rules in `self`.

        :param product: the product of the procurement
        :type product: :class:`~odoo.addons.product.models.product.ProductProduct`
        :return: the cumulative delay and cumulative delay's description
        :rtype: tuple[defaultdict(float), list[str, str]]
        """
        # FIXME : ensure one product or make the method work with multiple products
        _ = self.env._
        delays = defaultdict(float)
        delay_description = []
        bypass_delay_description = self.env.context.get("bypass_delay_description")
        # Check if the rules have lead time
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
        # Check if there's a horizon set
        bypass_global_horizon_days = self.env.context.get("bypass_global_horizon_days")
        if bypass_global_horizon_days:
            return delays, delay_description
        global_horizon_days = self.env["stock.warehouse.orderpoint"].get_horizon_days()
        if global_horizon_days:
            delays["horizon_time"] += global_horizon_days
            if not bypass_delay_description:
                delay_description.append(
                    (_("Time Horizon"), _("+ %d day(s)", global_horizon_days))
                )
        return delays, delay_description

    @api.model
    def _skip_procurement(self, procurement):
        return procurement.product_id.type != "consu" or float_is_zero(
            procurement.product_qty, precision_rounding=procurement.product_uom.rounding
        )

    @api.model
    def run(self, procurements, raise_user_error=True):
        """Fulfil `procurements` with the help of stock rules.

        Procurements are needs of products at a certain location. To fulfil
        these needs, we need to create some sort of documents (`stock.move`
        by default, but extensions of `_run_` methods allow to create every
        type of documents).

        :param procurements: the description of the procurement
        :type procurements: list of `~odoo.addons.stock.models.stock_procurement.Procurement`
        :param raise_user_error: will raise either an UserError or a ProcurementException
        :type raise_user_error: bool, optional
        :raises UserError: if `raise_user_error` is True and a procurement isn't fulfillable
        :raises ProcurementException: if `raise_user_error` is False and a procurement isn't fulfillable
        """

        def raise_exception(procurement_errors):
            if raise_user_error:
                dummy, errors = zip(*procurement_errors)
                raise UserError("\n".join(errors))
            else:
                raise ProcurementException(procurement_errors)

        actions_to_run = defaultdict(list)
        procurement_errors = []
        for procurement in procurements:
            procurement.values.setdefault(
                "company_id", procurement.location_id.company_id
            )
            procurement.values.setdefault("priority", "0")
            # A plain `setdefault` is not enough: a caller may pass an explicit
            # falsy `date_planned`, which would otherwise reach
            # `_get_stock_move_values` and raise on `None - relativedelta(...)`.
            procurement.values["date_planned"] = (
                procurement.values.get("date_planned") or fields.Datetime.now()
            )
            if self._skip_procurement(procurement):
                continue
            rule = self._get_rule(
                procurement.product_id, procurement.location_id, procurement.values
            )
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

        for action, action_procurements in actions_to_run.items():
            # Dynamic dispatch: `_run_pull`/`_run_push` here, `_run_buy`/`_run_manufacture`
            # contributed by purchase/mrp. `None` default keeps a misconfigured action
            # from raising an AttributeError instead of a readable log line.
            run_action = getattr(self.env["stock.rule"], f"_run_{action}", None)
            if run_action is None:
                _logger.error(
                    "The method _run_%s doesn't exist on the procurement rules", action
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
        """Yield candidate route recordsets in resolution-priority order:
        explicit routes, then the packaging's routes, then the product/category
        routes, then the warehouse's routes.

        This is the single definition of route precedence, shared by the
        sequential resolver (`_search_rule`), the batched resolver
        (`_search_rule_for_warehouses`) and the in-memory resolver
        (`_get_rule`), so the four-tier fallback lives in exactly one place.
        Empty buckets may be yielded; callers skip them.
        """
        if route_ids:
            yield route_ids
        if packaging_uom_id:
            yield packaging_uom_id.package_type_id.route_ids
        yield product_id.route_ids | product_id.categ_id.total_route_ids
        if warehouse_id:
            yield warehouse_id.route_ids

    @api.model
    def _search_rule_for_warehouses(
        self, route_ids, packaging_uom_id, product_id, warehouse_ids, domain
    ):
        domain = Domain(domain)
        if warehouse_ids:
            domain &= Domain("warehouse_id", "in", [False, *warehouse_ids.ids])
        valid_route_ids = set()
        no_warehouse = self.env["stock.warehouse"]
        for routes in self._get_route_buckets(
            route_ids, packaging_uom_id, product_id, no_warehouse
        ):
            valid_route_ids |= set(routes.ids)
        # The warehouse bucket differs here: it spans several warehouses and is
        # filtered per product, so it is handled outside `_get_route_buckets`.
        if warehouse_ids:
            filter_function = partial(
                self._filter_warehouse_routes, product_id, warehouse_ids
            )
            valid_route_ids |= set(
                warehouse_ids.route_ids.filtered(filter_function).ids
            )
        if valid_route_ids:
            domain &= Domain("route_id", "in", list(valid_route_ids))
        res = self.env["stock.rule"]._read_group(
            domain,
            groupby=["location_dest_id", "warehouse_id", "route_id"],
            aggregates=["id:recordset"],
            order="route_sequence:min, sequence:min",
        )
        rule_dict = defaultdict(OrderedDict)
        for group in res:
            rule_dict[group[0].id, group[2].id][group[1].id] = min(
                group[3], key=lambda rule: (rule.route_sequence, rule.sequence)
            )
        return rule_dict

    def _filter_warehouse_routes(self, product, warehouses, route):
        return route

    def _search_rule(
        self, route_ids, packaging_uom_id, product_id, warehouse_id, domain
    ):
        """First find a rule among the routes given in `route_ids`, then try
        the packaging's routes, then the product's routes, finally fallback
        on the warehouse's routes.
        """
        Rule = self.env["stock.rule"]
        domain = Domain(domain)
        if warehouse_id:
            domain &= Domain("warehouse_id", "in", [False, warehouse_id.id])
        domain = domain.optimize(Rule)
        for routes in self._get_route_buckets(
            route_ids, packaging_uom_id, product_id, warehouse_id
        ):
            if not routes:
                continue
            res = Rule.search(
                Domain("route_id", "in", routes.ids) & domain,
                order="route_sequence, sequence",
                limit=1,
            )
            if res:
                return res
        return Rule

    def _extract_rule_from_dict(
        self, rule_dict, routes, warehouse_id, location_dest_id, product_id
    ):
        """Pick a rule delivering to `location_dest_id` among `routes` from the
        prefetched `rule_dict` (built by `_search_rule_for_warehouses`).

        Routes are tried product-routes-first, then by ascending route/rule
        sequence. Returns an empty recordset when none matches.
        """
        for route in routes.sorted(
            key=lambda r: (r not in product_id.route_ids, r.sequence)
        ):
            sub_dict = rule_dict.get((location_dest_id.id, route.id))
            if not sub_dict:
                continue
            if not warehouse_id:
                return sub_dict[next(iter(sub_dict))]
            # `.get(False)` rather than `[False]`: when the location chain spans
            # several warehouses a group may hold only a foreign-warehouse rule
            # and no warehouse-agnostic one. Falling through to the next route /
            # parent location is correct; indexing would raise KeyError.
            rule = sub_dict.get(warehouse_id.id) or sub_dict.get(False)
            if rule:
                return rule
        return self.env["stock.rule"]

    def _get_rule_from_dict(self, rule_dict, product_id, location_dest_id, values):
        """Return the best pull rule for `location_dest_id` from the prefetched
        `rule_dict`, trying each route bucket in priority order.
        """
        warehouse_id = values.get("warehouse_id", location_dest_id.warehouse_id)
        buckets = self._get_route_buckets(
            values.get("route_ids", self.env["stock.route"]),
            values.get("packaging_uom_id", self.env["uom.uom"]),
            product_id,
            warehouse_id,
        )
        for routes in buckets:
            rule = self._extract_rule_from_dict(
                rule_dict, routes, warehouse_id, location_dest_id, product_id
            )
            if rule:
                return rule
        return self.env["stock.rule"]

    @api.model
    def _get_rule(self, product_id, location_id, values):
        """Find a pull rule for the location_id, fallback on the parent
        locations if it could not be found.
        """
        Rule = self.env["stock.rule"]
        if not location_id:
            return Rule
        # Build the leaf -> root location hierarchy once; it is reused below for
        # the search domain, the warehouse set and the fallback walk.
        locations = location_id
        while locations[-1].location_id:
            locations |= locations[-1].location_id
        # Resolve the intercompany locations once, instead of re-running
        # `_check_intercomp_location` / `env.ref` for every location in the walk.
        # When the inter-company transit location is in scope, `_get_rule_domain`
        # also searched rules delivering to the shared Customers location, so that
        # location must be tried alongside the inter-company one during the walk.
        intercomp_transit = self.env.ref(
            "stock.stock_location_inter_company", raise_if_not_found=False
        )
        intercomp_customers = self.env["stock.location"]
        if self._check_intercomp_location(locations):
            intercomp_customers = self.env.ref(
                "stock.stock_location_customers", raise_if_not_found=False
            )
        domain = self._get_rule_domain(locations, values)
        # Mapping (location_id, route_id) -> {warehouse_id: rule}
        rule_dict = self._search_rule_for_warehouses(
            values.get("route_ids", False),
            values.get("packaging_uom_id", False),
            product_id,
            values.get("warehouse_id", locations.warehouse_id),
            domain,
        )
        # Walk the hierarchy leaf -> root, returning the first matching rule.
        for location in locations:
            candidate_locations = location
            if intercomp_customers and location == intercomp_transit:
                candidate_locations = location | intercomp_customers
            for candidate_location in candidate_locations:
                rule = self._get_rule_from_dict(
                    rule_dict, product_id, candidate_location, values
                )
                if rule:
                    return rule
        return Rule

    @api.model
    def _check_intercomp_location(self, locations):
        if locations.filtered(lambda location: location.usage == "transit"):
            inter_comp_location = self.env.ref(
                "stock.stock_location_inter_company", raise_if_not_found=False
            )
            return inter_comp_location and inter_comp_location.id in locations.ids

    @api.model
    def _get_rule_domain(self, locations, values):
        location_ids = locations.ids
        # If the method is called to find rules towards the Inter-company location, also add the 'Customer' location in the domain.
        # This is to avoid having to duplicate every rules that deliver to Customer to have the Inter-company part.
        if self._check_intercomp_location(locations):
            location_ids.append(
                self.env.ref(
                    "stock.stock_location_customers", raise_if_not_found=False
                ).id
            )
        domain = Domain("location_dest_id", "in", location_ids) & Domain(
            "action", "!=", "push"
        )
        # In case the method is called by the superuser, we need to restrict the rules to the
        # ones of the company. This is not useful as a regular user since there is a record
        # rule to filter out the rules based on the company.
        if self.env.su and values.get("company_id"):
            company_ids = set(values.get("company_id").ids)
            if values.get("route_ids"):
                company_ids |= set(values["route_ids"].company_id.ids)
            domain_company = [
                "|",
                ("company_id", "=", False),
                ("company_id", "child_of", list(company_ids)),
            ]
            domain &= Domain(domain_company)
        return domain

    @api.model
    def _get_push_rule(self, product_id, location_dest_id, values):
        """Find a push rule for the location_dest_id, with a fallback to the parent locations if none could be found."""
        found_rule = self.env["stock.rule"]
        location = location_dest_id
        while (not found_rule) and location:
            domain = Domain("location_src_id", "=", location.id) & Domain(
                "action", "in", ("push", "pull_push")
            )
            if dom := values.get("domain"):
                domain &= Domain(dom)
            found_rule = self._search_rule(
                values.get("route_ids"),
                values.get("packaging_uom_id"),
                product_id,
                values.get("warehouse_id"),
                domain,
            )
            location = location.location_id
        return found_rule

    @api.model
    def _get_moves_to_assign_domain(self, company_id):
        return Domain(
            [
                ("company_id", "=?", company_id),
                ("state", "in", ["confirmed", "partially_available"]),
                ("product_uom_qty", "!=", 0.0),
                "|",
                ("date_reservation", "<=", fields.Date.today()),
                ("picking_type_id.reservation_method", "=", "at_confirm"),
            ]
        )

    @api.model
    def _run_scheduler_tasks(self, use_new_cursor=False, company_id=False):
        if use_new_cursor:
            self.env["ir.cron"]._commit_progress(
                remaining=self._get_scheduler_tasks_to_do()
            )

        # Minimum stock rules
        domain = self._get_orderpoint_domain(company_id=company_id)
        orderpoints = self.env["stock.warehouse.orderpoint"].search(domain)
        orderpoints.sudo()._compute_qty_to_order_computed()
        orderpoints.sudo()._compute_deadline_date()
        # Refresh stored lead-time analytics from freshly completed receipts; they cannot
        # ORM-depend on the pickings they aggregate, so the scheduler owns their refresh.
        orderpoints.sudo()._compute_lead_time_stats()
        orderpoints.sudo()._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor, company_id=company_id, raise_user_error=False
        )

        if use_new_cursor:
            self.env["ir.cron"]._commit_progress(1)

        # Search all confirmed stock_moves and try to assign them
        domain = self._get_moves_to_assign_domain(company_id)
        moves_to_assign = self.env["stock.move"].search(
            domain,
            limit=None,
            order="date_reservation, priority desc, date asc, id asc",
        )
        for moves_chunk in batched(moves_to_assign.ids, 1000):
            self.env["stock.move"].browse(moves_chunk).sudo()._action_assign()
            if use_new_cursor:
                self.env.cr.commit()
                _logger.info(
                    "A batch of %d moves are assigned and committed", len(moves_chunk)
                )

        if use_new_cursor:
            self.env["ir.cron"]._commit_progress(1)

        # Merge duplicated quants
        self.env["stock.quant"]._quant_tasks()

        if use_new_cursor:
            self.env["ir.cron"]._commit_progress(1)

    @api.model
    def _get_scheduler_tasks_to_do(self):
        """Number of task to be executed by the stock scheduler. This number will be given in log
        message to know how many tasks succeeded."""
        return 3

    @api.model
    def run_scheduler(self, use_new_cursor=False, company_id=False):
        """Call the scheduler in order to check the running procurements (super method), to check the minimum stock rules
        and the availability of moves. This function is intended to be run for all the companies at the same time, so
        we run functions as SUPERUSER to avoid intercompanies and access rights issues.
        """
        try:
            self._run_scheduler_tasks(
                use_new_cursor=use_new_cursor, company_id=company_id
            )
        except Exception:
            _logger.error("Error during stock scheduler", exc_info=True)
            raise
        return {}

    @api.model
    def _get_orderpoint_domain(self, company_id=False):
        domain = [("trigger", "=", "auto"), ("product_id.active", "=", True)]
        if company_id:
            domain += [("company_id", "=", company_id)]
        return domain
