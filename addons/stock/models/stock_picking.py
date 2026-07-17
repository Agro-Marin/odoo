import json
import math
from ast import literal_eval
from collections import defaultdict
from datetime import date, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.tools import OrderedSet, format_date, format_datetime, groupby
from odoo.tools.misc import clean_context
from odoo.tools.translate import _

from odoo.addons.stock.models.stock_move import PROCUREMENT_PRIORITIES
from odoo.addons.web.controllers.utils import clean_action

# Terminal states for pickings and moves: a done/cancelled record no longer takes
# part in confirmation, reservation, backorders, packing, etc. Membership tests only
# (domains keep explicit tuples).
DONE_CANCEL_STATES = frozenset(("done", "cancel"))


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Transfer"
    _order = "priority desc, date_planned asc, id desc"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    name = fields.Char(
        string="Reference",
        default="/",
        readonly=True,
        copy=False,
        index="trigram",
    )
    origin = fields.Char(
        string="Source Document",
        index="trigram",
        help="Reference of the document",
    )
    note = fields.Html(string="Notes")
    backorder_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Back Order of",
        readonly=True,
        check_company=True,
        copy=False,
        index="btree_not_null",
        help="If this shipment was split, then this field links to the shipment which contains the already processed part.",
    )
    backorder_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="backorder_id",
        string="Back Orders",
    )
    return_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Return of",
        readonly=True,
        check_company=True,
        copy=False,
        index="btree_not_null",
        help="If this picking was created as a return of another picking, this field links to the original picking.",
    )
    return_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="return_id",
        string="Returns",
    )
    return_count = fields.Integer(
        string="# Returns",
        compute="_compute_return_count",
        compute_sudo=False,
    )

    move_type = fields.Selection(
        selection=[
            ("direct", "As soon as possible"),
            ("one", "When all products are ready"),
        ],
        string="Shipping Policy",
        required=True,
        compute="_compute_move_type",
        store=True,
        precompute=True,
        readonly=False,
        help="It specifies goods to be deliver partially or all at once",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("waiting", "Waiting Another Operation"),
            ("confirmed", "Waiting"),
            ("assigned", "Ready"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        compute="_compute_state",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        help=" * Draft: The transfer is not confirmed yet. Reservation doesn't apply.\n"
        " * Waiting another operation: This transfer is waiting for another operation before being ready.\n"
        ' * Waiting: The transfer is waiting for the availability of some products.\n(a) The shipping policy is "As soon as possible": no product could be reserved.\n(b) The shipping policy is "When all products are ready": not all the products could be reserved.\n'
        ' * Ready: The transfer is ready to be processed.\n(a) The shipping policy is "As soon as possible": at least one product has been reserved.\n(b) The shipping policy is "When all products are ready": all product have been reserved.\n'
        " * Done: The transfer has been processed.\n"
        " * Cancelled: The transfer has been cancelled.",
    )
    reference_ids = fields.Many2many(
        related="move_ids.reference_ids",
        comodel_name="stock.reference",
        string="References",
        readonly=True,
    )
    priority = fields.Selection(
        selection=PROCUREMENT_PRIORITIES,
        string="Priority",
        default="0",
        help="Products will be reserved first for the transfers with the highest priorities.",
    )
    date_planned = fields.Datetime(
        string="Scheduled Date",
        default=fields.Datetime.now,
        compute="_compute_date_planned",
        store=True,
        inverse="_inverse_date_planned",
        index=True,
        tracking=True,
        help="Scheduled time for the first part of the shipment to be processed. Setting manually a value here would set it as expected date for all the stock moves.",
    )
    date_deadline = fields.Datetime(
        string="Deadline",
        compute="_compute_date_deadline",
        store=True,
        help="In case of outgoing flow, validate the transfer before this date to allow to deliver at promised date to the customer.\n\
        In case of incoming flow, validate the transfer before this date in order to have these products in stock at the date promised by the supplier",
    )
    has_deadline_issue = fields.Boolean(
        string="Is late",
        default=False,
        compute="_compute_has_deadline_issue",
        store=True,
        help="Is late or will be late depending on the deadline and scheduled date",
    )
    date_done = fields.Datetime(
        string="Date of Transfer",
        copy=False,
        help="Date at which the transfer has been processed or cancelled.",
    )
    date_delay_alert = fields.Datetime(
        string="Delay Alert Date",
        compute="_compute_date_delay_alert",
        search="_search_date_delay_alert",
    )
    json_popover = fields.Char(
        string="JSON data for the popover widget",
        compute="_compute_json_popover",
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source Location",
        required=True,
        compute="_compute_location_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination Location",
        required=True,
        compute="_compute_location_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
    )
    move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="picking_id",
        string="Stock Moves",
        copy=True,
    )
    has_scrap_move = fields.Boolean(
        string="Has Scrap Moves",
        compute="_compute_has_scrap_move",
    )
    picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation Type",
        required=True,
        default=lambda self: self._default_picking_type_id(),
        index=True,
        tracking=True,
    )
    warehouse_address_id = fields.Many2one(
        related="picking_type_id.warehouse_id.partner_id",
        comodel_name="res.partner",
    )
    picking_type_code = fields.Selection(
        related="picking_type_id.code",
        readonly=True,
    )
    picking_type_entire_packs = fields.Boolean(
        related="picking_type_id.show_entire_packs",
    )
    use_create_lots = fields.Boolean(
        related="picking_type_id.use_create_lots",
    )
    use_existing_lots = fields.Boolean(
        related="picking_type_id.use_existing_lots",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contact",
        check_company=True,
        index="btree_not_null",
    )
    company_id = fields.Many2one(
        related="picking_type_id.company_id",
        comodel_name="res.company",
        string="Company",
        store=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("stock.group_stock_user").id),
        ],
        copy=False,
        tracking=True,
    )
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="picking_id",
        string="Operations",
    )
    count_packages = fields.Integer(
        string="Packages Count",
        compute="_compute_count_packages",
    )
    package_history_ids = fields.Many2many(
        comodel_name="stock.package.history",
        string="Transferred Packages",
        copy=False,
    )
    show_check_availability = fields.Boolean(
        compute="_compute_show_check_availability",
        help='Technical field used to compute whether the button "Check Availability" should be displayed.',
    )
    show_allocation = fields.Boolean(
        compute="_compute_show_allocation",
        help='Technical Field used to decide whether the button "Allocation" should be displayed.',
    )
    owner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Assign Owner",
        check_company=True,
        index="btree_not_null",
        help="When validating the transfer, the products will be assigned to this owner.",
    )
    printed = fields.Boolean(string="Printed", copy=False)
    signature = fields.Image(
        string="Signature",
        attachment=True,
        copy=False,
        help="Signature",
    )
    is_signed = fields.Boolean(
        string="Is Signed",
        compute="_compute_is_signed",
    )
    is_locked = fields.Boolean(
        default=True,
        copy=False,
        help="When the picking is not done this allows changing the "
        "initial demand. When the picking is done this allows "
        "changing the done quantities.",
    )
    is_date_editable = fields.Boolean(
        "Is Scheduled Date Editable",
        compute="_compute_is_date_editable",
    )

    weight_bulk = fields.Float(
        string="Bulk Weight",
        compute="_compute_bulk_weight",
        help="Total weight of products which are not in a package.",
    )
    shipping_weight = fields.Float(
        string="Weight for Shipping",
        digits="Stock Weight",
        compute="_compute_shipping_weight",
        store=True,
        readonly=False,
        help="Total weight of packages and products not in a package. "
        "Packages with no shipping weight specified will default to their products' total weight. "
        "This is the weight used to compute the cost of the shipping.",
    )
    shipping_volume = fields.Float(
        string="Volume for Shipping",
        compute="_compute_shipping_volume",
    )

    # Used to search on pickings
    product_id = fields.Many2one(
        related="move_ids.product_id",
        comodel_name="product.product",
        string="Product",
        readonly=True,
    )
    lot_id = fields.Many2one(
        related="move_line_ids.lot_id",
        comodel_name="stock.lot",
        string="Lot/Serial Number",
        readonly=True,
    )
    show_lots_text = fields.Boolean(compute="_compute_show_lots_text")
    has_tracking = fields.Boolean(compute="_compute_has_tracking")
    products_availability = fields.Char(
        string="Product Availability",
        compute="_compute_products_availability",
        help="Latest product availability status of the picking",
    )
    products_availability_state = fields.Selection(
        selection=[
            ("available", "Available"),
            ("expected", "Expected"),
            ("late", "Late"),
        ],
        compute="_compute_products_availability",
        search="_search_products_availability_state",
    )

    picking_properties = fields.Properties(
        string="Properties",
        definition="picking_type_id.picking_properties_definition",
        copy=True,
    )
    show_next_pickings = fields.Boolean(
        compute="_compute_show_next_pickings",
    )
    search_date_category = fields.Selection(
        selection=[
            ("before", "Before"),
            ("yesterday", "Yesterday"),
            ("today", "Today"),
            ("day_1", "Tomorrow"),
            ("day_2", "The day after tomorrow"),
            ("after", "After"),
        ],
        string="Date Category",
        store=False,
        readonly=True,
        search="_search_date_category",
    )
    partner_country_id = fields.Many2one(
        related="partner_id.country_id",
        comodel_name="res.country",
    )
    picking_warning_text = fields.Text(
        string="Picking Instructions",
        compute="_compute_picking_warning_text",
        help="Internal instructions for the partner or its parent company as set by the user.",
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    _name_uniq = models.Constraint(
        "unique(name, company_id)",
        "Reference must be unique per company!",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # `default_get` depends only on the context, so resolve it once for the batch.
        defaults = self.default_get(["name", "picking_type_id"])
        default_name = defaults.get("name", "/")
        default_picking_type_id = defaults.get("picking_type_id")
        # Prefetch every referenced picking type so `sequence_id` reads in the loop
        # cost one query, not one per distinct type.
        type_ids = {
            vals.get("picking_type_id", default_picking_type_id) for vals in vals_list
        }
        type_ids.discard(False)
        self.env["stock.picking.type"].browse(type_ids).mapped("sequence_id")
        date_planneds = []
        for vals in vals_list:
            picking_type_id = vals.get("picking_type_id", default_picking_type_id)
            if vals.get("name", "/") == "/" and default_name == "/" and picking_type_id:
                picking_type = self.env["stock.picking.type"].browse(picking_type_id)
                if picking_type.sequence_id:
                    vals["name"] = picking_type.sequence_id.next_by_id()

            # Defer `date_planned` until after the moves exist, so
            # `_inverse_date_planned` runs on a fully-formed picking.
            date_planneds.append(vals.pop("date_planned", False))

        pickings = super().create(vals_list)

        # Group by the deferred value so pickings sharing a `date_planned` are written
        # (cascading to their moves) once per distinct date, not one-by-one.
        ids_by_date_planned = defaultdict(list)
        for picking, date_planned in zip(pickings, date_planneds, strict=True):
            if date_planned:
                ids_by_date_planned[date_planned].append(picking.id)
        for date_planned, picking_ids in ids_by_date_planned.items():
            self.browse(picking_ids).with_context(mail_notrack=True).write(
                {"date_planned": date_planned},
            )
        pickings._autoconfirm_picking()

        return pickings

    def write(self, vals):
        pickings_changing_type = self.browse()
        if vals.get("picking_type_id"):
            if any(picking.state in DONE_CANCEL_STATES for picking in self):
                raise UserError(
                    _(
                        "Changing the operation type of this record is forbidden at this point.",
                    ),
                )
            picking_type = self.env["stock.picking.type"].browse(
                vals["picking_type_id"],
            )
            pickings_changing_type = self.filtered(
                lambda picking: picking.picking_type_id != picking_type,
            )
            if pickings_changing_type and picking_type.sequence_id:
                for picking in pickings_changing_type:
                    picking.name = picking_type.sequence_id.next_by_id()

        res = super().write(vals)

        # Apply each changed picking's default locations *after* the type is set, so
        # they resolve per-record with that picking's own partner/company (the
        # supplier/customer override) rather than one value forced onto the batch.
        # Never override a location the caller passed explicitly in this same write; the
        # recursive write cascades the change to the picking's moves (see `after_vals`).
        write_src = "location_id" not in vals
        write_dest = "location_dest_id" not in vals
        if pickings_changing_type and (write_src or write_dest):
            # Group pickings sharing the same resolved pair so the cascade to moves runs
            # once per distinct pair (mirrors the `date_planned` grouping in `create`).
            ids_by_locations = defaultdict(list)
            for picking in pickings_changing_type:
                ids_by_locations[picking._get_type_default_location_ids()].append(
                    picking.id,
                )
            for (location_src, location_dest), picking_ids in ids_by_locations.items():
                type_location_vals = {}
                if write_src:
                    type_location_vals["location_id"] = location_src
                if write_dest:
                    type_location_vals["location_dest_id"] = location_dest
                self.browse(picking_ids).write(type_location_vals)

        if vals.get("date_done"):
            self.filtered(lambda p: p.state == "done").move_ids.date = vals["date_done"]
        if vals.get("signature"):
            for picking in self:
                picking._attach_sign()
        after_vals = {}
        if vals.get("location_id"):
            after_vals["location_id"] = vals["location_id"]
        if vals.get("location_dest_id"):
            after_vals["location_dest_id"] = vals["location_dest_id"]
        if "partner_id" in vals:
            after_vals["partner_id"] = vals["partner_id"]
        if after_vals:
            # Scrap moves (dest "inventory") keep their own location; exclude them.
            self.move_ids.filtered(
                lambda move: move.location_dest_usage != "inventory",
            ).write(after_vals)
        if vals.get("move_ids"):
            self._autoconfirm_picking()

        return res

    def unlink(self):
        self.move_ids._action_cancel()
        self.with_context(
            prefetch_fields=False,
        ).move_ids.unlink()  # Checks if moves are not done
        return super().unlink()

    # ------------------------------------------------------------
    # DEFAULT METHODS
    # ------------------------------------------------------------

    def _default_picking_type_id(self):
        picking_type_code = self.env.context.get("restricted_picking_type_code")
        if not picking_type_code:
            return False
        picking_types = self.env["stock.picking.type"].search(
            [
                ("code", "=", picking_type_code),
                ("company_id", "=", self.env.company.id),
            ],
        )
        return picking_types[:1].id

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_has_tracking(self):
        for picking in self:
            picking.has_tracking = any(
                m.has_tracking != "none" for m in picking.move_ids
            )

    def _compute_is_date_editable(self):
        for picking in self:
            if picking.state in DONE_CANCEL_STATES:
                picking.is_date_editable = not picking.is_locked
            else:
                picking.is_date_editable = True

    @api.depends("picking_type_id")
    def _compute_move_type(self):
        for record in self:
            record.move_type = record.picking_type_id.move_type

    @api.depends("date_deadline", "date_planned")
    def _compute_has_deadline_issue(self):
        for picking in self:
            # Guard `date_planned`: comparing a datetime to False raises TypeError.
            picking.has_deadline_issue = bool(
                picking.date_deadline
                and picking.date_planned
                and picking.date_deadline < picking.date_planned
            )

    @api.depends("move_ids.date_delay_alert")
    def _compute_date_delay_alert(self):
        read_group = self.env["stock.move"]._read_group(
            [("id", "in", self.move_ids.ids), ("date_delay_alert", "!=", False)],
            ["picking_id"],
            ["date_delay_alert:max"],
        )
        date_delay_alert_by_picking = {
            picking.id: date_delay_alert for picking, date_delay_alert in read_group
        }
        for picking in self:
            picking.date_delay_alert = date_delay_alert_by_picking.get(
                picking.id, False
            )

    @api.depends("signature")
    def _compute_is_signed(self):
        for picking in self:
            picking.is_signed = bool(picking.signature)

    @api.depends(
        "state",
        "picking_type_code",
        "date_planned",
        "move_ids",
        "move_ids.forecast_availability",
        "move_ids.date_planned_forecast",
    )
    def _compute_products_availability(self):
        pickings = self.filtered(
            lambda picking: (
                picking.state in ("waiting", "confirmed", "assigned")
                and picking.picking_type_code in ("outgoing", "internal")
            ),
        )
        pickings.products_availability_state = "available"
        pickings.products_availability = _("Available")
        other_pickings = self - pickings
        other_pickings.products_availability = False
        other_pickings.products_availability_state = False

        all_moves = pickings.move_ids
        # Batch-compute forecast_availability for all moves, not per prefetch chunk.
        all_moves._fields["forecast_availability"].compute_value(all_moves)
        for picking in pickings:
            # Draft moves check forecast_availability against 0, not the full demand.
            if any(
                move.product_id
                and move.product_id.uom_id.compare(
                    move.forecast_availability,
                    0 if move.state == "draft" else move.product_qty,
                )
                == -1
                for move in picking.move_ids
            ):
                picking.products_availability = _("Not Available")
                picking.products_availability_state = "late"
            else:
                forecast_date = max(
                    picking.move_ids.filtered("date_planned_forecast").mapped(
                        "date_planned_forecast",
                    ),
                    default=False,
                )
                if forecast_date:
                    picking.products_availability = _(
                        "Exp %s",
                        format_date(self.env, forecast_date),
                    )
                    picking.products_availability_state = (
                        "late"
                        if picking.date_planned and picking.date_planned < forecast_date
                        else "expected"
                    )

    @api.depends(
        "move_line_ids",
        "picking_type_id.use_create_lots",
        "picking_type_id.use_existing_lots",
        "state",
    )
    def _compute_show_lots_text(self):
        group_production_lot_enabled = self.env.user.has_group(
            "stock.group_production_lot",
        )
        for picking in self:
            if (
                not picking.move_line_ids
                and not picking.picking_type_id.use_create_lots
            ):
                picking.show_lots_text = False
            elif (
                group_production_lot_enabled
                and picking.picking_type_id.use_create_lots
                and not picking.picking_type_id.use_existing_lots
                and picking.state != "done"
            ):
                picking.show_lots_text = True
            else:
                picking.show_lots_text = False

    @api.depends("state", "date_delay_alert", "move_ids.date_delay_alert")
    def _compute_json_popover(self):
        picking_no_alert = self.filtered(
            lambda p: p.state in DONE_CANCEL_STATES or not p.date_delay_alert,
        )
        picking_no_alert.json_popover = False
        for picking in self - picking_no_alert:
            picking.json_popover = json.dumps(
                {
                    "popoverTemplate": "stock.PopoverStockRescheduling",
                    "date_delay_alert": format_datetime(
                        self.env,
                        picking.date_delay_alert,
                        dt_format=False,
                    ),
                    "late_elements": [
                        {
                            "id": late_move.id,
                            "name": late_move.display_name,
                            "model": late_move._name,
                        }
                        for late_move in picking.move_ids.filtered(
                            lambda m: m.date_delay_alert,
                        ).move_orig_ids._delay_alert_get_documents()
                    ],
                },
            )

    # `location_id` and `move_ids.procure_method` are read by the
    # reservation-bypass branch below, so both must retrigger the compute.
    # `procure_method` is (re)written almost only during confirmation, which
    # rewrites move states in the same flush, so the extra trigger is
    # essentially free.
    @api.depends(
        "move_type",
        "move_ids.state",
        "move_ids.picking_id",
        "move_ids.procure_method",
        "location_id",
    )
    def _compute_state(self):
        """State of a picking depends on the state of its related stock.move
        - Draft: only used for "planned pickings"
        - Waiting: if the picking is not ready to be sent so if
          - (a) no quantity could be reserved at all or if
          - (b) some quantities could be reserved and the shipping policy is "deliver all at once"
        - Waiting another move: if the picking is waiting for another move
        - Ready: if the picking is ready to be sent so if:
          - (a) all quantities are reserved or if
          - (b) some quantities could be reserved and the shipping policy is "as soon as possible"
          - (c) it's an incoming picking
        - Done: if the picking is done.
        - Cancelled: if the picking is cancelled
        """
        # Read moves from the database (rather than `self.move_ids`) so the state
        # reflects committed moves regardless of the in-memory cache. Collect ids and
        # `browse` once per picking to avoid the quadratic cost of repeated `|=` union.
        move_ids_by_picking = defaultdict(list)
        for move in self.env["stock.move"].search([("picking_id", "in", self.ids)]):
            move_ids_by_picking[move.picking_id.id].append(move.id)

        for picking in self:
            # When an existing picking is edited in a form, `picking.id` is a NewId
            # wrapping the database record; its committed moves are keyed by the real
            # (origin) id, so resolve that to look them up.
            picking_id = picking._origin.id or picking.id
            moves = self.env["stock.move"].browse(
                move_ids_by_picking.get(picking_id, ()),
            )
            move_states = set(moves.mapped("state"))

            if not moves or "draft" in move_states:
                picking.state = "draft"
            elif move_states == {"cancel"}:
                picking.state = "cancel"
            elif move_states <= DONE_CANCEL_STATES:
                # Every done move landed in an inventory location (i.e. was scrapped)
                # while at least one move was cancelled outside inventory: the picking
                # as a shipment did nothing, so it reads as cancelled rather than done.
                done_moves = moves.filtered(lambda m: m.state == "done")
                cancel_moves = moves.filtered(lambda m: m.state == "cancel")
                all_done_are_scrapped = all(
                    m.location_dest_usage == "inventory" for m in done_moves
                )
                any_cancel_and_not_scrapped = any(
                    m.location_dest_usage != "inventory" for m in cancel_moves
                )
                if all_done_are_scrapped and any_cancel_and_not_scrapped:
                    picking.state = "cancel"
                else:
                    picking.state = "done"
            elif picking.location_id.should_bypass_reservation() and all(
                m.procure_method == "make_to_stock" for m in moves
            ):
                picking.state = "assigned"
            else:
                relevant_move_state = moves._get_relevant_state_among_moves()
                if relevant_move_state == "partially_available":
                    picking.state = "assigned"
                else:
                    picking.state = relevant_move_state

    @api.depends("move_ids.state", "move_ids.date", "move_type")
    def _compute_date_planned(self):
        for picking in self:
            if not picking.id:
                continue
            moves_dates = picking.move_ids.filtered(
                lambda move: move.state not in DONE_CANCEL_STATES,
            ).mapped("date")
            if picking.move_type == "direct":
                picking.date_planned = min(
                    moves_dates,
                    default=picking.date_planned or fields.Datetime.now(),
                )
            else:
                picking.date_planned = max(
                    moves_dates,
                    default=picking.date_planned or fields.Datetime.now(),
                )

    def _measure_total_by_picking(
        self,
        model_name,
        extra_domain,
        uom_fname,
        product_attr,
    ):
        """Sum ``product.<product_attr>`` weighted by line quantity for every line of
        ``self`` living in ``model_name``, returning ``{picking_id: total}``.

        UoM conversion is linear, so grouping by (picking, product, uom) and converting
        the summed quantity is equivalent to converting each line one by one — a single
        read_group instead of a per-line conversion, and no grouping on the continuous
        ``quantity`` measure. Shared by `_compute_bulk_weight` and
        `_compute_shipping_volume`.

        Reads assigned rows only (``_read_group``): quantities still pending in an
        unsaved form view do not contribute. Acceptable while both consumers are
        list-view/report fields; a cache-aware loop is needed before exposing them
        on an editable form.
        """
        totals = defaultdict(float)
        res_groups = self.env[model_name]._read_group(
            [
                ("picking_id", "in", self.ids),
                ("product_id", "!=", False),
                *extra_domain,
            ],
            ["picking_id", "product_id", uom_fname],
            ["quantity:sum"],
        )
        for picking, product, product_uom_id, quantity in res_groups:
            totals[picking.id] += product_uom_id._compute_quantity(
                quantity, product.uom_id
            ) * getattr(product, product_attr)
        return totals

    @api.depends(
        "move_line_ids",
        "move_line_ids.result_package_id",
        "move_line_ids.product_uom_id",
        "move_line_ids.quantity",
    )
    def _compute_bulk_weight(self):
        weights = self._measure_total_by_picking(
            "stock.move.line",
            [("result_package_id", "=", False)],
            "product_uom_id",
            "weight",
        )
        for picking in self:
            picking.weight_bulk = weights[picking.id]

    @api.depends(
        "move_line_ids.result_package_id",
        "move_line_ids.result_package_id.package_type_id",
        "move_line_ids.result_package_id.shipping_weight",
        "move_line_ids.result_package_id.outermost_package_id",
        "move_line_ids.result_package_id.outermost_package_id.package_type_id",
        "move_line_ids.result_package_id.outermost_package_id.shipping_weight",
        "weight_bulk",
    )
    def _compute_shipping_weight(self):
        for picking in self:
            shipping_weight = picking.weight_bulk
            relevant_packages = (
                picking.move_line_ids.result_package_id.outermost_package_id
            )
            packages_weight = relevant_packages.sudo()._get_weight(picking.id)
            for package in relevant_packages:
                if package.shipping_weight:
                    shipping_weight += package.shipping_weight
                else:
                    # No shipping weight set: fall back to the computed product weight.
                    shipping_weight += packages_weight.get(package, 0)
            picking.shipping_weight = shipping_weight

    @api.depends(
        "move_ids.quantity",
        "move_ids.product_uom_id",
        "move_ids.product_id.volume",
    )
    def _compute_shipping_volume(self):
        volumes = self._measure_total_by_picking(
            "stock.move",
            [],
            "product_uom_id",
            "volume",
        )
        for picking in self:
            picking.shipping_volume = volumes[picking.id]

    @api.depends("move_ids.date_deadline", "move_ids.state", "move_type")
    def _compute_date_deadline(self):
        for picking in self:
            moves = picking.move_ids.filtered(
                lambda m: m.state != "cancel" and m.date_deadline
            )
            if picking.move_type == "direct":
                picking.date_deadline = min(
                    moves.mapped("date_deadline"),
                    default=False,
                )
            else:
                picking.date_deadline = max(
                    moves.mapped("date_deadline"),
                    default=False,
                )

    @api.depends("state", "move_line_ids.result_package_id", "package_history_ids")
    def _compute_count_packages(self):
        done_pickings = self.filtered(lambda picking: picking.state == "done")
        other_pickings = self - done_pickings

        packages_by_pick = defaultdict(int)
        # Can't _read_group() (picking_ids isn't stored) nor grouped()
        # (multiple pickings per package).
        packages = self.env["stock.package"].search(
            [("picking_ids", "in", other_pickings.ids)],
        )
        for pack in packages:
            for picking in pack.picking_ids:
                packages_by_pick[picking] += 1

        histories_by_pick = self.env["stock.package.history"]._read_group(
            [("picking_ids", "in", done_pickings.ids)],
            ["picking_ids"],
            ["__count"],
        )
        histories_by_pick = dict(histories_by_pick)

        for picking in done_pickings:
            picking.count_packages = histories_by_pick.get(picking, 0)
        for picking in other_pickings:
            picking.count_packages = packages_by_pick.get(picking, 0)

    @api.depends("state", "move_ids.product_uom_qty", "picking_type_code")
    def _compute_show_check_availability(self):
        """Whether the "Check Availability" button shows on the picking form."""
        for picking in self:
            if picking.state not in ("confirmed", "waiting", "assigned"):
                picking.show_check_availability = False
                continue
            if all(
                m.picked or m.product_uom_id.compare(m.product_uom_qty, m.quantity) == 0
                for m in picking.move_ids
            ):
                picking.show_check_availability = False
                continue
            picking.show_check_availability = any(
                move.state in ("waiting", "confirmed", "partially_available")
                and move.product_uom_id.compare(move.product_uom_qty, 0) > 0
                for move in picking.move_ids
            )

    @api.depends("state", "move_ids", "picking_type_id")
    def _compute_show_allocation(self):
        self.show_allocation = False
        if not self.env.user.has_group("stock.group_reception_report"):
            return
        show_by_picking = self._get_show_allocation_map()
        for picking in self:
            picking.show_allocation = show_by_picking.get(picking, False)

    def _get_show_allocation_map(self, excluded_pickings=None):
        """Map each picking in ``self`` to whether it has allocatable demand.

        Single batched implementation behind both `_compute_show_allocation` (the
        per-picking field) and `_get_show_allocation` (the batch-level OR). Sharing one
        implementation keeps the two from drifting — in particular the ``assigned``
        state counts as demand based on each picking's own done-ness, not an arbitrary
        first record's.

        :param excluded_pickings: pickings whose own moves never count as allocatable
            demand, on top of the picking being evaluated. `_get_show_allocation`
            passes the whole set so demand held by a sibling picking of the same
            batch never triggers the allocation button.
        """
        result = dict.fromkeys(self, False)
        excluded_ids = set(excluded_pickings.ids) if excluded_pickings else set()

        # Only non-outgoing pickings that still hold storable, non-cancelled moves can
        # have anything to allocate. Keep each such picking with its relevant moves.
        lines_by_picking = {}
        for picking in self:
            if (
                not picking.picking_type_id
                or picking.picking_type_id.code == "outgoing"
            ):
                continue
            lines = picking.move_ids.filtered(
                lambda m: m.product_id.is_storable and m.state != "cancel",
            )
            if lines:
                lines_by_picking[picking] = lines
        if not lines_by_picking:
            return result

        if len(lines_by_picking) == 1:
            # Fast path — the common per-form compute: one indexed EXISTS probe
            # instead of materialising every open demand move for the products.
            [(picking, lines)] = lines_by_picking.items()
            wh_location_ids = self._get_allocation_source_location_ids(
                picking.picking_type_id.warehouse_id.view_location_id.ids,
            )
            # A NewId picking has no committed moves to exclude; `.ids`-style
            # origin resolution keeps the domain free of NewId values.
            probe_excluded_ids = list(
                {pid for pid in excluded_ids | {picking._origin.id} if pid},
            )
            result[picking] = bool(
                self.env["stock.move"].search_count(
                    [
                        *self._get_allocatable_demand_domain(
                            wh_location_ids,
                            lines.product_id.ids,
                        ),
                        # Narrows the shared domain's include-assigned state list
                        # down to this picking's own done-ness.
                        (
                            "state",
                            "in",
                            self._get_allocation_allowed_move_states(
                                picking.state == "done",
                            ),
                        ),
                        ("picking_id", "not in", probe_excluded_ids),
                        "|",
                        ("move_orig_ids", "=", False),
                        ("move_orig_ids", "in", lines.ids),
                    ],
                    limit=1,
                ),
            )
            return result

        # Resolve the candidate source locations once per warehouse view location
        # (shared across every picking of that warehouse) instead of once per picking.
        location_ids_by_view = {}
        for picking in lines_by_picking:
            view_location = picking.picking_type_id.warehouse_id.view_location_id
            if view_location.id not in location_ids_by_view:
                location_ids_by_view[view_location.id] = set(
                    self._get_allocation_source_location_ids(view_location.ids),
                )

        # Fetch every potential allocation move in a single query, then decide per
        # picking in memory (replaces the previous per-picking search_count → N+1).
        candidate_products = self.env["product.product"].union(
            *(lines.product_id for lines in lines_by_picking.values()),
        )
        candidate_location_ids = set().union(*location_ids_by_view.values())
        candidate_domain = self._get_allocatable_demand_domain(
            candidate_location_ids,
            candidate_products.ids,
        )
        if excluded_ids:
            candidate_domain.append(("picking_id", "not in", list(excluded_ids)))
        candidate_moves = self.env["stock.move"].search(candidate_domain)

        # Index candidate moves by product so each picking only scans the moves for its
        # own products, instead of the full candidate set (was O(pickings × moves)).
        moves_by_product = defaultdict(list)
        for move in candidate_moves:
            moves_by_product[move.product_id].append(move)

        for picking, lines in lines_by_picking.items():
            allowed_states = set(
                self._get_allocation_allowed_move_states(picking.state == "done"),
            )
            view_location = picking.picking_type_id.warehouse_id.view_location_id
            wh_location_ids = location_ids_by_view[view_location.id]
            result[picking] = any(
                move.state in allowed_states
                and move.picking_id != picking
                and move.location_id.id in wh_location_ids
                and (not move.move_orig_ids or move.move_orig_ids & lines)
                for product in lines.product_id
                for move in moves_by_product.get(product, ())
            )
        return result

    @api.depends("picking_type_id", "partner_id")
    def _compute_location_id(self):
        for picking in self:
            if picking.state in DONE_CANCEL_STATES or picking.return_id:
                continue
            if picking.picking_type_id:
                picking.location_id, picking.location_dest_id = (
                    picking._get_type_default_location_ids()
                )

    def _get_type_default_location_ids(self):
        """(source_id, dest_id) for this picking's operation type, applying the
        partner's supplier/customer location override. Single source of truth shared
        by `_compute_location_id` and the picking-type change in `write`, so both
        resolve locations identically (and per-record with each partner/company).
        """
        self.ensure_one()
        picking = self.with_company(self.company_id)
        location_src = picking.picking_type_id.default_location_src_id
        if location_src.usage == "supplier" and picking.partner_id:
            location_src = picking.partner_id.property_stock_supplier
        location_dest = picking.picking_type_id.default_location_dest_id
        if location_dest.usage == "customer" and picking.partner_id:
            location_dest = picking.partner_id.property_stock_customer
        return location_src.id, location_dest.id

    @api.depends("return_ids")
    def _compute_return_count(self):
        for picking in self:
            picking.return_count = len(picking.return_ids)

    @api.depends("partner_id.name", "partner_id.parent_id.name")
    def _compute_picking_warning_text(self):
        if not self.env.user.has_group("stock.group_warning_stock"):
            self.picking_warning_text = ""
            return
        for picking in self:
            text = ""
            if partner_msg := picking.partner_id.picking_warn_msg:
                text += partner_msg + "\n"
            if parent_msg := picking.partner_id.parent_id.picking_warn_msg:
                text += parent_msg + "\n"
            picking.picking_warning_text = text

    @api.depends("move_ids.move_dest_ids")
    def _compute_show_next_pickings(self):
        # Per-record: `_get_next_transfers` aggregates over the whole recordset, so a
        # scalar assignment would OR every picking's next-transfers together.
        for picking in self:
            picking.show_next_pickings = bool(picking._get_next_transfers())

    @api.depends("move_ids.location_dest_usage")
    def _compute_has_scrap_move(self):
        result = {
            picking
            for [picking] in self.env["stock.move"]._read_group(
                [
                    ("picking_id", "in", self.ids),
                    ("location_dest_usage", "=", "inventory"),
                ],
                ["picking_id"],
            )
        }
        for picking in self:
            picking.has_scrap_move = picking._origin in result

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_date_planned(self):
        for picking in self:
            if picking.state == "cancel":
                raise UserError(
                    _("You cannot change the Scheduled Date on a cancelled transfer."),
                )
            if picking.state == "done":
                continue
            # Mirror `_compute_date_planned`: only open moves follow the
            # scheduled date. Done moves (e.g. a scrap validated from this
            # picking) keep their effective date — `stock.move.write` cascades
            # `date` to done move lines, so rewriting it would corrupt
            # inventory history.
            picking.move_ids.filtered(
                lambda move: move.state not in DONE_CANCEL_STATES,
            ).write({"date": picking.date_planned})

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_date_category(self, operator, value):
        if operator != "in":
            return NotImplemented
        # `date_category_to_domain` returns None for unknown categories (reachable
        # through raw RPC domains): skip them so they match nothing instead of
        # crashing. `Domain.OR` of an empty list is `Domain.FALSE`.
        return Domain.OR(
            domain
            for item in value
            if (domain := self.date_category_to_domain("date_planned", item))
        )

    def _search_products_availability_state(self, operator, value):
        if operator != "in":
            return NotImplemented

        # Normalise to a set: the branches below rely on set algebra (`- {False}`, `&`).
        value = set(value)
        invalid_states = ("done", "cancel", "draft")
        # A picking carries a non-False availability state only when it is
        # waiting/confirmed/assigned AND of an outgoing/internal type — the condition
        # `_compute_products_availability` applies. Every other picking reads as False
        # (even if its moves are reservable), so the search must scope itself the same.
        qualifying = Domain(
            [
                ("state", "not in", invalid_states),
                ("picking_type_id.code", "in", ("outgoing", "internal")),
            ],
        )
        if False in value:
            # False is exactly the complement of the qualifying set: a qualifying
            # picking always carries one of available/expected/late, never False.
            return ~qualifying | self._search_products_availability_state(
                "in",
                value - {False},
            )
        value = (
            set(self._fields["products_availability_state"].get_values(self.env))
            & value
        )
        if not value:
            return Domain.FALSE

        def _get_comparison_date(move):
            return move.picking_id.date_planned

        def _filter_picking_moves(picking):
            try:
                return picking.move_ids._match_searched_availability(
                    operator,
                    value,
                    _get_comparison_date,
                )
            except UserError:
                # invalid value for search
                return False

        # Only qualifying pickings can match, so scan just those and batch-compute the
        # forecast field the matcher reads in one pass over their moves, instead of the
        # default per-chunk recompute (mirrors `_compute_products_availability`).
        candidate_pickings = self.env["stock.picking"].search(qualifying, order="id")
        candidate_moves = candidate_pickings.move_ids
        candidate_moves._fields["forecast_availability"].compute_value(candidate_moves)
        pickings = candidate_pickings.filtered(_filter_picking_moves)
        return Domain("id", "in", pickings.ids)

    @api.model
    def _search_date_delay_alert(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return [("move_ids.date_delay_alert", operator, value)]

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("picking_type_id", "partner_id")
    def _onchange_picking_type(self):
        if self.picking_type_id and self.state == "draft":
            self = self.with_company(self.company_id)
            self.move_ids.filtered(
                lambda m: m.picking_type_id != self.picking_type_id,
            ).picking_type_id = self.picking_type_id
            self.move_ids.company_id = self.company_id

    @api.onchange("location_id")
    def _onchange_location_id(self):
        self.move_ids.location_id = self.location_id
        for move in self.move_ids.filtered(lambda m: m.move_orig_ids):
            for ml in move.move_line_ids:
                parent_path = [
                    int(loc_id) for loc_id in ml.location_id.parent_path.split("/")[:-1]
                ]
                if self.location_id.id not in parent_path:
                    return {
                        "warning": {
                            "title": _("Warning: change source location"),
                            "message": _(
                                "Updating the location of this transfer will result in unreservation of the currently assigned items. "
                                "An attempt to reserve items at the new location will be made and the link with preceding transfers will be discarded.\n\n"
                                "To avoid this, please discard the source location change before saving.",
                            ),
                        },
                    }
        return None

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def do_print_picking(self):
        self.write({"printed": True})
        return self.env.ref("stock.action_report_picking").report_action(self)

    def action_confirm(self):
        self._check_company()
        self.move_ids.filtered(lambda move: move.state == "draft")._action_confirm()

        self.move_ids.filtered(
            lambda move: move.state not in ("draft", "cancel", "done"),
        )._trigger_scheduler()
        return True

    def action_assign(self):
        """Reserve quants for the picking's moves, updating move (and picking) state."""
        self.filtered(lambda picking: picking.state == "draft").action_confirm()
        moves = self.move_ids.filtered(
            lambda move: move.state not in ("draft", "cancel", "done"),
        ).sorted(
            key=lambda move: (
                -int(move.priority),
                not bool(move.date_deadline),
                move.date_deadline,
                move.date,
                move.id,
            ),
        )
        if not moves:
            raise UserError(_("Nothing to check the availability for."))
        moves._action_assign()
        return True

    def action_cancel(self):
        self.move_ids._action_cancel()
        self.write({"is_locked": True})
        self.filtered(lambda x: not x.move_ids).state = "cancel"
        return True

    def action_detailed_operations(self):
        view_id = self.env.ref("stock.view_stock_move_line_detailed_operation_tree").id
        return {
            "name": _("Detailed Operations"),
            "view_mode": "list",
            "type": "ir.actions.act_window",
            "res_model": "stock.move.line",
            "views": [(view_id, "list")],
            "domain": [("picking_id", "=", self.id)],
            "context": {
                "sml_specific_default": True,
                "default_picking_id": self.id,
                "default_location_id": self.location_id.id,
                "default_location_dest_id": self.location_dest_id.id,
                "default_company_id": self.company_id.id,
                "show_lots_text": self.show_lots_text,
                "picking_code": self.picking_type_code,
                "create": self.state not in DONE_CANCEL_STATES,
            },
        }

    def action_next_transfer(self):
        next_transfers = self._get_next_transfers()

        if len(next_transfers) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "views": [[False, "form"]],
                "res_id": next_transfers.id,
            }
        return {
            "name": _("Next Transfers"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", next_transfers.ids)],
        }

    def _action_done(self):
        """Call `_action_done` on the `stock.move` of the `stock.picking` in `self`.
        This method makes sure every `stock.move.line` is linked to a `stock.move` by either
        linking them to an existing one or a newly created one.

        If the context key `cancel_backorder` is present, backorders won't be created.

        :return: True
        :rtype: bool
        """
        self._check_company()

        todo_moves = self.move_ids.filtered(
            lambda self: (
                self.state
                in ["draft", "waiting", "partially_available", "assigned", "confirmed"]
            ),
        )
        for picking in self:
            if picking.owner_id:
                picking.move_ids.write({"restrict_partner_id": picking.owner_id.id})
                picking.move_line_ids.write({"owner_id": picking.owner_id.id})
        todo_moves._action_done(
            cancel_backorder=self.env.context.get("cancel_backorder"),
        )
        self.write({"date_done": fields.Datetime.now(), "priority": "0"})

        # If incoming/internal moves free up other confirmed/partially_available moves,
        # assign them.
        done_incoming_moves = self.filtered(
            lambda p: p.picking_type_id.code in ("incoming", "internal"),
        ).move_ids.filtered(lambda m: m.state == "done")
        done_incoming_moves._trigger_assign()

        self._send_confirmation_email()
        return True

    def _send_confirmation_email(self):
        pickings_to_notify = self.filtered(
            lambda p: (
                p.company_id.stock_move_email_validation
                and p.picking_type_id.code == "outgoing"
            ),
        )
        if not pickings_to_notify:
            return
        subtype_id = self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_comment")
        for stock_pick in pickings_to_notify:
            delivery_template = (
                stock_pick.company_id.stock_mail_confirmation_template_id
            )
            stock_pick.with_context(force_send=True).message_post_with_source(
                delivery_template,
                email_layout_xmlid="mail.mail_notification_light",
                subtype_id=subtype_id,
            )

    def do_unreserve(self):
        self.move_ids._do_unreserve()

    def button_validate(self):
        self = self.filtered(lambda p: p.state != "done")
        draft_picking = self.filtered(lambda p: p.state == "draft")
        draft_picking.action_confirm()
        for move in draft_picking.move_ids:
            if move.product_uom_id.is_zero(
                move.quantity
            ) and not move.product_uom_id.is_zero(
                move.product_uom_qty,
            ):
                move.quantity = move.product_uom_qty

        if not self.env.context.get("skip_sanity_check", False):
            self._sanity_check()

        # Pre-validation wizards touch only moves/context, never call `_action_done`.
        if not self.env.context.get("button_validate_picking_ids"):
            self = self.with_context(button_validate_picking_ids=self.ids)
        res = self._pre_action_done_hook()
        if res is not True:
            return res

        pickings_to_backorder, pickings_not_to_backorder = (
            self._split_backorder_pickings()
        )
        if pickings_not_to_backorder:
            pickings_not_to_backorder.with_context(cancel_backorder=True)._action_done()
        if pickings_to_backorder:
            pickings_to_backorder.with_context(cancel_backorder=False)._action_done()
        report_actions = self._get_autoprint_report_actions()
        another_action = self._get_reception_report_action()
        if another_action and not report_actions:
            return another_action
        if report_actions:
            return {
                "type": "ir.actions.client",
                "tag": "do_multi_print",
                "params": {
                    "reports": report_actions,
                    "anotherAction": another_action,
                },
            }
        return True

    def _split_backorder_pickings(self):
        """Partition ``self`` into ``(to_backorder, not_to_backorder)`` for validation.

        A picking goes to the no-backorder side when its type's ``create_backorder`` is
        ``"never"``, or when it is listed in the ``picking_ids_not_to_backorder`` context
        (unless its type forces ``"always"``). The context is intersected with ``self``,
        so validation never reaches pickings the caller did not pass (e.g. records
        already filtered out as done by `button_validate`).
        """
        not_to_backorder = self.filtered(
            lambda p: p.picking_type_id.create_backorder == "never",
        )
        if self.env.context.get("picking_ids_not_to_backorder"):
            not_to_backorder |= (
                self.browse(self.env.context["picking_ids_not_to_backorder"]) & self
            ).filtered(lambda p: p.picking_type_id.create_backorder != "always")
        return self - not_to_backorder, not_to_backorder

    def _get_reception_report_action(self):
        """Return the reception-report action to open after validation, or ``False``.

        Shown only when the reception-report feature is enabled and at least one
        just-received product has allocatable demand waiting in its warehouse.
        """
        if not self.env.user.has_group("stock.group_reception_report"):
            return False
        pickings_show_report = self.filtered(
            lambda p: p.picking_type_id.auto_show_reception_report,
        )
        lines = pickings_show_report.move_ids.filtered(
            lambda m: (
                m.product_id.is_storable
                and m.state != "cancel"
                and m.quantity
                and not m.move_dest_ids
            ),
        )
        if not lines:
            return False
        # don't show reception report if all already assigned/nothing to assign
        wh_location_ids = pickings_show_report._get_allocation_source_location_ids(
            pickings_show_report.picking_type_id.warehouse_id.view_location_id.ids,
        )
        if not self.env["stock.move"].search_count(
            [
                *self._get_allocatable_demand_domain(
                    wh_location_ids,
                    lines.product_id.ids,
                ),
                # Reception report only offers *fresh* demand: moves with no origin,
                # from other pickings. `_get_show_allocation_map` differs on purpose —
                # it also re-surfaces demand chained to this receipt's own lines
                # (`move_orig_ids & lines`).
                ("move_orig_ids", "=", False),
                ("picking_id", "not in", pickings_show_report.ids),
            ],
            limit=1,
        ):
            return False
        action = pickings_show_report.action_view_reception_report()
        action["context"] = {"default_picking_ids": pickings_show_report.ids}
        return action

    def action_split_transfer(self):
        self.ensure_one()
        if all(m.product_uom_id.is_zero(m.quantity) for m in self.move_ids):
            raise UserError(
                _(
                    "%s: Nothing to split. Fill the quantities you want in a new transfer in the done quantities",
                    self.display_name,
                ),
            )
        # done-vs-demand per move: 0 = fully done, >0 = over demand, <0 = partial
        demand_comparisons = [
            m.product_uom_id.compare(m.quantity, m.product_uom_qty)
            for m in self.move_ids
        ]
        if all(comparison == 0 for comparison in demand_comparisons):
            raise UserError(
                _(
                    "%s: Nothing to split, all demand is done. For split you need at least one line not fully fulfilled",
                    self.display_name,
                ),
            )
        if any(comparison > 0 for comparison in demand_comparisons):
            raise UserError(
                _(
                    "%s: Can't split: quantities done can't be above demand",
                    self.display_name,
                ),
            )

        moves = self.move_ids.filtered(
            lambda m: m.state not in DONE_CANCEL_STATES and m.quantity != 0,
        )
        backorder_moves = moves._create_backorder()
        backorder_moves += self.move_ids.filtered(lambda m: m.quantity == 0)
        self._create_backorder(backorder_moves=backorder_moves)

    def _pre_action_done_hook(self):
        for picking in self:
            # Auto-pick everything when the picking has quantity to move but nothing was
            # picked explicitly. The asymmetry for inventory-destination (scrap) moves
            # is deliberate and load-bearing:
            #  * their quantity DOES count towards `has_quantity`, so a picking whose
            #    only move is scrap still auto-picks and validates (see test_scrap_10);
            #  * their quantity is auto-picked by the final write (all moves), so scrap
            #    transfers complete;
            #  * but a scrap move being `picked` does NOT count towards `has_pick`, so a
            #    pre-picked scrap move can't suppress auto-picking the real moves.
            has_quantity = False
            has_pick = False
            for move in picking.move_ids:
                if move.quantity:
                    has_quantity = True
                if move.location_dest_usage == "inventory":
                    continue
                if move.picked:
                    has_pick = True
                if has_quantity and has_pick:
                    break
            if has_quantity and not has_pick:
                picking.move_ids.picked = True
        if not self.env.context.get("skip_backorder"):
            pickings_to_backorder = self._check_backorder()
            if pickings_to_backorder:
                return pickings_to_backorder._action_generate_backorder_wizard(
                    show_transfers=self._should_show_transfers(),
                )
        return True

    def _action_generate_backorder_wizard(self, show_transfers=False):
        view = self.env.ref("stock.view_backorder_confirmation")
        return {
            "name": _("Create Backorder?"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.backorder.confirmation",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "context": dict(
                self.env.context,
                default_show_transfers=show_transfers,
                default_pick_ids=[(4, p.id) for p in self],
            ),
        }

    def action_toggle_is_locked(self):
        self.ensure_one()
        self.is_locked = not self.is_locked
        return True

    def action_put_in_pack(
        self,
        *,
        package_id=False,
        package_type_id=False,
        package_name=False,
    ):
        self.ensure_one()
        if self.env.context.get("sml_specific_default"):
            self = self.with_context(clean_context(self.env.context))
        if self.state in DONE_CANCEL_STATES:
            return None
        return self.move_line_ids.action_put_in_pack(
            package_id=package_id,
            package_type_id=package_type_id,
            package_name=package_name,
        )

    def button_scrap(self):
        self.ensure_one()
        view = self.env.ref("stock.view_stock_scrap_form2")
        products = self.env["product.product"]
        for move in self.move_ids:
            if (
                move.state not in ("draft", "cancel")
                and move.product_id.type == "consu"
            ):
                products |= move.product_id
        return {
            "name": _("Scrap Products"),
            "view_mode": "form",
            "res_model": "stock.scrap",
            "view_id": view.id,
            "views": [(view.id, "form")],
            "type": "ir.actions.act_window",
            "context": {
                "default_picking_id": self.id,
                "product_ids": products.ids,
                "default_company_id": self.company_id.id,
            },
            "target": "new",
        }

    def action_add_entire_packs(self, package_ids):
        self.ensure_one()
        if self.state not in DONE_CANCEL_STATES:
            all_packages = self.env["stock.package"].search(
                [("id", "child_of", package_ids)],
            )
            all_package_ids = set(all_packages.ids)
            # Drop existing move lines that already pull from these packages; we use
            # them fully now.
            self.move_line_ids.filtered(
                lambda ml: ml.package_id.id in all_package_ids,
            ).unlink()
            move_line_vals = self._prepare_entire_pack_move_line_vals(all_packages)
            pack_move_lines = self.env["stock.move.line"].create(move_line_vals)
            pack_move_lines._apply_putaway_strategy()
            # Need to set the right package dest for now fully contained packages
            self.move_line_ids.result_package_id._apply_package_dest_for_entire_packs(
                allowed_package_ids=all_package_ids,
            )
            return True
        return False

    def action_view_move_scrap(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_stock_scrap")
        scraps = self.env["stock.scrap"].search([("picking_id", "=", self.id)])
        action["domain"] = [("id", "in", scraps.ids)]
        action["context"] = dict(self.env.context, create=False)
        return action

    def action_view_packages(self):
        self.ensure_one()
        return {
            "name": self.env._("Packages"),
            "res_model": "stock.package",
            "view_mode": "list,kanban,form",
            "views": [
                (self.env.ref("stock.view_stock_package_list_editable").id, "list"),
                (False, "kanban"),
                (False, "form"),
            ],
            "type": "ir.actions.act_window",
            "domain": [("picking_ids", "in", self.ids)],
            "context": {
                "picking_ids": self.ids,
                "location_id": self.location_id.id,
                "can_add_entire_packs": self.picking_type_code != "incoming",
                "search_default_main_packages": True,
            },
        }

    def action_view_package_histories(self):
        self.ensure_one()
        return {
            "name": self.env._("Packages"),
            "res_model": "stock.package.history",
            "view_mode": "list",
            "views": [(False, "list")],
            "type": "ir.actions.act_window",
            "domain": [("picking_ids", "=", self.id)],
            "context": {
                "search_default_main_packages": 1,
            },
        }

    def action_view_move_list(self):
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_action")
        action["views"] = [
            (self.env.ref("stock.view_stock_move_list_picking").id, "list"),
        ]
        action["context"] = self.env.context
        action["domain"] = [("picking_id", "in", self.ids)]
        return action

    def action_view_reception_report(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_reception_action",
        )

    def action_view_label_layout(self):
        view = self.env.ref("stock.product_label_layout_form_picking")
        return {
            "name": _("Choose Labels Layout"),
            "type": "ir.actions.act_window",
            "res_model": "product.label.layout",
            "views": [(view.id, "form")],
            "target": "new",
            "context": {
                "default_product_ids": self.move_ids.product_id.ids,
                "default_move_ids": self.move_ids.ids,
                "default_move_quantity": "move",
            },
        }

    def action_view_label_type(self):
        if (
            self.env.user.has_group("stock.group_production_lot")
            and self.move_line_ids.lot_id
        ):
            view = self.env.ref("stock.picking_label_type_form")
            return {
                "name": _("Choose Type of Labels To Print"),
                "type": "ir.actions.act_window",
                "res_model": "picking.label.type",
                "views": [(view.id, "form")],
                "target": "new",
                "context": {"default_picking_ids": self.ids},
            }
        return self.action_view_label_layout()

    def action_view_returns(self):
        self.ensure_one()
        if len(self.return_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "views": [[False, "form"]],
                "res_id": self.return_ids.id,
            }
        return {
            "name": _("Returns"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", self.return_ids.ids)],
        }

    def _add_reference(self, reference):
        """Link the given references to the list of references."""
        self.ensure_one()
        self.move_ids.reference_ids = [
            Command.link(stock_reference.id) for stock_reference in reference
        ]

    def _attach_sign(self):
        """Render the delivery report in pdf and attach it to the picking in `self`."""
        self.ensure_one()
        report = self.env["ir.actions.report"]._render_qweb_pdf(
            "stock.action_report_delivery",
            self.id,
        )
        filename = "%s_signed_delivery_slip" % self.name
        if self.partner_id:
            message = _("Order signed by %s", self.partner_id.name)
        else:
            message = _("Order signed")
        self.message_post(
            attachments=[("%s.pdf" % filename, report[0])],
            body=message,
        )
        return True

    def _autoconfirm_picking(self):
        """Run `action_confirm` on pickings that gained a move after the initial
        `action_confirm` (which acts only on draft moves).
        """
        pickings_with_additional_moves = self.filtered(
            lambda picking: (
                picking.state not in DONE_CANCEL_STATES
                and any(move.additional for move in picking.move_ids)
            ),
        )
        if pickings_with_additional_moves:
            pickings_with_additional_moves.action_confirm()
        to_confirm = self.move_ids.filtered(lambda m: m.state == "draft" and m.quantity)
        to_confirm._action_confirm()

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _autoprint_action(self, report_xmlid, records, data=None):
        """Build a cleaned auto-print action for `records`, or None if there's nothing
        to print. Centralises the `report_action(..., config=False)` + `clean_action`
        boilerplate shared by every direct-report auto-print helper.
        """
        if not records:
            return None
        action = self.env.ref(report_xmlid).report_action(
            records,
            data=data,
            config=False,
        )
        clean_action(action, self.env)
        return action

    def _autoprint_delivery_slip(self):
        action = self._autoprint_action(
            "stock.action_report_delivery",
            self.filtered(lambda p: p.picking_type_id.auto_print_delivery_slip),
        )
        return [action] if action else []

    def _autoprint_return_slip(self):
        action = self._autoprint_action(
            "stock.return_label_report",
            self.filtered(lambda p: p.picking_type_id.auto_print_return_slip),
        )
        return [action] if action else []

    def _autoprint_reception_reports(self):
        """Reception report and reception-report labels (reception-report group only)."""
        if not self.env.user.has_group("stock.group_reception_report"):
            return []
        actions = []
        report_action = self._autoprint_action(
            "stock.stock_reception_report_action",
            self.filtered(
                lambda p: (
                    p.picking_type_id.auto_print_reception_report
                    and p.picking_type_id.code != "outgoing"
                    and p.move_ids.move_dest_ids
                ),
            ),
        )
        if report_action:
            actions.append(report_action)
        reception_labels_to_print = self.filtered(
            lambda p: (
                p.picking_type_id.auto_print_reception_report_labels
                and p.picking_type_id.code != "outgoing"
            ),
        )
        moves_to_print = reception_labels_to_print.move_ids.move_dest_ids
        if moves_to_print:
            # needs to be string to support python + js calls to report
            quantities = ",".join(
                str(qty)
                for qty in moves_to_print.mapped(
                    lambda m: math.ceil(m.product_uom_qty),
                )
            )
            label_action = self._autoprint_action(
                "stock.label_picking",
                moves_to_print,
                data={"docids": moves_to_print.ids, "quantity": quantities},
            )
            if label_action:
                actions.append(label_action)
        return actions

    def _autoprint_product_labels(self):
        actions = []
        pickings_print_product_label = self.filtered(
            lambda p: p.picking_type_id.auto_print_product_labels,
        )
        # Group by format value (not picking type) so each distinct format yields one
        # action. Iterating `mapped(...)` instead would duplicate a format shared by two
        # types, and reading the format off a >1-type group would raise a singleton.
        for print_format, pickings in pickings_print_product_label.grouped(
            lambda p: p.picking_type_id.product_label_format,
        ).items():
            wizard = self.env["product.label.layout"].create(
                {
                    "product_ids": pickings.move_ids.product_id.ids,
                    "move_ids": pickings.move_ids.ids,
                    "move_quantity": "move",
                    "print_format": print_format,
                },
            )
            action = wizard.process()
            if action:
                clean_action(action, self.env)
                actions.append(action)
        return actions

    def _autoprint_lot_labels(self):
        if not self.env.user.has_group("stock.group_production_lot"):
            return []
        actions = []
        pickings_print_lot_label = self.filtered(
            lambda p: (
                p.picking_type_id.auto_print_lot_labels and p.move_line_ids.lot_id
            ),
        )
        # Group by format value so each distinct format yields one action (see
        # `_autoprint_product_labels` for why iterating `mapped(...)` is wrong).
        for print_format, pickings in pickings_print_lot_label.grouped(
            lambda p: p.picking_type_id.lot_label_format,
        ).items():
            wizard = self.env["lot.label.layout"].create(
                {
                    "move_line_ids": pickings.move_line_ids.ids,
                    "label_quantity": "lots" if "_lots" in print_format else "units",
                    "print_format": "4x12" if "4x12" in print_format else "zpl",
                },
            )
            action = wizard.process()
            if action:
                clean_action(action, self.env)
                actions.append(action)
        return actions

    def _autoprint_package_report(self):
        if not self.env.user.has_group("stock.group_tracking_lot"):
            return []
        action = self._autoprint_action(
            "stock.action_report_picking_packages",
            self.filtered(
                lambda p: (
                    p.picking_type_id.auto_print_packages
                    and p.move_line_ids.result_package_id
                ),
            ),
        )
        return [action] if action else []

    @api.model
    def calculate_date_category(self, value):
        """Classify `value` (a datetime, assumed UTC) as "before", "yesterday", "today",
        "day_1" (tomorrow), "day_2" or "after", relative to the current user's timezone.
        Returns "" if `value` is falsy.
        """
        if not value:
            return ""
        # Stored datetimes are naive UTC; `astimezone` would reinterpret a naive
        # value in the server's OS timezone, so attach UTC explicitly instead.
        # Aware values are converted by instant, matching the tz-aware boundaries.
        if value.tzinfo is None:
            value = value.replace(tzinfo=pytz.UTC)
        else:
            value = value.astimezone(pytz.UTC)
        bound = self._date_category_boundaries()
        if value < bound["yesterday"]:
            return "before"
        if value < bound["today"]:
            return "yesterday"
        if value < bound["day_1"]:
            return "today"
        if value < bound["day_2"]:
            return "day_1"
        if value < bound["day_3"]:
            return "day_2"
        return "after"

    def _create_backorder_picking(self):
        self.ensure_one()
        return self.copy(
            {
                "name": "/",
                "move_ids": [],
                "move_line_ids": [],
                "backorder_id": self.id,
                "return_id": self.return_id.id,
            },
        )

    def _create_backorder(self, backorder_moves=None):
        """Create a backorder picking and move the non-`done`/`cancel` stock.moves into
        it. Called when the user chose to create a backorder.
        """
        backorders = self.env["stock.picking"]
        bo_to_assign = self.env["stock.picking"]
        for picking in self:
            if backorder_moves:
                moves_to_backorder = backorder_moves.filtered(
                    lambda m, picking=picking: m.picking_id == picking,
                )
            else:
                moves_to_backorder = picking._get_moves_to_backorder()
            moves_to_backorder._recompute_state()
            if moves_to_backorder:
                backorder_picking = picking._create_backorder_picking()
                moves_to_backorder.write(
                    {"picking_id": backorder_picking.id, "picked": False},
                )
                moves_to_backorder.mapped("move_line_ids").write(
                    {"picking_id": backorder_picking.id},
                )
                backorders |= backorder_picking
                backorder_picking.user_id = False
                picking.message_post(
                    body=_(
                        "The backorder %s has been created.",
                        backorder_picking._get_html_link(),
                    ),
                )
                if backorder_picking.picking_type_id.reservation_method == "at_confirm":
                    bo_to_assign |= backorder_picking
        if bo_to_assign:
            bo_to_assign.action_assign()
        return backorders

    @api.model
    def _date_category_boundaries(self):
        """Day boundaries (tz-aware, in the current user's timezone) used to classify a
        datetime relative to today. Returns the start of "yesterday", "today", "day_1"
        (tomorrow), "day_2" and "day_3".
        """
        start_today = fields.Datetime.context_timestamp(
            self.env.user,
            fields.Datetime.now(),
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "yesterday": start_today + timedelta(days=-1),
            "today": start_today,
            "day_1": start_today + timedelta(days=1),
            "day_2": start_today + timedelta(days=2),
            "day_3": start_today + timedelta(days=3),
        }

    @api.model
    def date_category_to_domain(self, field_name, date_category):
        """Build a domain on `field_name` matching the given date category (one of "before",
        "yesterday", "today", "day_1", "day_2", "after"; see `calculate_date_category`).
        Returns None if `date_category` is not one of these.
        """
        # Stored datetimes are naive UTC, so express the boundaries the same way.
        bound = {
            key: value.astimezone(pytz.UTC).replace(tzinfo=None)
            for key, value in self._date_category_boundaries().items()
        }
        date_category_to_search_domain = {
            "before": [(field_name, "<", bound["yesterday"])],
            "yesterday": [
                (field_name, ">=", bound["yesterday"]),
                (field_name, "<", bound["today"]),
            ],
            "today": [
                (field_name, ">=", bound["today"]),
                (field_name, "<", bound["day_1"]),
            ],
            "day_1": [
                (field_name, ">=", bound["day_1"]),
                (field_name, "<", bound["day_2"]),
            ],
            "day_2": [
                (field_name, ">=", bound["day_2"]),
                (field_name, "<", bound["day_3"]),
            ],
            "after": [(field_name, ">=", bound["day_3"])],
        }
        return date_category_to_search_domain.get(date_category)

    def _get_next_transfers(self):
        next_pickings = self.move_ids.move_dest_ids.picking_id
        return next_pickings.filtered(lambda p: p not in self.return_ids)

    @api.model
    def _get_allocation_allowed_move_states(self, include_assigned=False):
        """Move states that count as allocatable demand for the reception report and the
        "show allocation" checks. ``assigned`` only qualifies once the receipt is done.
        """
        states = ["confirmed", "partially_available", "waiting"]
        if include_assigned:
            states.append("assigned")
        return states

    def _get_allocatable_demand_domain(self, location_ids, product_ids):
        """Common domain for "allocatable demand" moves: open demand (positive qty, an
        allocatable state) for the given products sitting in the given locations. Shared
        by `_get_show_allocation_map` and `_get_reception_report_action` so the two stay
        aligned on the baseline definition of demand; each caller then narrows it with
        its own ``move_orig_ids`` clause (which intentionally differ — see the callers).
        """
        return [
            (
                "state",
                "in",
                self._get_allocation_allowed_move_states(include_assigned=True),
            ),
            ("product_qty", ">", 0),
            ("location_id", "in", list(location_ids)),
            ("product_id", "in", list(product_ids)),
        ]

    def _get_allocation_source_location_ids(self, view_location_ids):
        """IDs of the locations allocatable demand can pull from: descendants of the
        given warehouse view location(s), excluding supplier locations. Shared by the
        reception report and the allocation checks so their location scope stays
        identical (single source of truth for this query).
        """
        return (
            self.env["stock.location"]
            .search(
                [
                    ("id", "child_of", view_location_ids),
                    ("usage", "!=", "supplier"),
                ],
            )
            .ids
        )

    def _get_show_allocation(self, picking_type_id):
        """Batch-level "show allocation": True when *any* picking in ``self`` has
        allocatable demand from outside the set. Delegates to
        `_get_show_allocation_map` with the whole set excluded, so demand held by a
        sibling picking of the same batch never counts (reused by e.g.
        stock.picking.batch).
        """
        if not picking_type_id or picking_type_id.code == "outgoing":
            return False
        return any(self._get_show_allocation_map(excluded_pickings=self).values())

    @api.model
    def get_empty_list_help(self, help_message):
        return self._render_picking_help()

    def _get_lot_move_lines_for_sanity_check(self):
        """Move lines with a tracked product and a done quantity — each must carry a
        lot/serial number, verified in the sanity check.
        """
        return self.move_line_ids.filtered(
            lambda ml: (
                ml.product_id
                and ml.product_id.tracking != "none"
                and ml.picked
                and ml.product_uom_id.compare(ml.quantity, 0)
            ),
        )

    @api.model
    def get_action_click_graph(self):
        return self._get_action("stock.action_picking_tree_graph")

    def _get_action(self, action_xmlid):
        action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
        context = dict(self.env.context)
        context.update(literal_eval(action["context"]))
        action["context"] = context

        action["help"] = self._render_picking_help(context)

        return action

    @api.model
    def get_action_picking_tree_incoming(self):
        return self._get_action("stock.action_picking_tree_incoming")

    @api.model
    def get_action_picking_tree_outgoing(self):
        return self._get_action("stock.action_picking_tree_outgoing")

    @api.model
    def get_action_picking_tree_internal(self):
        return self._get_action("stock.action_picking_tree_internal")

    def _get_autoprint_report_actions(self):
        """Collect the report/label actions to auto-print after validation, in a stable
        order. Each `_autoprint_*` helper returns the actions for one report type (or an
        empty list), so report types can be tested and overridden independently.
        """
        return [
            *self._autoprint_delivery_slip(),
            *self._autoprint_return_slip(),
            *self._autoprint_reception_reports(),
            *self._autoprint_product_labels(),
            *self._autoprint_lot_labels(),
            *self._autoprint_package_report(),
        ]

    def _get_impacted_pickings(self, moves):
        """Return all pickings reached by following `moves`' destination moves,
        direct and indirect (used to notify users impacted by a chained move change).
        """

        # Iterative breadth-first walk of the move-destination graph; the `explored`
        # set both dedupes and guards against cycles (no recursion depth limit).
        impacted_pickings = self.env["stock.picking"]
        explored_moves = self.env["stock.move"]
        frontier = moves
        while frontier:
            new_moves = frontier - explored_moves
            impacted_pickings |= new_moves.picking_id
            explored_moves |= new_moves
            frontier = new_moves.move_dest_ids - explored_moves
        return impacted_pickings

    def _get_moves_to_backorder(self):
        self.ensure_one()
        return self.move_ids.filtered(lambda x: x.state not in DONE_CANCEL_STATES)

    def _get_packages_for_print(self):
        package_ids = OrderedSet()
        for picking in self:
            if picking.state == "done":
                package_ids.update(picking.package_history_ids.package_id.ids)
            else:
                package_ids.update(
                    picking.move_line_ids.result_package_id._get_all_package_dest_ids(),
                )
        return self.env["stock.package"].browse(package_ids)

    def _get_report_lang(self):
        # Reports render one picking at a time; `self.partner_id` would raise a
        # singleton error on a multi-record set anyway, so make the contract explicit.
        self.ensure_one()
        return (
            (self.move_ids and self.move_ids[0].partner_id.lang)
            or self.partner_id.lang
            or self.env.lang
        )

    def _get_without_quantities_error_message(self):
        """Error message raised in validation when no quantities are reserved.
        Overridable to adapt the message.

        :return: Translated error message
        :rtype: str
        """
        return _(
            "Transfer trouble alert! Validating a zero quantity transfer? You're not moving invisible goods around are you?\n"
            "Set some quantities and let's get moving!",
        )

    def _less_quantities_than_expected_add_documents(self, moves, documents):
        return documents

    def _log_activity_get_documents(
        self,
        orig_obj_changes,
        stream_field,
        stream,
        groupby_method=False,
    ):
        """Find the (document, responsible) pairs to notify for the given changes, following
        either the upstream ("UP") or downstream ("DOWN") documents, and build a rendering
        context per document containing only the changes relevant to it (e.g. a picking is
        only notified about the moves it actually contains).

        :param dict orig_obj_changes: record -> change on that record, e.g. {move: (new_qty, old_qty)}
        :param str stream_field: field on the `orig_obj_changes` records to follow, e.g. 'move_dest_ids'
        :param str stream: ``'UP'`` (log on the topmost ongoing document) or ``'DOWN'`` (log on
            the following documents)
        :param groupby_method: required when `stream` is 'DOWN'; groups objects by
            (document to log on, responsible for that document)
        """
        if self.env.context.get("skip_activity"):
            return {}
        move_to_orig_object_rel = {
            co: ooc for ooc in orig_obj_changes for co in ooc[stream_field]
        }
        origin_objects = self.env[next(iter(orig_obj_changes))._name].concat(
            *orig_obj_changes,
        )
        # Group each destination object by (document to log, responsible), regardless of
        # stream direction. E.g.:
        # {(delivery_picking_1, admin): stock.move(1, 2),
        #  (delivery_picking_2, admin): stock.move(3)}
        visited_documents = {}
        if stream == "DOWN":
            if groupby_method:
                grouped_moves = groupby(
                    origin_objects.mapped(stream_field),
                    key=groupby_method,
                )
            else:
                raise AssertionError(
                    "You have to define a groupby method and pass them as arguments.",
                )
        elif stream == "UP":
            # Ascending requires `_get_upstream_documents_and_responsibles` to be
            # defined on the destination objects.
            grouped_moves = {}
            for visited_move in origin_objects.mapped(stream_field):
                for (
                    document,
                    responsible,
                    visited,
                ) in visited_move._get_upstream_documents_and_responsibles(
                    self.env[visited_move._name],
                ):
                    if grouped_moves.get((document, responsible)):
                        grouped_moves[document, responsible] |= visited_move
                        visited_documents[document, responsible] |= visited
                    else:
                        grouped_moves[document, responsible] = visited_move
                        visited_documents[document, responsible] = visited
            grouped_moves = grouped_moves.items()
        else:
            raise AssertionError("Unknown stream.")

        documents = {}
        for (parent, responsible), moves in grouped_moves:
            if not parent:
                continue
            moves = self.env[moves[0]._name].concat(*moves)
            rendering_context = {
                move: (orig_object, orig_obj_changes[orig_object])
                for move in moves
                for orig_object in move_to_orig_object_rel[move]
            }
            if visited_documents:
                documents[parent, responsible] = (
                    rendering_context,
                    visited_documents.values(),
                )
            else:
                documents[parent, responsible] = rendering_context
        return documents

    def _log_activity(self, render_method, documents):
        """Schedule a warning activity on each (document, responsible) pair in `documents`,
        with the note rendered by `render_method(rendering_context)`.

        :param dict documents: (document, responsible) -> rendering_context, as returned by
            `_log_activity_get_documents`
        :param callable render_method: rendering_context -> html note string
        """
        for (parent, responsible), rendering_context in documents.items():
            note = render_method(rendering_context)
            parent.sudo().activity_schedule(
                "mail.mail_activity_data_warning",
                date.today(),
                note=note,
                user_id=responsible.id,
            )

    def _log_less_quantities_than_expected(self, moves):
        """Log an activity on the pickings that follow `moves`, noting the quantity changes
        and any picking impacted by them.

        :param dict moves: move -> (new_qty, old_qty)
        """

        def _keys_in_groupby(move):
            """Group by picking and the product's responsible."""
            return (move.picking_id, move.product_id.responsible_id)

        def _render_note_exception_quantity(rendering_context):
            """:param rendering_context: {move_dest: (move_orig, (new_qty, old_qty))}"""
            origin_moves = self.env["stock.move"].browse(
                [
                    move.id
                    for move_orig in rendering_context.values()
                    for move in move_orig[0]
                ],
            )
            origin_picking = origin_moves.mapped("picking_id")
            move_dest_ids = self.env["stock.move"].concat(*rendering_context.keys())
            impacted_pickings = origin_picking._get_impacted_pickings(
                move_dest_ids,
            ) - move_dest_ids.mapped("picking_id")
            values = {
                "origin_picking": origin_picking,
                "moves_information": rendering_context.values(),
                "impacted_pickings": impacted_pickings,
            }
            return self.env["ir.qweb"]._render("stock.exception_on_picking", values)

        documents = self._log_activity_get_documents(
            moves,
            "move_dest_ids",
            "DOWN",
            _keys_in_groupby,
        )
        documents = self._less_quantities_than_expected_add_documents(moves, documents)
        self._log_activity(_render_note_exception_quantity, documents)

    def _prepare_entire_pack_move_line_vals(self, packages):
        """Move line values for each package (and child package) that holds products."""
        self.ensure_one()
        return [
            {
                "product_id": package_quant.product_id.id,
                "quantity": package_quant.quantity,
                "product_uom_id": package_quant.product_uom_id.id,
                "location_id": package_quant.location_id.id,
                "location_dest_id": self.location_dest_id.id,
                "picking_id": self.id,
                "company_id": self.company_id.id,
                "package_id": package_quant.package_id.id,
                "result_package_id": package_quant.package_id.id,
                "lot_id": package_quant.lot_id.id,
                "owner_id": package_quant.owner_id.id,
                "is_entire_pack": True,
            }
            for package_quant in packages.quant_ids
        ]

    def _remove_reference(self, reference):
        """Remove the given references from the list of references."""
        self.ensure_one()
        self.move_ids.reference_ids = [
            Command.unlink(stock_reference.id) for stock_reference in reference
        ]

    def _render_picking_help(self, context=None):
        """Render the picking action-view help banner for the current (restricted)
        picking type. Shared by `get_empty_list_help` and `_get_action`.
        """
        context = self.env.context if context is None else context
        return self.env["ir.ui.view"]._render_template(
            "stock.help_message_template",
            {
                "picking_type_code": context.get("restricted_picking_type_code")
                or self.picking_type_code,
            },
        )

    # ------------------------------------------------------------
    # VALIDATION METHODS
    # ------------------------------------------------------------

    def _can_return(self):
        self.ensure_one()
        return self.state == "done"

    def _check_backorder(self):
        backorder_pickings = self.browse()
        for picking in self:
            if picking.picking_type_id.create_backorder != "ask":
                continue
            # Compare picked vs demand with the move's own UoM rounding (both
            # quantities are expressed in that UoM), rather than the global
            # "Product Unit" decimal precision.
            if any(
                (move.product_uom_qty and not move.picked)
                or move.product_uom_id.compare(
                    move._get_picked_quantity(),
                    move.product_uom_qty,
                )
                < 0
                for move in picking.move_ids
                if move.state != "cancel"
            ):
                backorder_pickings |= picking
        return backorder_pickings

    def _check_entire_pack(self):
        """Detect entire packages being moved and set their move lines' result package
        (and `is_entire_pack`) accordingly, unless the package type is reusable.
        """
        for package, package_move_lines in self.move_line_ids.grouped(
            "package_id"
        ).items():
            if not package:
                continue
            pickings = package_move_lines.picking_id
            if (
                pickings._is_single_transfer()
                and pickings._check_move_lines_map_quant_package(package)
            ):
                move_lines_to_pack = package_move_lines.filtered(
                    lambda ml: (
                        not ml.result_package_id and ml.state not in DONE_CANCEL_STATES
                    ),
                )
                if package.package_type_id.package_use != "reusable":
                    move_lines_to_pack.write(
                        {
                            "result_package_id": package.id,
                            "is_entire_pack": True,
                        },
                    )
        # If all packages within a package move, they keep their container too.
        self.move_line_ids.result_package_id._apply_package_dest_for_entire_packs()

    def _check_move_lines_map_quant_package(self, package):
        return package._check_move_lines_map_quant(
            self.move_line_ids.filtered(
                lambda ml: (
                    ml.product_id.is_storable
                    and (
                        ml.package_id == package
                        or ml.package_id in package.all_children_package_ids
                    )
                ),
            ),
        )

    def _is_single_transfer(self):
        # Overridden in stock.picking.batch: a "single transfer" is a single picking.
        return len(self) == 1

    def _is_to_external_location(self):
        self.ensure_one()
        return self.picking_type_code == "outgoing"

    def _sanity_check(self):
        """Sanity check for `button_validate()`."""
        pickings_without_lots = self.browse()
        products_without_lots = self.env["product.product"]
        pickings_without_moves = self.filtered(
            lambda p: not p.move_ids and not p.move_line_ids,
        )

        pickings_without_quantities = self.env["stock.picking"]
        for picking in self:
            has_pick = any(
                move.picked and move.state not in DONE_CANCEL_STATES
                for move in picking.move_ids
            )
            # A quantity below the move's UoM rounding is effectively zero.
            if all(
                move.product_uom_id.is_zero(move.quantity)
                for move in picking.move_ids.filtered(
                    lambda m, has_pick=has_pick: (
                        m.state not in DONE_CANCEL_STATES and (not has_pick or m.picked)
                    ),
                )
            ):
                pickings_without_quantities |= picking

        pickings_using_lots = self.filtered(
            lambda p: (
                p.picking_type_id.use_create_lots or p.picking_type_id.use_existing_lots
            ),
        )
        if pickings_using_lots:
            lines_to_check = pickings_using_lots._get_lot_move_lines_for_sanity_check()
            for line in lines_to_check:
                if not line.lot_name and not line.lot_id:
                    pickings_without_lots |= line.picking_id
                    products_without_lots |= line.product_id

        if not self._should_show_transfers():
            if pickings_without_moves:
                raise UserError(
                    _(
                        "You can’t validate an empty transfer. Please add some products to move before proceeding.",
                    ),
                )
            if pickings_without_quantities:
                raise UserError(self._get_without_quantities_error_message())
            if pickings_without_lots:
                raise UserError(
                    _(
                        "You need to supply a Lot/Serial number for products %s.",
                        ", ".join(products_without_lots.mapped("display_name")),
                    ),
                )
        else:
            message = ""
            if pickings_without_moves:
                message += _(
                    "Transfers %s: Please add some items to move.",
                    ", ".join(pickings_without_moves.mapped("name")),
                )
            # Draft pickings are exempt here: `button_validate` confirms them and
            # backfills their quantities from the demand *before* re-checking, and
            # the batch flow runs this check pre-confirmation.
            if zero_quantity_pickings := pickings_without_quantities.filtered(
                lambda p: p.state != "draft",
            ):
                message += _(
                    "\n\nTransfers %s: You cannot validate a transfer without any quantities set. Set some quantities before proceeding.",
                    ", ".join(zero_quantity_pickings.mapped("name")),
                )
            if pickings_without_lots:
                message += _(
                    "\n\nTransfers %(transfer_list)s: You need to supply a Lot/Serial number for products %(product_list)s.",
                    transfer_list=", ".join(pickings_without_lots.mapped("name")),
                    product_list=", ".join(
                        products_without_lots.mapped("display_name"),
                    ),
                )
            if message:
                raise UserError(message.lstrip())

    def _should_ignore_backorders(self):
        """Checks if the `create_backorder` setting from the picking type should be ignored.

        Deliberate asymmetry: only the Barcode flow consults this (it forces
        ``create_backorder = "never"`` in its client config), while the backend
        `button_validate` chain does not — a return picking validated from the
        backend still follows its type's backorder setting.
        """
        return bool(self.return_id)

    def should_print_delivery_address(self):
        self.ensure_one()
        return (
            self.move_ids
            and (self.move_ids[0].partner_id or self.partner_id)
            and self._is_to_external_location()
        )

    def _should_show_transfers(self):
        """Whether the different transfers should be displayed on the pre action done wizards."""
        return len(self) > 1
