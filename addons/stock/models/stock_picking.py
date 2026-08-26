import json
import math
from collections import defaultdict

from odoo import api, fields, models
from odoo.db.schema import column_exists
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.tools import OrderedSet, format_date, format_datetime
from odoo.tools.misc import clean_context
from odoo.tools.translate import _

from odoo.addons.stock.models.stock_move import PROCUREMENT_PRIORITIES
from odoo.addons.web.controllers.utils import clean_action

DONE_CANCEL_STATES = frozenset(("done", "cancel"))
DRAFT_DONE_CANCEL_STATES = DONE_CANCEL_STATES | {"draft"}
OPEN_PICKING_STATES = frozenset(("waiting", "confirmed", "assigned"))
UNRESERVED_MOVE_STATES = frozenset(("waiting", "confirmed", "partially_available"))
FORECAST_PICKING_CODES = frozenset(("outgoing", "internal"))
INBOUND_PICKING_CODES = frozenset(("incoming", "internal"))


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = [
        "mixin.mail.thread",
        "mixin.mail.activity",
        "mixin.stock.activity",
        "mixin.date.category",
    ]
    _description = "Transfer"
    _order = "priority desc, date_planned asc, id desc"
    _date_category_field = "date_planned"

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
    return_count = fields.Count("return_ids", string="# Returns", compute_sudo=False)

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
        compute="_compute_has_deadline_issue",
        store=True,
        help="Is late or will be late depending on the deadline and scheduled date",
    )
    date_done = fields.Datetime(
        string="Date of Transfer",
        copy=False,
        help="Date at which the transfer was processed. Cancelling never sets it.",
    )
    date_delay_alert = fields.Datetime(
        string="Delay Alert Date",
        compute="_compute_date_delay_alert",
        store=True,
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
        compute="_compute_location_dest_id",
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
    )
    is_signed = fields.Boolean(
        string="Is Signed",
        compute="_compute_is_signed",
    )
    is_cancelled = fields.Boolean(
        string="Cancelled",
        readonly=True,
        copy=False,
        help="Records that this transfer was cancelled. Its moves express that "
        "while they exist; this is what answers once they are gone.",
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
        compute="_compute_weight_bulk",
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
    partner_country_id = fields.Many2one(
        related="partner_id.country_id",
        comodel_name="res.country",
    )
    picking_warning_text = fields.Text(
        string="Picking Instructions",
        compute="_compute_picking_warning_text",
        help="Internal instructions for the partner or its parent company as set by the user.",
    )

    _name_uniq = models.Constraint(
        "unique(name, company_id)",
        "Reference must be unique per company!",
    )

    def _auto_init(self):
        fresh_column = not column_exists(self.env.cr, "stock_picking", "is_cancelled")
        res = super()._auto_init()
        if fresh_column:
            self.env.cr.execute(
                "UPDATE stock_picking SET is_cancelled = true WHERE state = 'cancel'"
            )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["name", "picking_type_id"])
        default_name = defaults.get("name", "/")
        default_picking_type_id = defaults.get("picking_type_id")
        vals_list = [dict(vals) for vals in vals_list]
        type_ids = {
            vals.get("picking_type_id", default_picking_type_id) for vals in vals_list
        }
        type_ids.discard(False)
        self.env["stock.picking.type"].browse(type_ids).fetch(["sequence_id"])
        for vals in vals_list:
            picking_type_id = vals.get("picking_type_id", default_picking_type_id)
            if not picking_type_id or vals.get("name", "/") != "/":
                continue
            if len(vals_list) == 1 and default_name != "/":
                continue
            picking_type = self.env["stock.picking.type"].browse(picking_type_id)
            if picking_type.sequence_id:
                vals["name"] = picking_type.sequence_id.next_by_id()

        date_planneds = [vals.pop("date_planned", False) for vals in vals_list]

        pickings = super().create(vals_list)

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
            picking_type = self.env["stock.picking.type"].browse(
                vals["picking_type_id"],
            )
            pickings_changing_type = self.filtered(
                lambda picking: picking.picking_type_id != picking_type,
            )
            if any(
                picking.state in DONE_CANCEL_STATES
                for picking in pickings_changing_type
            ):
                raise UserError(
                    _(
                        "Changing the operation type of this record is forbidden at this point.",
                    ),
                )
            if pickings_changing_type and picking_type.sequence_id:
                for picking in pickings_changing_type:
                    picking.name = picking_type.sequence_id.next_by_id()

        locations_before = {
            picking.id: (picking.location_id, picking.location_dest_id)
            for picking in self
        }

        res = super().write(vals)

        self._propagate_locations_to_moves(locations_before)

        if vals.get("date_done"):
            self.filtered(lambda p: p.state == "done").move_ids.filtered(
                lambda move: (
                    move.state == "done" and move.location_dest_usage != "inventory"
                ),
            ).date = vals["date_done"]
        if vals.get("signature"):
            for picking in self:
                picking._attach_sign()
        if vals.get("move_ids"):
            self._autoconfirm_picking()

        return res

    def _propagate_locations_to_moves(self, locations_before):
        moves_by_location_vals = defaultdict(lambda: self.env["stock.move"])
        for picking in self:
            before = locations_before.get(picking.id)
            if before is None:
                continue
            location_vals = {}
            if picking.location_id != before[0]:
                location_vals["location_id"] = picking.location_id.id
            if picking.location_dest_id != before[1]:
                location_vals["location_dest_id"] = picking.location_dest_id.id
            if not location_vals:
                continue
            moves_by_location_vals[tuple(location_vals.items())] |= (
                picking.move_ids.filtered(
                    lambda move: (
                        move.state not in DONE_CANCEL_STATES
                        and move.location_dest_usage != "inventory"
                    ),
                )
            )
        for location_vals, moves in moves_by_location_vals.items():
            if moves:
                moves.write(dict(location_vals))

    def unlink(self):
        self.move_ids._action_cancel()
        self.with_context(
            prefetch_fields=False,
        ).move_ids.unlink()
        return super().unlink()

    def _default_picking_type_id(self):
        picking_type_code = self.env.context.get("restricted_picking_type_code")
        if not picking_type_code:
            return False
        picking_type = self.env["stock.picking.type"].search(
            [
                ("code", "=", picking_type_code),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        return picking_type.id

    @api.depends("move_ids.has_tracking")
    def _compute_has_tracking(self):
        for picking in self:
            picking.has_tracking = any(
                m.has_tracking != "none" for m in picking.move_ids
            )

    @api.depends("state", "is_locked")
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
            picking.has_deadline_issue = bool(
                picking.date_deadline
                and picking.date_planned
                and picking.date_deadline < picking.date_planned
            )

    @api.depends("move_ids.date_delay_alert")
    def _compute_date_delay_alert(self):
        saved = self.filtered("id")
        date_delay_alert_by_picking = {}
        if saved:
            date_delay_alert_by_picking = {
                picking.id: date_delay_alert
                for picking, date_delay_alert in self.env["stock.move"]._read_group(
                    [
                        ("picking_id", "in", saved.ids),
                        ("date_delay_alert", "!=", False),
                    ],
                    ["picking_id"],
                    ["date_delay_alert:max"],
                )
            }
        for picking in self:
            if picking.id:
                picking.date_delay_alert = date_delay_alert_by_picking.get(
                    picking.id, False
                )
            else:
                picking.date_delay_alert = max(
                    picking.move_ids.filtered("date_delay_alert").mapped(
                        "date_delay_alert"
                    ),
                    default=False,
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
    @api.depends_context("lang")
    def _compute_products_availability(self):
        pickings = self.filtered(
            lambda picking: (
                picking.state in OPEN_PICKING_STATES
                and picking.picking_type_code in FORECAST_PICKING_CODES
            ),
        )
        pickings.products_availability_state = "available"
        pickings.products_availability = _("Available")
        other_pickings = self - pickings
        other_pickings.products_availability = False
        other_pickings.products_availability_state = False

        all_moves = pickings.move_ids
        all_moves._fields["forecast_availability"].compute_value(all_moves)
        for picking in pickings:
            state, forecast_date = picking.move_ids._get_availability(
                picking.date_planned,
            )
            picking.products_availability_state = state
            if forecast_date:
                picking.products_availability = _(
                    "Exp %s",
                    format_date(self.env, forecast_date),
                )
            elif state == "late":
                picking.products_availability = _("Not Available")

    @api.depends(
        "picking_type_id.use_create_lots",
        "picking_type_id.use_existing_lots",
        "state",
    )
    @api.depends_context("uid")
    def _compute_show_lots_text(self):
        group_production_lot_enabled = self.env.user.has_group(
            "stock.group_production_lot",
        )
        for picking in self:
            picking.show_lots_text = bool(
                group_production_lot_enabled
                and picking.picking_type_id.use_create_lots
                and not picking.picking_type_id.use_existing_lots
                and picking.state != "done"
            )

    @api.depends("state", "date_delay_alert", "move_ids.date_delay_alert")
    @api.depends_context("lang", "tz")
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

    @api.depends(
        "move_type",
        "move_ids.state",
        "move_ids.picking_id",
        "move_ids.procure_method",
        "location_id",
        "is_cancelled",
    )
    def _compute_state(self):
        real_pickings = self.filtered("id")
        move_ids_by_picking = defaultdict(list)
        if real_pickings:
            for move in self.env["stock.move"].search(
                [("picking_id", "in", real_pickings.ids)]
            ):
                move_ids_by_picking[move.picking_id.id].append(move.id)

        for picking in self:
            if picking.id:
                moves = self.env["stock.move"].browse(
                    move_ids_by_picking.get(picking.id, ()),
                )
            else:
                moves = picking.move_ids
            move_states = set(moves.mapped("state"))

            if not moves:
                picking.state = "cancel" if picking.is_cancelled else "draft"
            elif "draft" in move_states:
                picking.state = "draft"
            elif move_states == {"cancel"}:
                picking.state = "cancel"
            elif move_states <= DONE_CANCEL_STATES:
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
            picking.date_planned = picking._get_date_planned_from_moves()

    def _get_date_planned_from_moves(self):
        self.ensure_one()
        moves_dates = self.move_ids.filtered(
            lambda move: move.state not in DONE_CANCEL_STATES,
        ).mapped("date")
        fallback = self.date_planned or fields.Datetime.now()
        if self.move_type == "direct":
            return min(moves_dates, default=fallback)
        return max(moves_dates, default=fallback)

    def _measure_total_by_picking(self, extra_domain, product_attr, lines_field):
        totals = defaultdict(float)
        saved = self.filtered("id")
        if saved:
            res_groups = self[lines_field]._read_group(
                [
                    ("picking_id", "in", saved.ids),
                    ("product_id", "!=", False),
                    *extra_domain,
                ],
                ["picking_id", "product_id", "product_uom_id"],
                ["quantity:sum"],
            )
            for picking, product, product_uom_id, quantity in res_groups:
                totals[picking.id] += product_uom_id._compute_quantity(
                    quantity, product.uom_id
                ) * getattr(product, product_attr)
        for picking in self - saved:
            quantity_by_group = defaultdict(float)
            for line in picking[lines_field].filtered_domain(
                [("product_id", "!=", False), *extra_domain],
            ):
                quantity_by_group[line.product_id, line.product_uom_id] += line.quantity
            for (product, product_uom_id), quantity in quantity_by_group.items():
                totals[picking.id] += product_uom_id._compute_quantity(
                    quantity, product.uom_id
                ) * getattr(product, product_attr)
        return totals

    @api.depends(
        "move_line_ids",
        "move_line_ids.result_package_id",
        "move_line_ids.product_uom_id",
        "move_line_ids.quantity",
        "move_line_ids.product_id.weight",
    )
    def _compute_weight_bulk(self):
        weights = self._measure_total_by_picking(
            [("result_package_id", "=", False)],
            "weight",
            "move_line_ids",
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
        packages_by_picking = {
            picking: picking.move_line_ids.result_package_id.outermost_package_id
            for picking in self
        }
        all_packages = self.env["stock.package"].union(*packages_by_picking.values())
        packages_weight = (
            all_packages.sudo()._get_weight_by_picking(self.ids) if all_packages else {}
        )
        for picking in self:
            shipping_weight = picking.weight_bulk
            for package in packages_by_picking[picking]:
                if package.shipping_weight:
                    shipping_weight += package.shipping_weight
                else:
                    shipping_weight += packages_weight.get((package, picking.id), 0)
            picking.shipping_weight = shipping_weight

    @api.depends(
        "move_ids.quantity",
        "move_ids.product_uom_id",
        "move_ids.product_id.volume",
    )
    def _compute_shipping_volume(self):
        volumes = self._measure_total_by_picking(
            [],
            "volume",
            "move_ids",
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

    @api.depends(
        "state",
        "move_ids.state",
        "move_ids.picked",
        "move_ids.quantity",
        "move_ids.product_uom_qty",
    )
    def _compute_show_check_availability(self):
        for picking in self:
            if picking.state not in OPEN_PICKING_STATES:
                picking.show_check_availability = False
                continue
            if all(
                m.picked or m.product_uom_id.compare(m.product_uom_qty, m.quantity) == 0
                for m in picking.move_ids
            ):
                picking.show_check_availability = False
                continue
            picking.show_check_availability = any(
                move.state in UNRESERVED_MOVE_STATES
                and move.product_uom_id.compare(move.product_uom_qty, 0) > 0
                for move in picking.move_ids
            )

    @api.depends("state", "move_ids", "picking_type_id")
    @api.depends_context("uid")
    def _compute_show_allocation(self):
        self.show_allocation = False
        if not self.env.user.has_group("stock.group_reception_report"):
            return
        show_by_picking = self._get_show_allocation_map()
        for picking in self:
            picking.show_allocation = show_by_picking.get(picking, False)

    def _get_allocatable_demand_lines(self):
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
        return lines_by_picking

    def _has_allocatable_demand(self, lines, excluded_ids, candidates_by_product):
        self.ensure_one()
        line_ids = set(lines.ids)
        return any(
            move.picking_id.id not in excluded_ids
            and (
                not move.move_orig_ids
                or not line_ids.isdisjoint(move.move_orig_ids.ids)
            )
            for product_id in set(lines.product_id.ids)
            for move in candidates_by_product.get(product_id, ())
        )

    def _get_allocatable_demand_candidates(
        self, view_location, include_assigned, lines
    ):
        Move = self.env["stock.move"]
        candidates = Move.search(
            Move._get_allocatable_demand_domain(
                self.env["stock.location"]._get_allocation_source_ids(
                    view_location.ids,
                ),
                lines.product_id.ids,
                include_assigned=include_assigned,
            ),
        )
        candidates_by_product = defaultdict(list)
        for move in candidates:
            candidates_by_product[move.product_id.id].append(move)
        return candidates_by_product

    def _get_show_allocation_map(self, excluded_pickings=None, stop_at_first=False):
        result = dict.fromkeys(self, False)
        base_excluded_ids = set(excluded_pickings.ids) if excluded_pickings else set()
        lines_by_picking = self._get_allocatable_demand_lines()
        batches = defaultdict(dict)
        for picking, lines in lines_by_picking.items():
            key = (
                picking.picking_type_id.warehouse_id.view_location_id,
                picking.state == "done",
            )
            batches[key][picking] = lines
        for (view_location, include_assigned), members in batches.items():
            candidates_by_product = self._get_allocatable_demand_candidates(
                view_location,
                include_assigned,
                self.env["stock.move"].union(*members.values()),
            )
            if not candidates_by_product:
                continue
            for picking, lines in members.items():
                excluded_ids = base_excluded_ids | {picking._origin.id}
                excluded_ids.discard(False)
                result[picking] = picking._has_allocatable_demand(
                    lines,
                    excluded_ids,
                    candidates_by_product,
                )
                if stop_at_first and result[picking]:
                    return result
        return result

    @api.depends("picking_type_id", "partner_id")
    def _compute_location_id(self):
        for picking in self:
            if picking.location_id and (
                picking.state in DONE_CANCEL_STATES or picking.return_id
            ):
                continue
            if picking.picking_type_id:
                picking.location_id = picking._get_type_default_location_id()

    @api.depends("picking_type_id", "partner_id")
    def _compute_location_dest_id(self):
        for picking in self:
            if picking.location_dest_id and (
                picking.state in DONE_CANCEL_STATES or picking.return_id
            ):
                continue
            if picking.picking_type_id:
                picking.location_dest_id = picking._get_type_default_location_dest_id()

    def _get_type_default_location_id(self):
        self.ensure_one()
        picking = self.with_company(self.company_id)
        location = picking.picking_type_id.default_location_src_id
        if location.usage == "supplier" and picking.partner_id:
            location = picking.partner_id.property_stock_supplier
        return location.id

    def _get_type_default_location_dest_id(self):
        self.ensure_one()
        picking = self.with_company(self.company_id)
        location = picking.picking_type_id.default_location_dest_id
        if location.usage == "customer" and picking.partner_id:
            location = picking.partner_id.property_stock_customer
        return location.id

    @api.depends(
        "partner_id.picking_warn_msg",
        "partner_id.parent_id.picking_warn_msg",
    )
    @api.depends_context("uid")
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
        self.mapped("move_ids.move_dest_ids.picking_id")
        for picking in self:
            next_pickings = picking.move_ids.move_dest_ids.picking_id
            picking.show_next_pickings = bool(next_pickings - picking.return_ids)

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

    def _inverse_date_planned(self):
        for picking in self:
            if picking.state == "cancel":
                raise UserError(
                    _("You cannot change the Scheduled Date on a cancelled transfer."),
                )
            if picking.state == "done":
                continue
            if picking.date_planned == picking._get_date_planned_from_moves():
                continue
            picking.move_ids.filtered(
                lambda move: move.state not in DONE_CANCEL_STATES,
            ).write({"date": picking.date_planned})

    def _search_products_availability_state(self, operator, value):
        if operator != "in":
            return NotImplemented

        value = set(value)
        qualifying = Domain(
            [
                ("state", "in", tuple(OPEN_PICKING_STATES)),
                ("picking_type_id.code", "in", tuple(FORECAST_PICKING_CODES)),
            ],
        )
        if False in value:
            return ~qualifying | self._search_products_availability_state(
                "in",
                value - {False},
            )
        all_states = set(
            self._fields["products_availability_state"].get_values(self.env)
        )
        value = all_states & value
        if not value:
            return Domain.FALSE
        if value == all_states:
            return qualifying

        def _filter_picking_moves(picking):
            try:
                return picking.move_ids._match_searched_availability(
                    operator,
                    value,
                    picking.date_planned,
                )
            except UserError:
                return False

        candidate_pickings = self.env["stock.picking"].search(qualifying, order="id")
        candidate_moves = candidate_pickings.move_ids
        candidate_moves._fields["forecast_availability"].compute_value(candidate_moves)
        pickings = candidate_pickings.filtered(_filter_picking_moves)
        return Domain("id", "in", pickings.ids)

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

    def do_print_picking(self):
        self.write({"printed": True})
        return self.env.ref("stock.action_report_picking").report_action(self)

    def action_confirm(self):
        self._check_company()
        self.move_ids.filtered(lambda move: move.state == "draft")._action_confirm()

        self.move_ids.filtered(
            lambda move: move.state not in DRAFT_DONE_CANCEL_STATES,
        )._trigger_scheduler()
        return True

    def action_assign(self):
        self.filtered(lambda picking: picking.state == "draft").action_confirm()
        moves = self.move_ids.filtered(
            lambda move: move.state not in DRAFT_DONE_CANCEL_STATES,
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
        moveless = self.filtered(lambda picking: not picking.move_ids)
        cancelled = (self - moveless).filtered(
            lambda picking: picking.state == "cancel",
        )
        (moveless | cancelled).is_cancelled = True
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
        return self._get_pickings_action(
            self._get_next_transfers(), _("Next Transfers")
        )

    def _action_done(self):
        self._check_company()

        todo_moves = self.move_ids.filtered(
            lambda move: move.state not in DONE_CANCEL_STATES,
        )
        for owner, pickings in self.filtered("owner_id").grouped("owner_id").items():
            owner_moves = todo_moves.filtered(
                lambda move, pickings=pickings: move.picking_id in pickings,
            )
            owner_moves.write({"restrict_partner_id": owner.id})
            owner_moves.move_line_ids.write({"owner_id": owner.id})
        todo_moves._action_done(
            cancel_backorder=self.env.context.get("cancel_backorder"),
        )
        self.filtered(lambda picking: picking.state == "done").write(
            {"date_done": fields.Datetime.now(), "priority": "0"},
        )

        done_incoming_moves = self.filtered(
            lambda p: p.picking_type_id.code in INBOUND_PICKING_CODES,
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
        return True

    def button_validate(self):
        self = self.filtered(lambda p: p.state not in DONE_CANCEL_STATES)
        draft_picking = self.filtered(lambda p: p.state == "draft")
        draft_picking.action_confirm()
        moves_by_quantity = defaultdict(lambda: self.env["stock.move"])
        for move in draft_picking.move_ids:
            if move.product_uom_id.is_zero(
                move.quantity
            ) and not move.product_uom_id.is_zero(
                move.product_uom_qty,
            ):
                moves_by_quantity[move.product_uom_qty] |= move
        for quantity, moves in moves_by_quantity.items():
            moves.write({"quantity": quantity})

        if not self.env.context.get("skip_sanity_check", False):
            self._sanity_check()

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
        not_to_backorder = self.filtered(
            lambda p: p.picking_type_id.create_backorder == "never",
        )
        if self.env.context.get("picking_ids_not_to_backorder"):
            not_to_backorder |= (
                self.browse(self.env.context["picking_ids_not_to_backorder"]) & self
            ).filtered(lambda p: p.picking_type_id.create_backorder != "always")
        return self - not_to_backorder, not_to_backorder

    def _get_reception_report_action(self):
        if not self.env.user.has_group("stock.group_reception_report"):
            return False
        pickings_show_report = self.filtered(
            lambda p: p.picking_type_id.auto_show_reception_report,
        )
        Move = self.env["stock.move"]
        has_allocatable_demand = False
        for warehouse, pickings in pickings_show_report.grouped(
            lambda p: p.picking_type_id.warehouse_id,
        ).items():
            lines = pickings.move_ids.filtered(
                lambda m: (
                    m.product_id.is_storable
                    and m.state != "cancel"
                    and m.quantity
                    and not m.move_dest_ids
                ),
            )
            if not lines:
                continue
            wh_location_ids = self.env["stock.location"]._get_allocation_source_ids(
                warehouse.view_location_id.ids,
            )
            if Move.search_count(
                [
                    *Move._get_allocatable_demand_domain(
                        wh_location_ids,
                        lines.product_id.ids,
                    ),
                    ("move_orig_ids", "=", False),
                    ("picking_id", "not in", pickings_show_report.ids),
                ],
                limit=1,
            ):
                has_allocatable_demand = True
                break
        if not has_allocatable_demand:
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

        open_moves = self.move_ids.filtered(
            lambda m: m.state not in DONE_CANCEL_STATES,
        )
        moves = open_moves.filtered(
            lambda m: not m.product_uom_id.is_zero(m.quantity),
        )
        backorder_moves = moves._create_backorder()
        backorder_moves += open_moves.filtered(
            lambda m: m.product_uom_id.is_zero(m.quantity),
        )
        self._create_backorder(backorder_moves=backorder_moves)

    def _get_pickings_to_autopick(self):
        to_autopick = self.browse()
        for picking in self:
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
                to_autopick |= picking
        return to_autopick

    def _pre_action_done_hook(self):
        self._get_pickings_to_autopick().move_ids.picked = True
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
            self.move_line_ids.filtered(
                lambda ml: ml.package_id.id in all_package_ids,
            ).unlink()
            move_line_vals = self._prepare_entire_pack_move_line_vals(all_packages)
            pack_move_lines = self.env["stock.move.line"].create(move_line_vals)
            pack_move_lines._apply_putaway_strategy()
            self.move_line_ids.result_package_id._apply_package_dest_for_entire_packs(
                allowed_package_ids=all_package_ids,
            )
            return True
        return False

    def action_view_move_scrap(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("stock.action_stock_scrap")
        action["domain"] = [("picking_id", "=", self.id)]
        action["context"] = dict(self.env.context, create=False)
        return action

    def action_view_packages(self):
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
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("stock.stock_move_action")
        action["views"] = [
            (self.env.ref("stock.view_stock_move_list_picking").id, "list"),
        ]
        action["context"] = self.env.context
        action["domain"] = [("picking_id", "in", self.ids)]
        return action

    def action_view_reception_report(self):
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
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
        return self._get_pickings_action(self.return_ids, _("Returns"))

    @api.model
    def _get_pickings_action(self, pickings, name):
        if len(pickings) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "views": [[False, "form"]],
                "res_id": pickings.id,
            }
        return {
            "name": name,
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", pickings.ids)],
        }

    def _add_reference(self, reference):
        self.ensure_one()
        self.move_ids.reference_ids = [
            Command.link(stock_reference.id) for stock_reference in reference
        ]

    def _attach_sign(self):
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
        open_pickings = self.filtered(
            lambda picking: picking.state not in DONE_CANCEL_STATES,
        )
        pickings_with_additional_moves = open_pickings.filtered(
            lambda picking: any(move.additional for move in picking.move_ids),
        )
        if pickings_with_additional_moves:
            pickings_with_additional_moves.action_confirm()
        to_confirm = open_pickings.move_ids.filtered(
            lambda m: m.state == "draft" and m.quantity,
        )
        to_confirm._action_confirm()

    def _autoprint_action(self, report_xmlid, records, data=None):
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

    def _prepare_backorder_picking_vals(self):
        self.ensure_one()
        return self.copy_data(
            {
                "name": "/",
                "move_ids": [],
                "move_line_ids": [],
                "backorder_id": self.id,
                "return_id": self.return_id.id,
            },
        )[0]

    def _post_create_backorder(self, backorder):
        pass

    def _create_backorder(self, backorder_moves=None):
        moves_by_picking = {}
        for picking in self:
            if backorder_moves:
                moves_to_backorder = backorder_moves.filtered(
                    lambda m, picking=picking: m.picking_id == picking,
                )
            else:
                moves_to_backorder = picking._get_moves_to_backorder()
            if moves_to_backorder:
                moves_by_picking[picking] = moves_to_backorder
        if not moves_by_picking:
            return self.browse()

        sources = self.browse([picking.id for picking in moves_by_picking])
        backorders = self.create(
            [picking._prepare_backorder_picking_vals() for picking in sources],
        )

        bo_to_assign = self.browse()
        all_moves_to_backorder = self.env["stock.move"]
        for picking, backorder_picking in zip(sources, backorders, strict=True):
            picking._post_create_backorder(backorder_picking)
            moves_to_backorder = moves_by_picking[picking]
            moves_to_backorder.write(
                {"picking_id": backorder_picking.id, "picked": False},
            )
            moves_to_backorder.move_line_ids.write(
                {"picking_id": backorder_picking.id},
            )
            all_moves_to_backorder |= moves_to_backorder
            picking.message_post(
                body=_(
                    "The backorder %s has been created.",
                    backorder_picking._get_html_link(),
                ),
            )
            if backorder_picking.picking_type_id.reservation_method == "at_confirm":
                bo_to_assign |= backorder_picking
        backorders.user_id = False
        all_moves_to_backorder._recompute_state()
        if bo_to_assign:
            bo_to_assign.action_assign()
        return backorders

    def _get_next_transfers(self):
        return self.move_ids.move_dest_ids.picking_id - self.return_ids

    @api.model
    def _get_allocation_allowed_move_states(self, include_assigned=False):
        states = ["confirmed", "partially_available", "waiting"]
        if include_assigned:
            states.append("assigned")
        return states

    def _get_allocatable_demand_domain(self, location_ids, product_ids):
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
        if not picking_type_id or picking_type_id.code == "outgoing":
            return False
        return any(
            self._get_show_allocation_map(
                excluded_pickings=self,
                stop_at_first=True,
            ).values(),
        )

    @api.model
    def get_empty_list_help(self, help_message):
        if not self.env.context.get("restricted_picking_type_code"):
            return super().get_empty_list_help(help_message)
        return self._render_picking_help()

    def _get_lot_move_lines_for_sanity_check(self):
        autopicked = self._get_pickings_to_autopick()
        return self.move_line_ids.filtered(
            lambda ml: (
                ml.product_id
                and ml.product_id.tracking != "none"
                and (ml.picked or ml.picking_id in autopicked)
                and ml.product_uom_id.compare(ml.quantity, 0)
            ),
        )

    @api.model
    def get_action_click_graph(self):
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_picking_tree_graph",
        )

    @api.model
    def action_view_pickings_incoming(self):
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_picking_tree_incoming",
        )

    @api.model
    def action_view_pickings_outgoing(self):
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_picking_tree_outgoing",
        )

    @api.model
    def action_view_pickings_internal(self):
        return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "stock.action_picking_tree_internal",
        )

    def _get_autoprint_report_actions(self):
        return [
            *self._autoprint_delivery_slip(),
            *self._autoprint_return_slip(),
            *self._autoprint_reception_reports(),
            *self._autoprint_product_labels(),
            *self._autoprint_lot_labels(),
            *self._autoprint_package_report(),
        ]

    def _get_impacted_pickings(self, moves):
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
        self.ensure_one()
        return (
            (self.move_ids and self.move_ids[0].partner_id.lang)
            or self.partner_id.lang
            or self.env.lang
        )

    def _get_without_quantities_error_message(self):
        return _(
            "Transfer trouble alert! Validating a zero quantity transfer? You're not moving invisible goods around are you?\n"
            "Set some quantities and let's get moving!",
        )

    def _less_quantities_than_expected_add_documents(self, moves, documents):
        return documents

    def _log_less_quantities_than_expected(self, moves):
        def _keys_in_groupby(move):
            return (move.picking_id, move.product_id.responsible_id)

        def _render_note_exception_quantity(rendering_context):
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
        self.ensure_one()
        self.move_ids.reference_ids = [
            Command.unlink(stock_reference.id) for stock_reference in reference
        ]

    def _render_picking_help(self):
        return self.env["ir.ui.view"]._render_template(
            "stock.help_message_template",
            {
                "picking_type_code": self.env.context.get(
                    "restricted_picking_type_code"
                )
                or self.picking_type_code,
            },
        )

    def _can_return(self):
        self.ensure_one()
        return self.state == "done"

    def _check_backorder(self):
        backorder_pickings = self.browse()
        for picking in self:
            if picking.picking_type_id.create_backorder != "ask":
                continue
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
        return len(self) == 1

    def _is_to_external_location(self):
        self.ensure_one()
        return self.picking_type_code == "outgoing"

    def _sanity_check(self):
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
        return bool(self.return_id)

    def should_print_delivery_address(self):
        self.ensure_one()
        return (
            self.move_ids
            and (self.move_ids[0].partner_id or self.partner_id)
            and self._is_to_external_location()
        )

    def _should_show_transfers(self):
        return len(self) > 1
