import itertools
import logging
import typing
from ast import literal_eval
from collections import defaultdict
from datetime import timedelta
from re import fullmatch as regex_fullmatch

from odoo import api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.numbers import float_round
from odoo.tools.misc import OrderedSet, clean_context, groupby
from odoo.tools.translate import _

from ..const import (
    INVENTORY_REFERENCE_CONFIRMED,
    INVENTORY_REFERENCE_UPDATED,
)
from odoo.addons.stock.tools.reservation import ReservationLedger

_logger = logging.getLogger(__name__)

PROCUREMENT_PRIORITIES = [("0", "Normal"), ("1", "Urgent")]

GENERATED_LOT_VALS_MAX = 10000


class _ReservationOutcome(typing.NamedTuple):
    state: str = ""
    redirect: bool = False
    reserved: bool = True


class StockMove(models.Model):
    _name = "stock.move"
    _description = "Stock Move"
    _order = "sequence, id"
    _rec_name = "reference"

    _MAX_PUSH_DEPTH = 50
    _MAX_UPSTREAM_DEPTH = 100

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
        check_company=True,
        index=True,
    )
    picking_code = fields.Selection(
        related="picking_id.picking_type_id.code",
        readonly=True,
    )
    picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation Type",
        compute="_compute_picking_type_id",
        store=True,
        readonly=False,
        check_company=True,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        help="the warehouse to consider for the route selection on the next procurement (if any).",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Destination Address ",
        compute="_compute_partner_id",
        store=True,
        readonly=False,
        index="btree_not_null",
        help="Optional address where goods are to be delivered, specifically used for allotment",
    )
    origin_returned_move_id = fields.Many2one(
        comodel_name="stock.move",
        string="Origin return move",
        check_company=True,
        copy=False,
        index=True,
        help="Move that created the return move",
    )
    returned_move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="origin_returned_move_id",
        string="All returned moves",
        help="Optional: all returned moves created from this move",
    )
    sequence = fields.Integer("Sequence", default=10)
    priority = fields.Selection(
        selection=PROCUREMENT_PRIORITIES,
        string="Priority",
        default="0",
        compute="_compute_priority",
        store=True,
    )
    origin = fields.Char("Source Document")
    date = fields.Datetime(
        string="Date Scheduled",
        required=True,
        default=fields.Datetime.now,
        index=True,
        help="Scheduled date until move is done, then date of actual move processing",
    )
    date_deadline = fields.Datetime(
        string="Deadline",
        readonly=True,
        copy=False,
        help="In case of outgoing flow, validate the transfer before this date to allow to deliver at promised date to the customer.\n\
        In case of incoming flow, validate the transfer before this date in order to have these products in stock at the date promised by the supplier",
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
        index=True,
        bypass_search_access=True,
        help="The operation takes and suggests products from this location.",
    )
    location_usage = fields.Selection(
        related="location_id.usage",
        string="Source Location Type",
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Intermediate Location",
        required=True,
        readonly=False,
        index=True,
        store=True,
        compute="_compute_location_dest_id",
        precompute=True,
        inverse="_inverse_location_dest_id",
        help="The operations brings product to this location",
    )
    location_dest_usage = fields.Selection(
        related="location_dest_id.usage",
        string="Destination Location Type",
    )
    location_final_id = fields.Many2one(
        comodel_name="stock.location",
        string="Final Location",
        readonly=False,
        store=True,
        check_company=True,
        bypass_search_access=True,
        index=True,
        help="The operation brings the products to the intermediate location."
        "But this operation is part of a chain of operations targeting the final location.",
    )
    procure_method = fields.Selection(
        selection=[
            ("make_to_stock", "Default: Take From Stock"),
            ("make_to_order", "Advanced: Apply Procurement Rules"),
        ],
        string="Supply Method",
        required=True,
        default="make_to_stock",
        copy=False,
        help="By default, the system will take from the stock in the source location and passively wait for availability. "
        "The other possibility allows you to directly create a procurement on the source location (and thus ignore "
        "its current stock) to gather products. If we want to chain moves and have this one to wait for the previous, "
        "this second option should be chosen.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "New"),
            ("waiting", "Waiting Another Move"),
            ("confirmed", "Waiting"),
            ("partially_available", "Partially Available"),
            ("assigned", "Available"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        readonly=True,
        copy=False,
        index=True,
        help="* New: The stock move is created but not confirmed.\n"
        "* Waiting Another Move: A linked stock move should be done before this one.\n"
        "* Waiting: The stock move is confirmed but the product can't be reserved.\n"
        "* Available: The product of the stock move is reserved.\n"
        "* Done: The product has been transferred and the transfer has been confirmed.",
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
        domain="[('type', '=', 'consu')]",
        index=True,
    )
    has_tracking = fields.Selection(
        related="product_id.tracking",
        string="Product with Tracking",
    )
    is_storable = fields.Boolean(
        related="product_id.is_storable",
    )
    product_category_id = fields.Many2one(
        related="product_id.categ_id",
        comodel_name="product.category",
        string="Product Category",
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id",
        comodel_name="product.template",
        string="Product Template",
        store=True,
    )
    never_product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        "template_attribute_value_stock_move_rel",
        "move_id",
        "template_attribute_value_id",
        string="Never attribute Values",
    )
    allowed_uom_ids = fields.Many2many(
        comodel_name="uom.uom",
        compute="_compute_allowed_uom_ids",
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        required=True,
        compute="_compute_product_uom_id",
        store=True,
        precompute=True,
        readonly=False,
        domain="[('id', 'in', allowed_uom_ids)]",
    )
    product_uom_qty = fields.Float(
        string="Demand",
        digits="Product Unit",
        default=0,
        required=True,
        help="This is the quantity of product that is planned to be moved."
        "Lowering this quantity does not generate a backorder."
        "Changing this quantity on assigned moves affects "
        "the product reservation, and should be done with care.",
    )
    product_qty = fields.Float(
        string="Real Quantity",
        digits=0,
        compute="_compute_product_qty",
        compute_sudo=True,
        store=True,
        inverse="_inverse_product_qty",
        help="Quantity in the default UoM of the product",
    )
    description_picking_manual = fields.Text(readonly=True)
    description_picking = fields.Text(
        string="Description Of Picking",
        compute="_compute_description_picking",
        inverse="_inverse_description_picking",
        compute_sudo=True,
    )
    move_orig_ids = fields.Many2many(
        "stock.move",
        "stock_move_move_rel",
        "move_dest_id",
        "move_orig_id",
        "Original Move",
        copy=False,
        help="Optional: previous stock move when chaining them",
    )
    move_dest_ids = fields.Many2many(
        "stock.move",
        "stock_move_move_rel",
        "move_orig_id",
        "move_dest_id",
        "Destination Moves",
        copy=False,
        help="Optional: next stock move when chaining them",
    )

    price_unit = fields.Float("Unit Price", copy=False)
    scrap_id = fields.Many2one(
        comodel_name="stock.scrap",
        string="Scrap operation",
        readonly=True,
        check_company=True,
        index="btree_not_null",
    )
    reference_ids = fields.Many2many(
        "stock.reference",
        "stock_reference_move_rel",
        "move_id",
        "reference_id",
        string="References",
    )
    rule_id = fields.Many2one(
        comodel_name="stock.rule",
        string="Stock Rule",
        check_company=True,
        ondelete="restrict",
        help="The stock rule that created this stock move",
    )
    propagate_cancel = fields.Boolean(
        string="Propagate cancel and split",
        default=True,
        help="If checked, when this move is cancelled, cancel the linked move too",
    )
    date_delay_alert = fields.Datetime(
        string="Delay Alert Date",
        compute="_compute_date_delay_alert",
        store=True,
        help="Process at this date to be on time",
    )
    is_inventory = fields.Boolean("Inventory")
    inventory_name = fields.Char(readonly=True)

    move_line_ids = fields.One2many("stock.move.line", "move_id")
    package_ids = fields.One2many(
        comodel_name="stock.package",
        string="Packages",
        compute="_compute_package_ids",
    )
    restrict_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Owner ",
        check_company=True,
        index="btree_not_null",
    )
    route_ids = fields.Many2many(
        "stock.route",
        "stock_route_move",
        "move_id",
        "route_id",
        "Destination route",
        help="Preferred route",
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        compute="_compute_quantity",
        store=True,
        inverse="_inverse_quantity",
    )
    reference = fields.Char(
        string="Reference",
        compute="_compute_reference",
        store=True,
    )
    has_partial_result_packages = fields.Boolean(
        compute="_compute_has_partial_result_packages",
    )
    show_details_visible = fields.Boolean(
        string="Details Visible",
        compute="_compute_show_details_visible",
    )
    additional = fields.Boolean(
        string="Whether the move was added after the picking's confirmation",
        default=False,
    )
    picked = fields.Boolean(
        string="Picked",
        compute="_compute_picked",
        inverse="_inverse_picked",
        store=True,
        readonly=False,
        copy=False,
        default=False,
        help="This checkbox is just indicative, it doesn't validate or generate any product moves.",
    )
    is_locked = fields.Boolean(
        compute="_compute_is_locked",
        readonly=True,
    )
    is_initial_demand_editable = fields.Boolean(
        string="Is initial demand editable",
        compute="_compute_is_initial_demand_editable",
    )
    is_quantity_done_editable = fields.Boolean(
        string="Is quantity done editable",
        compute="_compute_is_quantity_done_editable",
    )
    move_lines_count = fields.Integer(compute="_compute_move_lines_count")
    show_lot_actions = fields.Boolean(
        string="Show Lot/Serial Actions",
        compute="_compute_show_info",
        help="Whether the Generate/Import Serials-Lots buttons apply to this move.",
    )
    next_serial = fields.Char("First SN/Lot")
    next_serial_count = fields.Integer("Number of SN/Lots")
    orderpoint_id = fields.Many2one(
        comodel_name="stock.warehouse.orderpoint",
        string="Original Reordering Rule",
        index=True,
    )
    forecast_availability = fields.Float(
        string="Forecast Availability",
        compute="_compute_forecast_information",
        digits="Product Unit",
        compute_sudo=True,
    )
    date_planned_forecast = fields.Datetime(
        string="Forecasted Expected date",
        compute="_compute_forecast_information",
        compute_sudo=True,
    )
    lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        compute="_compute_lot_ids",
        inverse="_inverse_lot_ids",
        string="Serial Numbers",
        readonly=False,
    )
    date_reservation = fields.Date(
        string="Date to Reserve",
        compute="_compute_date_reservation",
        store=True,
        help="Computes when a move should be reserved",
    )
    packaging_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Packaging",
        help="Packaging unit from sale or purchase orders",
        compute="_compute_packaging_uom_id",
        precompute=True,
        store=True,
    )
    quantity_packaging_uom = fields.Float(
        string="Packaging Quantity",
        compute="_compute_quantity_packaging_uom",
        store=True,
        help="Quantity in the packaging unit",
    )
    show_quant = fields.Boolean(
        string="Show Quant",
        compute="_compute_show_info",
    )
    show_lots_m2o = fields.Boolean(
        string="Show lot_id",
        compute="_compute_show_info",
    )
    show_lots_text = fields.Boolean(
        string="Show lot_name",
        compute="_compute_show_info",
    )

    _product_location_index = models.Index(
        "(product_id, location_id, location_dest_id, company_id, state)",
    )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = self._prepare_create_vals(vals_list)
        res = super().create(vals_list)
        res._update_orderpoints()
        res._update_references()
        return res

    def _prepare_create_vals(self, vals_list):
        picking_ids = {
            vals["picking_id"] for vals in vals_list if vals.get("picking_id")
        }
        picking_state_by_id = {
            picking.id: picking.state
            for picking in self.env["stock.picking"].browse(picking_ids).exists()
        }
        prepared = []
        for vals in vals_list:
            changes = {}
            if vals.get("move_line_ids") and "lot_ids" in vals:
                vals = {k: v for k, v in vals.items() if k != "lot_ids"}
            if (
                picking_state_by_id.get(vals.get("picking_id")) == "done"
                and vals.get("state") != "done"
            ):
                changes["state"] = "done"
            if changes.get("state", vals.get("state")) == "done":
                changes["picked"] = True
            prepared.append({**vals, **changes} if changes else vals)
        return prepared

    def write(self, vals):
        vals = self._check_write_vals(vals)
        receipt_moves_to_reassign = self.env["stock.move"]
        move_to_recompute_state = self.env["stock.move"]
        move_to_check_location = self.env["stock.move"]
        if "product_uom_qty" in vals:
            receipt_moves_to_reassign, move_to_recompute_state = self._on_demand_change(
                vals
            )
        if "date_deadline" in vals:
            self._update_date_deadline(vals.get("date_deadline"))
        if "move_orig_ids" in vals:
            move_to_recompute_state |= self.filtered(
                lambda m: m.state not in ["draft", "cancel", "done"],
            )
        if "location_id" in vals:
            move_to_check_location = self.filtered(
                lambda m: m.location_id.id != vals.get("location_id"),
            )
        moves_leaving_orderpoint_scope = self.filtered(
            lambda m: any(
                key in vals and m[key].id != vals[key]
                for key in ("product_id", "location_id", "location_dest_id")
            ),
        )
        if moves_leaving_orderpoint_scope:
            moves_leaving_orderpoint_scope._update_orderpoints()

        res = super().write(vals)

        if "date" in vals:
            moves_done = self.filtered(lambda m: m.state == "done")
            moves_done.move_line_ids.date = vals["date"]
        if move_to_recompute_state:
            move_to_recompute_state._recompute_state()
        receipt_moves_to_reassign |= move_to_check_location._on_source_location_change()
        if "location_id" in vals or "location_dest_id" in vals:
            self._sync_warehouse_from_locations()
        if receipt_moves_to_reassign:
            receipt_moves_to_reassign._action_assign()
        if (
            "product_id" in vals
            or "state" in vals
            or "date" in vals
            or "product_uom_qty" in vals
            or "location_id" in vals
            or "location_dest_id" in vals
        ):
            self._update_orderpoints()
        if "picking_id" in vals:
            self._update_references()
        return res

    def unlink(self):
        self._unlink_if_draft_or_cancel()
        self.with_context(prefetch_fields=False).mapped("move_line_ids").unlink()
        orderpoints = self._get_orderpoints_to_update()
        res = super().unlink()
        self._update_orderpoints(orderpoints)
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft_or_cancel(self):
        for move in self:
            if move.state == "done":
                raise UserError(
                    _(
                        "You cannot delete a stock move that has been set to 'Done'."
                        " Create a return in order to reverse the moves which took place.",
                    ),
                )
            if move.state not in ("draft", "cancel") and (
                move.move_orig_ids or move.move_dest_ids
            ):
                raise UserError(
                    _("You can not delete moves linked to another operation"),
                )

    @api.model
    def default_get(self, fields):
        defaults = super().default_get(fields)
        if self.env.context.get("default_picking_id"):
            picking = self.env["stock.picking"].browse(
                self.env.context["default_picking_id"],
            )
            if picking.state == "done":
                defaults["state"] = "done"
                defaults["additional"] = True
            elif picking.state not in ("cancel", "draft"):
                defaults["additional"] = True
        return defaults

    @api.depends(
        "product_id",
        "product_id.uom_id",
        "product_id.uom_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_uom_ids(self):
        for move in self:
            move.allowed_uom_ids = (
                move.product_id.uom_id
                | move.product_id.uom_ids
                | move.sudo().product_id.seller_ids.product_uom_id
            )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for move in self:
            move.product_uom_id = move.product_id.uom_id.id

    @api.depends("picking_id.location_id")
    def _compute_location_id(self):
        for move in self:
            location = move.location_id
            if not location or (
                not move.picked and move.picking_id != move._origin.picking_id
            ):
                if move.picking_id:
                    location = move.picking_id.location_id
                elif move.picking_type_id:
                    location = move.picking_type_id.default_location_src_id
            move.location_id = location

    @api.depends("picking_id.location_dest_id", "location_final_id")
    def _compute_location_dest_id(self):
        customer_loc, __ = self.env["stock.warehouse"]._get_partner_locations()
        inter_comp_location = self.env.ref(
            "stock.stock_location_inter_company",
            raise_if_not_found=False,
        )
        for move in self:
            if move.state in ("done", "cancel") or (
                move.location_dest_id and move.location_dest_id.usage == "inventory"
            ):
                move.location_dest_id = move.location_dest_id
                continue
            if move.picking_id:
                location_dest = move.picking_id.location_dest_id
            elif move.rule_id.location_dest_from_rule:
                location_dest = move.rule_id.location_dest_id
            elif move.picking_type_id:
                location_dest = move.picking_type_id.default_location_dest_id
            else:
                location_dest = move.location_dest_id
            is_move_to_interco_transit = False
            if location_dest:
                is_move_to_interco_transit = (
                    location_dest._child_of(customer_loc)
                    and move.location_final_id == inter_comp_location
                )
            if (
                location_dest
                and move.location_final_id
                and (
                    move.location_final_id._child_of(location_dest)
                    or is_move_to_interco_transit
                )
            ):
                location_dest = move.location_final_id
            move.location_dest_id = location_dest

    @api.depends("move_line_ids.result_package_id")
    def _compute_has_partial_result_packages(self):
        for move in self:
            move.has_partial_result_packages = bool(
                move.move_line_ids.result_package_id
                and any(not line.result_package_id for line in move.move_line_ids)
            )

    @api.depends(
        "move_line_ids",
        "move_line_ids.package_history_id",
        "move_line_ids.result_package_id",
        "move_line_ids.result_package_id.outermost_package_id",
        "state",
    )
    def _compute_package_ids(self):
        for move in self:
            package_history = move.move_line_ids.package_history_id
            if move.state in ["done", "cancel"] and package_history:
                move.package_ids = package_history.outermost_dest_id
            else:
                move.package_ids = (
                    move.move_line_ids.result_package_id.outermost_package_id
                )

    @api.depends("move_line_ids.picked", "state")
    def _compute_picked(self):
        for move in self:
            if move.state == "done" or any(ml.picked for ml in move.move_line_ids):
                move.picked = True
            elif move.move_line_ids:
                move.picked = False
            else:
                move.picked = move.picked

    @api.depends("picking_id.priority")
    def _compute_priority(self):
        for move in self:
            move.priority = move.picking_id.priority or "0"

    @api.depends("picking_id.picking_type_id")
    def _compute_picking_type_id(self):
        for move in self:
            if move.picking_id:
                move.picking_type_id = move.picking_id.picking_type_id
            else:
                move.picking_type_id = move.picking_type_id

    @api.depends("picking_id.is_locked")
    def _compute_is_locked(self):
        for move in self:
            if move.picking_id:
                move.is_locked = move.picking_id.is_locked
            else:
                move.is_locked = False

    @api.depends("product_id", "has_tracking", "move_line_ids")
    def _compute_show_details_visible(self):
        has_package = self.env.user.has_group("stock.group_tracking_lot")
        multi_locations_enabled = self.env.user.has_group(
            "stock.group_stock_multi_locations",
        )
        consignment_enabled = self.env.user.has_group("stock.group_tracking_owner")

        show_details_visible = (
            multi_locations_enabled or has_package or consignment_enabled
        )

        for move in self:
            if (
                not move.product_id
                or move.state == "draft"
                or (
                    not move.picking_type_id.use_create_lots
                    and not move.picking_type_id.use_existing_lots
                    and not has_package
                    and not multi_locations_enabled
                )
            ):
                move.show_details_visible = False
            elif len(move.move_line_ids) > 1:
                move.show_details_visible = True
            else:
                move.show_details_visible = (
                    show_details_visible or move.has_tracking != "none"
                )

    @api.depends("state", "picking_id.is_locked")
    def _compute_is_initial_demand_editable(self):
        for move in self:
            move.is_initial_demand_editable = (
                not move.picking_id.is_locked or move.state == "draft"
            )

    @api.depends("product_id")
    def _compute_is_quantity_done_editable(self):
        for move in self:
            move.is_quantity_done_editable = bool(move.product_id)

    @api.depends(
        "picking_id.name",
        "scrap_id.name",
        "is_inventory",
        "inventory_name",
        "create_uid",
        "quantity",
    )
    def _compute_reference(self):
        for move in self:
            if move.scrap_id:
                move.reference = move.scrap_id.name
            elif move.is_inventory:
                move.reference = move.inventory_name or move._inventory_reference()
            else:
                move.reference = move.picking_id.name

    def _inventory_reference(self):
        self.ensure_one()
        label = (
            INVENTORY_REFERENCE_CONFIRMED
            if self.product_uom_id.is_zero(self.quantity)
            else INVENTORY_REFERENCE_UPDATED
        )
        if self.create_uid and self.create_uid.id != SUPERUSER_ID:
            label += f" ({self.create_uid.display_name})"
        return label

    @api.depends("move_line_ids")
    def _compute_move_lines_count(self):
        for move in self:
            move.move_lines_count = len(move.move_line_ids)

    @api.depends("product_id", "product_uom_id", "product_uom_qty")
    def _compute_product_qty(self):
        for move in self:
            move.product_qty = move.product_uom_id._compute_quantity(
                move.product_uom_qty,
                move.product_id.uom_id,
                rounding_method="HALF-UP",
            )

    @api.depends("picking_id.partner_id")
    def _compute_partner_id(self):
        for move in self:
            if move.picking_id:
                move.partner_id = move.picking_id.partner_id
            else:
                move.partner_id = move.partner_id

    @api.depends("move_orig_ids.date", "move_orig_ids.state", "state", "date")
    def _compute_date_delay_alert(self):
        for move in self:
            if move.state in ("done", "cancel"):
                move.date_delay_alert = False
                continue
            prev_moves = move.move_orig_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and m.date,
            )
            prev_max_date = max(prev_moves.mapped("date"), default=False)
            if prev_max_date and prev_max_date > move.date:
                move.date_delay_alert = prev_max_date
            else:
                move.date_delay_alert = False

    @api.depends("move_line_ids.quantity", "move_line_ids.product_uom_id")
    def _compute_quantity(self):
        new_moves = self.browse(move_id for move_id in self._ids if not move_id)
        for move in new_moves:
            move.quantity = move._get_move_line_quantity()

        saved_moves = self - new_moves
        if not saved_moves:
            return
        data = self.env["stock.move.line"]._read_group(
            [("move_id", "in", saved_moves.ids)],
            ["move_id", "product_uom_id"],
            ["quantity:sum"],
        )
        sum_qty = defaultdict(float)
        for move, product_uom_id, qty_sum in data:
            uom = move.product_uom_id
            sum_qty[move.id] += product_uom_id._compute_quantity(
                qty_sum,
                uom,
                round=False,
            )

        for move in saved_moves:
            move.quantity = sum_qty[move.id]

    @api.depends(
        "product_id",
        "product_qty",
        "picking_type_id",
        "quantity",
        "priority",
        "state",
        "product_uom_qty",
        "location_id",
    )
    def _compute_forecast_information(self):
        self.forecast_availability = False
        self.date_planned_forecast = False

        self.product_id.fetch(["type", "uom_id"])

        not_product_moves = self.filtered(lambda move: not move.product_id.is_storable)
        for move in not_product_moves:
            move.forecast_availability = move.product_qty

        product_moves = self - not_product_moves
        now = fields.Datetime.now()
        virtual_available_dict = product_moves._forecast_prefetch_virtual_available(now)

        def virtual_qty(key, product_id, idx):
            entry = virtual_available_dict.get(key, {}).get(product_id)
            return entry[idx] if entry else 0.0

        outgoing_unreserved_moves_per_warehouse = defaultdict(set)
        for move in product_moves:
            if move.state == "assigned":
                move.forecast_availability = move.product_uom_id._compute_quantity(
                    move.quantity,
                    move.product_id.uom_id,
                    rounding_method="HALF-UP",
                )
                continue
            key = move._forecast_virtual_key(now)
            qty_free = virtual_qty(key, move.product_id.id, 1)
            if (
                move.state == "draft"
                and move._is_consuming()
                and move.product_id.uom_id.compare(qty_free, move.product_qty) >= 0
            ):
                move.forecast_availability = qty_free
                continue
            if move._is_consuming():
                if move.state == "draft":
                    virtual_available = virtual_qty(key, move.product_id.id, 0)
                    if (
                        move.product_id.uom_id.compare(
                            virtual_available, move.product_qty
                        )
                        >= 0
                    ):
                        move.forecast_availability = virtual_available
                        continue
                    move.forecast_availability = virtual_available - move.product_qty
                elif move.state in ("waiting", "confirmed", "partially_available"):
                    outgoing_unreserved_moves_per_warehouse[
                        move.location_id.warehouse_id
                    ].add(move.id)
            elif move.picking_type_id.code == "incoming":
                forecast_availability = virtual_qty(key, move.product_id.id, 0)
                if move.state == "draft":
                    forecast_availability += move.product_qty
                move.forecast_availability = forecast_availability

        self._forecast_apply_outgoing(outgoing_unreserved_moves_per_warehouse)

    def _forecast_wh_date_key(self, now, incoming=False):
        warehouse_id = (
            self.location_dest_id.warehouse_id.id
            if incoming
            else self.location_id.warehouse_id.id
        )
        return warehouse_id, max(self.date or now, now)

    def _forecast_virtual_key(self, now):
        self.ensure_one()
        if self.state == "assigned":
            return None
        if self._is_consuming():
            if self.state != "draft":
                return None
            return self._forecast_wh_date_key(now)
        if self.picking_type_id.code == "incoming":
            return self._forecast_wh_date_key(now, incoming=True)
        return None

    def _forecast_prefetch_virtual_available(self, now):
        prefetch_virtual_available = defaultdict(set)
        for move in self:
            if (key := move._forecast_virtual_key(now)) is not None:
                prefetch_virtual_available[key].add(move.product_id.id)
        virtual_available_dict = {}
        for key_context, product_ids in prefetch_virtual_available.items():
            read_res = (
                self.env["product.product"]
                .browse(product_ids)
                .with_context(warehouse_id=key_context[0], to_date=key_context[1])
                .read(
                    [
                        "qty_available_virtual",
                        "qty_free",
                    ],
                )
            )
            virtual_available_dict[key_context] = {
                res["id"]: (res["qty_available_virtual"], res["qty_free"])
                for res in read_res
            }
        return virtual_available_dict

    def _forecast_apply_outgoing(self, outgoing_unreserved_moves_per_warehouse):
        for warehouse, moves_ids in outgoing_unreserved_moves_per_warehouse.items():
            if not warehouse:
                continue
            moves_per_location = self.browse(moves_ids).grouped("location_id")
            for location, mvs in moves_per_location.items():
                forecast_info = mvs._get_forecast_availability_outgoing(
                    warehouse,
                    location,
                )
                for move in mvs:
                    move.forecast_availability, move.date_planned_forecast = (
                        forecast_info[move]
                    )

    @api.depends("move_line_ids.lot_id", "move_line_ids.quantity")
    def _compute_lot_ids(self):
        domain = [
            ("move_id", "in", self.ids),
            ("lot_id", "!=", False),
            ("quantity", "!=", 0.0),
        ]
        lots_by_move_id = self.env["stock.move.line"]._read_group(
            domain,
            ["move_id"],
            ["lot_id:array_agg"],
        )
        lots_by_move_id = {move.id: lot_ids for move, lot_ids in lots_by_move_id}
        for move in self:
            move.lot_ids = lots_by_move_id.get(move._origin.id, [])

    @api.depends("picking_type_id", "date", "priority", "state")
    def _compute_date_reservation(self):
        for move in self:
            if move.picking_type_id.reservation_method == "by_date" and move.state in [
                "draft",
                "confirmed",
                "waiting",
                "partially_available",
            ]:
                move.date_reservation = move._reservation_date()
            elif move.picking_type_id.reservation_method == "manual":
                move.date_reservation = False
            else:
                move.date_reservation = move.date_reservation

    def _reservation_date(self, common_days=None, priority_days=None):
        self.ensure_one()
        picking_type = self.picking_type_id
        if common_days is None:
            common_days = picking_type.reservation_days_before
        if priority_days is None:
            priority_days = picking_type.reservation_days_before_priority
        days = priority_days if self.priority == "1" else common_days
        return fields.Date.to_date(self.date) - timedelta(days=days)

    def _set_reservation_date_from_days(self, common_days, priority_days):
        for move in self:
            move.date_reservation = move._reservation_date(common_days, priority_days)

    @api.depends("product_uom_id")
    def _compute_packaging_uom_id(self):
        for move in self:
            move.packaging_uom_id = move.product_uom_id

    @api.depends("product_uom_qty", "product_uom_id", "packaging_uom_id")
    def _compute_quantity_packaging_uom(self):
        for move in self:
            packaging_uom = move.packaging_uom_id
            if not packaging_uom:
                move.quantity_packaging_uom = 0.0
            elif move.product_uom_id._has_common_reference(packaging_uom):
                move.quantity_packaging_uom = move.product_uom_id._compute_quantity(
                    move.product_uom_qty,
                    packaging_uom,
                )
            else:
                move.quantity_packaging_uom = move.product_uom_qty

    @api.depends(
        "has_tracking",
        "product_id",
        "product_id.type",
        "picking_code",
        "picking_type_id.use_create_lots",
        "picking_type_id.use_existing_lots",
        "origin_returned_move_id",
        "state",
    )
    def _compute_show_info(self):
        for move in self:
            tracked = move.has_tracking != "none"
            creates_lots = move.picking_type_id.use_create_lots
            uses_existing_lots = move.picking_type_id.use_existing_lots
            is_return = bool(move.origin_returned_move_id.id)

            move.show_lot_actions = bool(
                tracked
                and move.product_id
                and creates_lots
                and not is_return
                and move.state not in ("done", "cancel")
            )
            move.show_quant = (
                move.picking_code != "incoming" and move.product_id.is_storable
            )
            move.show_lots_text = (
                tracked
                and creates_lots
                and not uses_existing_lots
                and move.state != "done"
                and not is_return
            )
            move.show_lots_m2o = (
                not move.show_quant
                and not move.show_lots_text
                and tracked
                and (uses_existing_lots or move.state == "done" or is_return)
            )

    @api.depends("picking_id", "product_id", "location_id", "location_dest_id")
    def _compute_display_name(self):
        for move in self:
            move.display_name = "%s%s%s>%s" % (
                (move.picking_id.origin and "%s/" % move.picking_id.origin) or "",
                (move.product_id.code and "%s: " % move.product_id.code) or "",
                move.location_id.name,
                move.location_dest_id.name,
            )

    @api.depends("product_id", "picking_type_id", "description_picking_manual")
    def _compute_description_picking(self):
        for move in self:
            if move.description_picking_manual:
                move.description_picking = move.description_picking_manual
            elif move.product_id:
                product = move.product_id.with_context(lang=move._get_lang())
                move.description_picking = (
                    product._get_picking_description(move.picking_type_id)
                    or move._get_description()
                )
            else:
                move.description_picking = ""

    def _inverse_location_dest_id(self):
        for ml in self.move_line_ids:
            if ml.location_dest_id._child_of(ml.move_id.location_dest_id):
                continue
            loc_dest = ml.move_id.location_dest_id._get_putaway_strategy(
                ml.product_id,
                ml.quantity_product_uom,
            )
            ml.location_dest_id = loc_dest

    def _inverse_picked(self):
        for move in self:
            move.move_line_ids.picked = move.picked

    def _inverse_quantity(self):
        def _process_decrease(move, quantity):
            mls_to_unlink = set()
            for ml in reversed(move.move_line_ids.sorted("id")):
                if self.env.context.get("unreserve_unpicked_only") and ml.picked:
                    continue
                if move.product_uom_id.is_zero(quantity):
                    break
                qty_ml_dec = min(
                    ml.quantity,
                    move.product_uom_id._compute_quantity(
                        quantity,
                        ml.product_uom_id,
                        round=False,
                    ),
                )
                if ml.product_uom_id.is_zero(qty_ml_dec):
                    continue
                if ml.product_uom_id.compare(
                    ml.quantity,
                    qty_ml_dec,
                ) == 0 and ml.state not in ["done", "cancel"]:
                    mls_to_unlink.add(ml.id)
                else:
                    ml.quantity -= qty_ml_dec
                quantity -= ml.product_uom_id._compute_quantity(
                    qty_ml_dec,
                    move.product_uom_id,
                    round=False,
                )
            self.env["stock.move.line"].browse(mls_to_unlink).unlink()

        for move in self:
            delta_qty = move.quantity - move._get_move_line_quantity()
            if move.product_uom_id.compare(delta_qty, 0) > 0:
                move._update_quantity_done(move.quantity)
            elif move.product_uom_id.compare(delta_qty, 0) < 0:
                _process_decrease(move, abs(delta_qty))

    def _inverse_product_qty(self):
        raise UserError(
            _(
                "The requested operation cannot be processed because of a programming error setting the `product_qty` field instead of the `product_uom_qty`.",
            ),
        )

    def _inverse_lot_ids(self):
        for move in self:
            if move.product_id.tracking == "none":
                continue
            if (
                move.state == "assigned"
                and all(ml.lot_id in move.lot_ids for ml in move.move_line_ids)
                and move.move_line_ids.lot_id == move.lot_ids
            ):
                continue
            move._apply_lot_ids_to_move_lines()
        self.env.add_to_compute(self._fields["quantity"], self)

    def _inverse_description_picking(self):
        for move in self:
            move.description_picking_manual = move.description_picking

    @api.onchange("lot_ids")
    def _onchange_lot_ids(self):
        product = self.product_id
        if product.tracking == "none":
            return None

        new_lot_names = OrderedSet(lot.name for lot in self.lot_ids if lot.name)
        assigned_quantity, assignable_quantity, nb_of_assignable_sml = (
            self._survey_lot_lines(new_lot_names)
        )
        old_lot_names = (
            OrderedSet(lot.name for lot in self._origin.lot_ids if lot.name)
            if self._origin
            else OrderedSet()
        )
        extra_lot_names = new_lot_names - old_lot_names
        quantity = assigned_quantity + assignable_quantity
        if not extra_lot_names:
            self.update({"quantity": quantity})
            return None

        base_location = self.picking_id.location_id or self.location_id
        quant_domain = self._extra_lot_quant_domain(extra_lot_names)
        minimal_quantity = product.uom_id._compute_quantity(1, self.product_uom_id)
        if self._should_bypass_reservation():
            nb_of_exceed = max(len(extra_lot_names) - nb_of_assignable_sml, 0)
            if nb_of_exceed > 0:
                quantity = max(
                    self.product_uom_qty,
                    quantity + nb_of_exceed * minimal_quantity,
                )
        else:
            quantity += self._extra_lot_reservable_quantity(
                extra_lot_names,
                quant_domain,
                base_location,
                assigned_quantity,
                assignable_quantity,
                minimal_quantity,
            )
        self.update({"quantity": quantity})
        return self._misplaced_serial_warning(quant_domain, base_location)

    def _survey_lot_lines(self, new_lot_names):
        assigned_quantity = 0
        assignable_quantity = 0
        nb_of_assignable_sml = 0
        for sml in self.move_line_ids:
            sml_quantity = sml.product_uom_id._compute_quantity(
                sml.quantity,
                self.product_uom_id,
            )
            if not sml.lot_id.name and not sml.lot_name:
                assignable_quantity += sml_quantity
                nb_of_assignable_sml += 1
            elif (sml.lot_id.name or sml.lot_name) in new_lot_names:
                assigned_quantity += sml_quantity
        return assigned_quantity, assignable_quantity, nb_of_assignable_sml

    def _extra_lot_quant_domain(self, extra_lot_names):
        extra_lot_ids = {
            rec["id"]
            for rec in self.env["stock.lot"]
            .sudo()
            .search_read(
                [
                    ("product_id", "=", self.product_id.id),
                    ("name", "in", extra_lot_names),
                ],
                ["id"],
            )
        }
        return Domain(
            [
                ("product_id", "=", self.product_id.id),
                ("lot_id", "in", extra_lot_ids),
                ("quantity", "!=", 0),
                ("location_id.usage", "in", ("internal", "transit", "customer")),
                ("company_id", "in", (False, self.company_id.id)),
            ],
        )

    def _extra_lot_reservable_quantity(
        self,
        extra_lot_names,
        quant_domain,
        base_location,
        assigned_quantity,
        assignable_quantity,
        minimal_quantity,
    ):
        uom = self.product_uom_id
        available_quantity_by_lot_name = self._available_quantity_by_lot_name(
            quant_domain,
            base_location,
        )
        new_assigned_quantity = len(extra_lot_names) * minimal_quantity
        qty_free = self.product_uom_qty - assigned_quantity - new_assigned_quantity
        for lot_name in extra_lot_names:
            if uom.compare(qty_free, 0.0) <= 0:
                continue
            extra_qty = (
                min(
                    available_quantity_by_lot_name[lot_name],
                    qty_free + minimal_quantity,
                )
                - minimal_quantity
            )
            if uom.compare(extra_qty, 0) > 0:
                new_assigned_quantity += extra_qty
                qty_free -= extra_qty
        return max(0, new_assigned_quantity - assignable_quantity)

    def _available_quantity_by_lot_name(self, quant_domain, base_location):
        quant_by_lot = (
            self.env["stock.quant"]
            .sudo()
            ._read_group(
                Domain.AND(
                    [quant_domain, Domain("location_id", "child_of", base_location.id)],
                ),
                ["lot_id"],
                ["quantity:sum", "reserved_quantity:sum"],
            )
        )
        available_quantity_by_lot_name = defaultdict(float)
        for lot, total_quantity, reserved_quantity in quant_by_lot:
            available_quantity_by_lot_name[lot.name] += (
                self.product_id.uom_id._compute_quantity(
                    total_quantity - reserved_quantity,
                    self.product_uom_id,
                )
            )
        return available_quantity_by_lot_name

    def _misplaced_serial_warning(self, quant_domain, base_location):
        if self.product_id.tracking != "serial":
            return None
        problematic_quants = (
            self.env["stock.quant"]
            .sudo()
            .search(
                Domain.AND(
                    [
                        quant_domain,
                        ~Domain("location_id", "child_of", base_location.id),
                    ],
                ),
            )
        )
        if not problematic_quants:
            return None
        sn_to_location = ""
        for quant in problematic_quants:
            sn_to_location += _(
                "\n(%(serial_number)s) exists in location %(location)s",
                serial_number=quant.lot_id.display_name,
                location=quant.location_id.display_name,
            )
        return {
            "warning": {
                "title": _("Warning"),
                "message": _(
                    "Unavailable Serial numbers. Please correct the serial numbers encoded: %(serial_numbers_to_locations)s",
                    serial_numbers_to_locations=sn_to_location,
                ),
            },
        }

    def action_show_details(self):
        self.ensure_one()
        view = self.env.ref("stock.view_stock_move_form_operations")

        return {
            "name": _("Detailed Operations"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.move",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "res_id": self.id,
            "context": dict(
                self.env.context,
                default_picked=self.picked,
            ),
        }

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.product_id.action_product_forecast_report()
        action["context"] = {
            "active_id": self.product_id.id,
            "active_model": "product.product",
            "move_to_match_ids": self.ids,
        }
        if self._is_consuming():
            warehouse = self.location_id.warehouse_id
        else:
            warehouse = self.location_dest_id.warehouse_id

        if warehouse:
            action["context"]["warehouse_id"] = warehouse.id
        return action

    @api.model
    def action_generate_lot_line_vals(
        self,
        context_data,
        mode,
        first_lot,
        count,
        lot_text,
    ):
        default_vals = self._prepare_lot_generation_defaults(context_data, mode)
        lot_names, lot_qties = self._prepare_lot_generation_names(
            default_vals, mode, first_lot, count, lot_text
        )
        generator = self.with_context(
            exclude_sml_ids=set(context_data.get("exclude_sml_ids") or ()),
            force_lot_m2o=bool(context_data.get("force_lot_m2o")),
        )
        vals_list = generator._prepare_generated_move_line_vals(
            default_vals, lot_names, lot_qties
        )
        product = self.env["product.product"].browse(default_vals["product_id"])
        if default_vals.get("picking_type_id"):
            picking_type = self.env["stock.picking.type"].browse(
                default_vals["picking_type_id"],
            )
            if generator._can_create_lot(picking_type):
                self._create_lot_ids_from_move_line_vals(
                    vals_list,
                    default_vals["product_id"],
                    default_vals.get("company_id", False),
                )
        self._format_move_line_vals_for_client(vals_list)
        if mode == "generate":
            self._update_lot_sequence(product, first_lot, len(lot_qties))
        return vals_list

    @api.model
    def _get_allocation_allowed_states(self, include_assigned=False):
        states = ["confirmed", "partially_available", "waiting"]
        if include_assigned:
            states.append("assigned")
        return states

    @api.model
    def _get_allocatable_demand_domain(
        self,
        location_ids,
        product_ids,
        include_assigned=True,
    ):
        return [
            ("state", "in", self._get_allocation_allowed_states(include_assigned)),
            ("product_qty", ">", 0),
            ("location_id", "in", list(location_ids)),
            ("product_id", "in", list(product_ids)),
        ]

    @api.model
    def _prepare_lot_generation_defaults(self, context_data, mode):
        if not context_data.get("default_product_id"):
            raise UserError(_("No product found to generate Serials/Lots for."))
        if mode not in ("generate", "import"):
            raise UserError(_("Invalid mode %s.", mode))

        default_vals = {}
        for key in context_data:
            if key.startswith("default_"):
                default_vals[key.removeprefix("default_")] = context_data[key]

        required_keys = ["tracking", "location_dest_id"]
        if default_vals.get("tracking") == "lot" and mode == "generate":
            required_keys.append("quantity")
        missing = [key for key in required_keys if key not in default_vals]
        if missing:
            raise UserError(
                _(
                    "Missing required values to generate Serials/Lots: %(keys)s.",
                    keys=", ".join(missing),
                ),
            )
        return default_vals

    @api.model
    def _prepare_lot_generation_names(
        self, default_vals, mode, first_lot, count, lot_text
    ):
        if default_vals["tracking"] == "lot" and mode == "generate":
            lot_qties = self._prepare_lot_generation_split(
                default_vals["quantity"], count
            )
        else:
            lot_qties = [1] * self._coerce_generated_lot_count(count)

        if mode == "generate":
            lot_names = [
                {"lot_name": name}
                for name in self.env["stock.lot"].generate_lot_names(
                    self._coerce_lot_text(
                        first_lot, _("The first Serial/Lot must be text.")
                    ),
                    len(lot_qties),
                )
            ]
        else:
            lot_names = self.split_lots(
                self._coerce_lot_text(
                    lot_text, _("The Serials/Lots to import must be text.")
                ),
            )
            lot_qties = [1] * len(lot_names)
        self._check_generated_lot_count(len(lot_qties))
        return lot_names, lot_qties

    @api.model
    def _coerce_generated_lot_count(self, count):
        not_whole = _("The number of Serials/Lots to generate must be a whole number.")
        try:
            line_count = int(count)
        except TypeError, ValueError:
            raise UserError(not_whole) from None
        if isinstance(count, float) and line_count != count:
            raise UserError(not_whole)
        self._check_generated_lot_count(line_count)
        return max(line_count, 0)

    @api.model
    def _coerce_lot_text(self, value, message):
        if not value:
            return ""
        if not isinstance(value, str):
            raise UserError(message)
        return value

    @api.model
    def _prepare_lot_generation_split(self, quantity, qty_per_lot):
        try:
            quantity = float(quantity)
            qty_per_lot = float(qty_per_lot)
        except TypeError, ValueError:
            raise UserError(
                _("The quantity and the quantity per lot must be numbers."),
            ) from None
        if qty_per_lot <= 0:
            raise UserError(
                _("The quantity per lot should always be a positive value."),
            )
        line_count = int(quantity // qty_per_lot)
        self._check_generated_lot_count(line_count)
        leftover = quantity % qty_per_lot
        qty_array = [qty_per_lot] * line_count
        if leftover:
            qty_array.append(leftover)
        return qty_array

    @api.model
    def _check_generated_lot_count(self, count):
        if count > GENERATED_LOT_VALS_MAX:
            raise UserError(
                _(
                    "You cannot generate more than %s Serials/Lots at once.",
                    GENERATED_LOT_VALS_MAX,
                ),
            )

    @api.model
    def _prepare_generated_move_line_vals(self, default_vals, lot_names, lot_qties):
        loc_dest = self.env["stock.location"].browse(
            default_vals["location_dest_id"],
        )
        product = self.env["product.product"].browse(default_vals["product_id"])
        lots = [
            lot if lot.get("quantity") else {**lot, "quantity": qty}
            for lot, qty in zip(lot_names, lot_qties, strict=True)
        ]
        locations = loc_dest._get_putaway_strategy_batch(
            product,
            [lot["quantity"] for lot in lots],
        )
        return [
            {
                **default_vals,
                **lot,
                "location_dest_id": location.id,
                "product_uom_id": default_vals.get("uom_id", product.uom_id.id),
            }
            for lot, location in zip(lots, locations, strict=True)
        ]

    @api.model
    def _format_move_line_vals_for_client(self, vals_list):
        MoveLine = self.env["stock.move.line"]
        relational_fields = {
            f_name
            for f_name in MoveLine._fields
            if isinstance(MoveLine[f_name], models.Model)
        }
        ids_by_field = defaultdict(OrderedSet)
        for values in vals_list:
            for f_name in values.keys() & relational_fields:
                if values[f_name]:
                    ids_by_field[f_name].add(values[f_name])
        name_by_field_id = {}
        for f_name, ids in ids_by_field.items():
            for record in MoveLine[f_name].browse(ids):
                name_by_field_id[f_name, record.id] = record.display_name
        for values in vals_list:
            for f_name in values.keys() & relational_fields:
                value = values[f_name]
                values[f_name] = {
                    "id": value,
                    "display_name": name_by_field_id.get((f_name, value), False),
                }

    @api.model
    def _update_lot_sequence(self, product, first_lot, generated_count):
        if not product.lot_sequence_id or not first_lot:
            return
        current_sequence = product.lot_sequence_id._get_current_sequence()
        increment = product.lot_sequence_id.number_increment
        first_number = current_sequence.number_next_actual - increment
        final_number = first_number
        if first_lot == product.lot_sequence_id.get_next_char(first_number):
            final_number = first_number + generated_count
        elif first_lot == product.lot_sequence_id.get_next_char(
            first_number + increment
        ):
            final_number = first_number + increment + generated_count
        final_number = max(final_number, current_sequence.number_next_actual)
        if final_number != current_sequence.number_next_actual:
            current_sequence.sudo().write({"number_next_actual": final_number})

    def _action_confirm(self, merge=True, merge_into=False, create_proc=True):
        consumed_from_stock_dict = self.env.context.get(
            "consumed_from_stock_dict",
            defaultdict(float),
        )
        move_create_proc, move_to_confirm, move_waiting = (
            OrderedSet(),
            OrderedSet(),
            OrderedSet(),
        )
        to_assign = OrderedSet()
        for move in self:
            if move.state != "draft":
                continue
            if move.move_orig_ids:
                move_waiting.add(move.id)
            elif move.procure_method == "make_to_order":
                move_waiting.add(move.id)
                if create_proc:
                    move_create_proc.add(move.id)
            elif move.rule_id and move.rule_id.procure_method == "mts_else_mto":
                move_to_confirm.add(move.id)
                if create_proc:
                    move_create_proc.add(move.id)
            else:
                move_to_confirm.add(move.id)
            if move._should_be_assigned():
                to_assign.add(move.id)

        self.browse(move_create_proc)._run_procurements(consumed_from_stock_dict)

        move_to_confirm, move_waiting = (
            self.browse(move_to_confirm).filtered(lambda m: m.state != "cancel"),
            self.browse(move_waiting).filtered(lambda m: m.state != "cancel"),
        )
        move_to_confirm.write({"state": "confirmed"})
        move_waiting.write({"state": "waiting"})
        (move_to_confirm | move_waiting).filtered(
            lambda m: m.picking_type_id.reservation_method == "at_confirm",
        ).write({"date_reservation": fields.Date.today()})

        if to_assign:
            self.browse(to_assign).with_context(
                clean_context(self.env.context),
            )._update_picking()

        self._check_company()
        moves = self
        if merge:
            moves = self._merge_moves(merge_into=merge_into)

        new_push_moves = moves._reverse_negative_demand()

        moves.filtered(
            lambda move: (
                move.state in ("confirmed", "partially_available")
                and (
                    move._should_bypass_reservation()
                    or move._should_assign_at_confirm()
                )
            ),
        )._action_assign()
        new_push_moves._confirm_pushed_moves()
        return moves

    def _run_procurements(self, consumed_from_stock_dict):
        quantities = self.with_context(
            consumed_from_stock_dict=consumed_from_stock_dict,
        )._prepare_procurement_qty()
        procurement_requests = [
            self.env["stock.rule"].Procurement(
                move.product_id,
                quantity,
                move.product_uom_id,
                move.location_id,
                (move.rule_id and move.rule_id.name) or "/",
                move._prepare_procurement_origin(),
                move.company_id,
                move._prepare_procurement_vals(),
            )
            for move, quantity in zip(self, quantities, strict=True)
        ]
        self.env["stock.rule"].with_context(
            consumed_from_stock_dict=consumed_from_stock_dict,
        ).run(
            procurement_requests,
            raise_user_error=not self.env.context.get("from_orderpoint"),
        )

    def _reverse_negative_demand(self):
        neg_r_moves = self.filtered(
            lambda move: move.product_uom_id.compare(move.product_uom_qty, 0) < 0,
        )
        if not neg_r_moves:
            return self.browse()
        neg_to_push = neg_r_moves.filtered(
            lambda move: (
                move.location_final_id
                and move.location_dest_id != move.location_final_id
            ),
        )
        new_push_moves = self.browse()
        if neg_to_push:
            new_push_moves = neg_to_push._push_apply()
        neg_r_moves._reverse_negative_moves()
        return new_push_moves

    def _confirm_pushed_moves(self):
        if not self:
            return
        neg_push_moves = self.filtered(
            lambda sm: sm.product_uom_id.compare(sm.product_uom_qty, 0) < 0,
        )
        (self - neg_push_moves).sudo()._action_confirm()
        neg_push_moves._action_confirm(
            merge_into=neg_push_moves.move_orig_ids.move_dest_ids,
        )

    def action_view_reference(self):
        self.ensure_one()
        if (
            not self.is_inventory
            and self.location_dest_usage == "inventory"
            and self.scrap_id
        ):
            return {
                "res_model": "stock.scrap",
                "type": "ir.actions.act_window",
                "views": [[False, "form"]],
                "res_id": self.scrap_id.id,
            }
        source = self.picking_id
        if source and source.has_access("read"):
            return {
                "res_model": source._name,
                "type": "ir.actions.act_window",
                "views": [[False, "form"]],
                "res_id": source.id,
            }
        return {
            "res_model": self._name,
            "type": "ir.actions.act_window",
            "views": [[False, "form"]],
            "res_id": self.id,
        }

    def _action_synch_order(self):
        return True

    def _action_assign(self, force_qty=False):
        assigned_moves_ids = OrderedSet()
        partially_available_moves_ids = OrderedSet()
        move_line_vals_list = []
        ledger = ReservationLedger(move_line_vals_list)
        moves_to_redirect = OrderedSet()
        moves_to_assign, quants_cache, reserved_availability = (
            self._prepare_reservation_run(force_qty)
        )
        serial_move_ids_by_qty = defaultdict(OrderedSet)
        for move in moves_to_assign.with_context(
            quants_cache=quants_cache,
            preserve_state=True,
            reservation_ledger=ledger,
        ):
            move = move.with_company(move.company_id)
            missing_reserved_quantity = move._get_missing_reserved_quantity(
                force_qty,
                reserved_availability[move.id],
            )
            if missing_reserved_quantity is None:
                assigned_moves_ids.add(move.id)
                continue
            if move._should_bypass_reservation():
                outcome = move._update_reserved_bypass(
                    missing_reserved_quantity,
                    move_line_vals_list,
                    assigned_moves_ids,
                    partially_available_moves_ids,
                )
            else:
                outcome = move._update_reserved_with_stock(
                    missing_reserved_quantity,
                    force_qty,
                    assigned_moves_ids,
                    partially_available_moves_ids,
                )
            if outcome.state == "assigned":
                assigned_moves_ids.add(move.id)
            elif outcome.state == "partially_available":
                partially_available_moves_ids.add(move.id)
            if outcome.redirect:
                moves_to_redirect.add(move.id)
            if outcome.reserved and move.product_id.tracking == "serial":
                serial_move_ids_by_qty[move._prefill_serial_count()].add(move.id)

        self._apply_reservation_outcomes(
            move_line_vals_list,
            ledger,
            quants_cache,
            assigned_moves_ids,
            partially_available_moves_ids,
            moves_to_redirect,
            serial_move_ids_by_qty,
        )

    def _prepare_reservation_run(self, force_qty):
        moves_to_assign = self
        if not force_qty:
            moves_to_assign = moves_to_assign.filtered(
                lambda m: (
                    not m.picked
                    and m.state in ["confirmed", "waiting", "partially_available"]
                ),
            )
        moves_needing_reservation = moves_to_assign.filtered(
            lambda m: not m._should_bypass_reservation(),
        )
        quants_cache = self.env["stock.quant"]._get_quants_by_products_locations(
            moves_needing_reservation.product_id,
            moves_needing_reservation.location_id,
        )
        moves_to_assign._prefetch_origin_chain()
        _logger.debug(
            "_action_assign: %s move(s), %s reserving against quants",
            len(moves_to_assign),
            len(moves_needing_reservation),
        )
        return (
            moves_to_assign,
            quants_cache,
            {m.id: m.quantity for m in moves_to_assign},
        )

    def _prefetch_origin_chain(self):
        chained = self.filtered(lambda m: m.move_orig_ids)
        if not chained:
            return
        siblings = chained.move_orig_ids.move_dest_ids
        chain = siblings | siblings.move_orig_ids
        chain.fetch(["state"])
        chain.move_line_ids.fetch(
            [
                "location_id",
                "location_dest_id",
                "lot_id",
                "package_id",
                "result_package_id",
                "owner_id",
                "quantity",
                "product_uom_id",
                "product_id",
            ],
        )

    def _get_missing_reserved_quantity(self, force_qty, reserved_uom_qty):
        self.ensure_one()
        if force_qty:
            missing_uom_quantity = force_qty
        else:
            missing_uom_quantity = self.product_uom_qty - reserved_uom_qty
        if self.product_uom_id.compare(missing_uom_quantity, 0) <= 0:
            return None
        return self.product_uom_id._compute_quantity(
            missing_uom_quantity,
            self.product_id.uom_id,
            rounding_method="HALF-UP",
        )

    def _apply_reservation_outcomes(
        self,
        move_line_vals_list,
        ledger,
        quants_cache,
        assigned_moves_ids,
        partially_available_moves_ids,
        moves_to_redirect,
        serial_move_ids_by_qty,
    ):
        StockMove = self.env["stock.move"]
        for count, move_ids in serial_move_ids_by_qty.items():
            if count:
                StockMove.browse(move_ids).next_serial_count = count
        _logger.debug(
            "_action_assign: flushing %s move line(s), %s unit(s) pending on quants",
            len(move_line_vals_list),
            ledger.total_pending(),
        )
        self.env["stock.move.line"].with_context(
            quants_cache=quants_cache,
            preserve_state=True,
        ).create(move_line_vals_list)
        _logger.debug(
            "_action_assign: %s assigned, %s partially available",
            len(assigned_moves_ids),
            len(partially_available_moves_ids),
        )
        StockMove.browse(partially_available_moves_ids).write(
            {"state": "partially_available"},
        )
        StockMove.browse(assigned_moves_ids).write({"state": "assigned"})
        if not self.env.context.get("bypass_entire_pack"):
            self.picking_id._check_entire_pack()
        StockMove.browse(moves_to_redirect).move_line_ids._apply_putaway_strategy()

    def _action_cancel(self):
        if any(
            move.state == "done" and move.location_dest_usage != "inventory"
            for move in self
        ):
            raise UserError(
                _(
                    "You cannot cancel a stock move that has been set to 'Done'. Create a return in order to reverse the moves which took place.",
                ),
            )
        moves_to_cancel = self.filtered(
            lambda m: (
                m.state != "cancel"
                and not (m.state == "done" and m.location_dest_usage == "inventory")
            ),
        )
        moves_to_cancel._do_unreserve(force=True)
        moves_to_cancel.picked = False
        cancel_moves_origin = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.cancel_moves_origin")
        )

        moves_to_cancel.state = "cancel"

        for move in moves_to_cancel:
            siblings_states = (
                move.move_dest_ids.mapped("move_orig_ids") - move
            ).mapped("state")
            if move.propagate_cancel:
                if all(state == "cancel" for state in siblings_states):
                    move_dest_to_cancel = move.move_dest_ids.filtered(
                        lambda m, move=move: (
                            m.state != "done" and move.location_dest_id == m.location_id
                        )
                    )
                    move_dest_to_cancel._action_cancel()
                    (move.move_dest_ids - move_dest_to_cancel).write(
                        {
                            "procure_method": "make_to_stock",
                            "move_orig_ids": [Command.unlink(move.id)],
                        },
                    )
                    if cancel_moves_origin:
                        move.move_orig_ids.sudo().filtered(
                            lambda m: m.state != "done",
                        )._action_cancel()
            elif all(state in ("done", "cancel") for state in siblings_states):
                move_dest_ids = move.move_dest_ids
                move_dest_ids.write(
                    {
                        "procure_method": "make_to_stock",
                        "move_orig_ids": [Command.unlink(move.id)],
                    },
                )
        if not self.env.context.get("skip_cancel_activity"):
            moves_to_cancel._log_cancel_activity()
        moves_to_cancel.write(
            {
                "move_orig_ids": [(5, 0, 0)],
                "procure_method": "make_to_stock",
            },
        )
        return True

    def _action_done(self, cancel_backorder=False):
        moves = self.filtered(lambda move: move.state == "draft")._action_confirm(
            merge=False,
        )
        moves = (
            (self | moves)
            .exists()
            .filtered(lambda x: x.state not in ("done", "cancel"))
        )

        moves._drop_unpicked_lines_and_cancel_empty(cancel_backorder)

        moves_todo = moves.filtered(
            lambda m: (
                not (
                    m.state == "cancel"
                    or (m.quantity <= 0 and not m.is_inventory)
                    or not m.picked
                )
            ),
        )

        moves_todo._check_company()
        if not cancel_backorder:
            moves_todo._create_backorder()
        moves_todo.mapped("move_line_ids").sorted()._action_done()
        moves_todo._check_packages_not_split()
        same_package_mls = moves_todo.move_line_ids.filtered(
            lambda ml: ml.package_id and ml.package_id == ml.result_package_id
        )
        if same_package_mls:
            self.env["stock.quant"]._unlink_zero_quants(
                products=same_package_mls.product_id,
                locations=same_package_mls.location_id
                | same_package_mls.location_dest_id,
            )
        picking = moves_todo.mapped("picking_id")
        moves_todo.write({"state": "done", "date": fields.Datetime.now()})

        moves_todo._push_and_assign_downstream()

        if self.env.context.get("is_scrap"):
            return moves

        if picking and not cancel_backorder:
            backorder = picking._create_backorder()
            if any(m.state == "assigned" for m in backorder.move_ids):
                backorder._check_entire_pack()
        if moves_todo:
            moves_todo._check_quantity()
            moves_todo._action_synch_order()
        return moves_todo

    def _drop_unpicked_lines_and_cancel_empty(self, cancel_backorder):
        ml_ids_to_unlink = OrderedSet()
        for move in self:
            if move.picked:
                ml_ids_to_unlink |= move.move_line_ids.filtered(
                    lambda ml: not ml.picked,
                ).ids
            if (
                (move.quantity <= 0 or not move.picked)
                and not move.is_inventory
                and (
                    move.product_uom_id.compare(move.product_uom_qty, 0.0) == 0
                    or cancel_backorder
                )
            ):
                move._action_cancel()
        self.env["stock.move.line"].browse(ml_ids_to_unlink).unlink()

    def _check_packages_not_split(self):
        packages = self.move_line_ids.filtered(
            lambda ml: ml.picked
        ).result_package_id.filtered(lambda p: len(p.quant_ids) > 1)
        for package in packages:
            locations = package.quant_ids.filtered(
                lambda q: q.product_uom_id.compare(q.quantity, 0.0) > 0,
            ).location_id
            if len(locations) > 1:
                raise UserError(
                    _(
                        "You cannot move the same package content more than once in the same transfer"
                        " or split the same package into two location.",
                    )
                    + _("\nPackage: %s", package.name)
                )

    def _push_and_assign_downstream(self):
        moves_to_push = self.filtered(lambda m: not m._skip_push())
        if moves_to_push:
            moves_to_push._push_apply()
        move_dests_per_company = defaultdict(lambda: self.env["stock.move"])
        for move_dest in self.move_dest_ids:
            move_dests_per_company[move_dest.company_id.id] |= move_dest
        for company_id, move_dests in move_dests_per_company.items():
            move_dests.sudo().with_company(company_id)._action_assign()

    def _adjust_procure_method(self, picking_type_code=False):
        rule_cache = {}
        for move in self:
            product_id = move.product_id
            warehouse = move.warehouse_id or move.picking_type_id.warehouse_id
            cache_key = (
                move.location_id.id,
                move.location_dest_id.id,
                product_id.id,
                warehouse.id,
                move.packaging_uom_id.id,
            )
            if cache_key in rule_cache:
                rule = rule_cache[cache_key]
            else:
                rule = self.env["stock.rule"]
                location = move.location_id
                while location:
                    domain = [
                        ("location_src_id", "=", location.id),
                        ("location_dest_id", "=", move.location_dest_id.id),
                        ("action", "!=", "push"),
                    ]
                    if picking_type_code:
                        domain.append(("picking_type_id.code", "=", picking_type_code))
                    rule = self.env["stock.rule"]._get_rule_by_domain(
                        False,
                        move.packaging_uom_id,
                        product_id,
                        warehouse,
                        domain,
                    )
                    if rule:
                        break
                    location = location.location_id
                rule_cache[cache_key] = rule
            if not rule:
                move.procure_method = "make_to_stock"
                continue

            move.rule_id = rule.id
            if rule.procure_method in ["make_to_stock", "make_to_order"]:
                move.procure_method = rule.procure_method
            else:
                move.procure_method = "make_to_stock"

    def _add_serial_move_line_to_vals_list(self, reserved_quant, quantity):
        return [
            self._prepare_move_line_vals(quantity=1, reserved_quant=reserved_quant)
            for _i in range(self._serial_line_count(quantity))
        ]

    def _serial_line_count(self, quantity):
        return max(int(self.product_id.uom_id.round(quantity)), 0)

    def _prefill_serial_count(self):
        self.ensure_one()
        if self.next_serial_count:
            return 0
        return self._serial_line_count(self.product_qty)

    def _apply_lot_ids_to_move_lines(self):
        self.ensure_one()
        product = self.product_id
        (
            move_lines_commands,
            available_move_lines,
            assigned_lot_ids,
            free_uom_qty,
        ) = self._classify_move_lines_for_lots()
        should_bypass_reservation = self._should_bypass_reservation()
        extra_uom_qty = free_uom_qty - len(set(self.lot_ids.ids) - assigned_lot_ids)
        quants_by_lot = {}
        if not should_bypass_reservation:
            quants_by_lot = (
                self.env["stock.quant"]
                ._gather(product, self.location_id)
                .grouped("lot_id")
            )
        for lot in self.lot_ids:
            if lot.id in assigned_lot_ids:
                continue
            if should_bypass_reservation:
                commands, available_move_lines, extra_uom_qty = (
                    self._prepare_lot_commands_bypass(
                        lot, available_move_lines, extra_uom_qty
                    )
                )
            else:
                commands, extra_uom_qty = self._prepare_lot_commands_reserve(
                    lot,
                    quants_by_lot.get(lot, self.env["stock.quant"]),
                    extra_uom_qty,
                )
            move_lines_commands += commands
        if not should_bypass_reservation and available_move_lines:
            move_lines_commands += self._prepare_lot_commands_rebalance_unlotted(
                available_move_lines,
                extra_uom_qty,
            )
        self.write({"move_line_ids": move_lines_commands})

    def _update_picking(self):
        Picking = self.env["stock.picking"]
        grouped_moves = groupby(self, key=lambda m: m._key_assign_picking())
        for _group, moves in grouped_moves:
            moves = self.env["stock.move"].concat(*moves)
            new_picking = False
            picking = moves[0]._search_picking_for_assignation()
            if picking:
                vals = moves._prepare_picking_vals(picking)
                if vals:
                    picking.write(vals)
            else:
                moves = moves.filtered(
                    lambda m: m.product_uom_id.compare(m.product_uom_qty, 0.0) >= 0,
                )
                if not moves:
                    continue
                new_picking = True
                picking = Picking.create(moves._prepare_new_picking_vals())

            moves.write({"picking_id": picking.id})
            moves._post_process_picking(new=new_picking)
        return True

    def _prepare_picking_vals(self, picking):
        vals = {}
        if any(picking.partner_id != m.partner_id for m in self):
            vals["partner_id"] = False
        if any(picking.origin != m.origin for m in self):
            current_origins = picking.origin.split(",") if picking.origin else []
            new_moves_origins = [move.origin for move in self if move.origin]
            new_origin = ",".join(OrderedSet(current_origins + new_moves_origins))
            if picking.origin != new_origin:
                vals["origin"] = new_origin
        return vals

    def _post_process_picking(self, new=False):
        pass

    def _update_reserved_bypass(
        self,
        missing_reserved_quantity,
        move_line_vals_list,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        self.ensure_one()
        if self.move_orig_ids:
            missing_reserved_quantity = self._add_bypassed_origin_lines(
                missing_reserved_quantity,
                move_line_vals_list,
                assigned_moves_ids,
                partially_available_moves_ids,
            )

        still_missing = not self.product_id.uom_id.is_zero(missing_reserved_quantity)
        if (
            still_missing
            and self.product_id.tracking == "serial"
            and (
                self.picking_type_id.use_create_lots
                or self.picking_type_id.use_existing_lots
            )
        ):
            for _i in range(self._serial_line_count(missing_reserved_quantity)):
                move_line_vals_list.append(
                    self._prepare_move_line_vals(quantity=1),
                )
        elif still_missing:
            to_update = self.move_line_ids.filtered(
                lambda ml: (
                    ml.product_uom_id == self.product_uom_id
                    and ml.location_id == self.location_id
                    and ml.location_dest_id == self.location_dest_id
                    and ml.picking_id == self.picking_id
                    and not ml.picked
                    and not ml.lot_id
                    and not ml.result_package_id
                    and not ml.package_id
                    and not ml.owner_id
                ),
            )
            if to_update:
                to_update[0].quantity += self.product_id.uom_id._compute_quantity(
                    missing_reserved_quantity,
                    self.product_uom_id,
                    rounding_method="HALF-UP",
                )
            else:
                move_line_vals_list.append(
                    self._prepare_move_line_vals(
                        quantity=missing_reserved_quantity,
                    ),
                )
        return _ReservationOutcome(state="assigned", redirect=True)

    def _add_bypassed_origin_lines(
        self,
        missing_reserved_quantity,
        move_line_vals_list,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        self.ensure_one()
        available_move_lines = self._get_available_move_lines(
            assigned_moves_ids,
            partially_available_moves_ids,
        )
        for (
            location_id,
            lot_id,
            package_id,
            owner_id,
        ), quantity in available_move_lines.items():
            qty_added = min(missing_reserved_quantity, quantity)
            move_line_vals = self._prepare_move_line_vals(qty_added)
            move_line_vals.update(
                {
                    "location_id": location_id.id,
                    "lot_id": lot_id.id,
                    "lot_name": lot_id.name,
                    "owner_id": owner_id.id,
                    "package_id": package_id.id,
                },
            )
            move_line_vals_list.append(move_line_vals)
            missing_reserved_quantity -= qty_added
            if self.product_id.uom_id.is_zero(missing_reserved_quantity):
                break
        return missing_reserved_quantity

    def _update_reserved_with_stock(
        self,
        missing_reserved_quantity,
        force_qty,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        self.ensure_one()
        if self.product_uom_id.is_zero(self.product_uom_qty) and not force_qty:
            return _ReservationOutcome(state="assigned")
        if not self.move_orig_ids:
            return self._update_reserved_from_quants(missing_reserved_quantity)
        return self._update_reserved_from_origins(
            missing_reserved_quantity,
            force_qty,
            assigned_moves_ids,
            partially_available_moves_ids,
        )

    def _update_reserved_from_quants(self, need):
        self.ensure_one()
        uom = self.product_id.uom_id
        if self.procure_method == "make_to_order":
            return _ReservationOutcome(reserved=False)
        if uom.is_zero(need):
            return _ReservationOutcome(state="assigned", reserved=False)
        taken_quantity = self._update_reserved_quantity(
            need,
            self.location_id,
            strict=False,
        )
        if uom.is_zero(taken_quantity):
            return _ReservationOutcome(reserved=False)
        short = uom.compare(need, taken_quantity) != 0
        return _ReservationOutcome(
            state="partially_available" if short else "assigned",
            redirect=True,
        )

    def _update_reserved_from_origins(
        self,
        missing_reserved_quantity,
        force_qty,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        self.ensure_one()
        uom = self.product_id.uom_id
        available_move_lines = self._get_available_move_lines(
            assigned_moves_ids,
            partially_available_moves_ids,
        )
        if not available_move_lines:
            return _ReservationOutcome(reserved=False)
        self._deduct_own_lines(available_move_lines)

        if force_qty:
            target_qty = missing_reserved_quantity
        else:
            target_qty = self.product_qty - sum(
                self.move_line_ids.mapped("quantity_product_uom"),
            )
        taken_qty_total = 0.0
        all_move_line_vals = []
        for (
            location_id,
            lot_id,
            package_id,
            owner_id,
        ), quantity in available_move_lines.items():
            need = target_qty - taken_qty_total
            if uom.compare(need, 0) <= 0:
                break
            move_line_vals, taken_quantity = self._update_reserved_quantity_vals(
                min(quantity, need),
                location_id,
                lot_id,
                package_id,
                owner_id,
                strict=True,
            )
            all_move_line_vals += move_line_vals
            taken_qty_total += taken_quantity

        ledger = self.env.context.get("reservation_ledger")
        if ledger is not None:
            ledger.move_line_vals.extend(all_move_line_vals)
        elif all_move_line_vals:
            self.env["stock.move.line"].create(all_move_line_vals)

        if uom.is_zero(taken_qty_total):
            return _ReservationOutcome()
        short = uom.compare(target_qty - taken_qty_total, 0) > 0
        return _ReservationOutcome(
            state="partially_available" if short else "assigned",
            redirect=True,
        )

    def _deduct_own_lines(self, available_move_lines):
        self.ensure_one()
        for move_line in self.move_line_ids.filtered(
            lambda ml: ml.quantity_product_uom,
        ):
            key = (
                move_line.location_id,
                move_line.lot_id,
                move_line.package_id,
                move_line.owner_id,
            )
            if available_move_lines.get(key):
                available_move_lines[key] -= move_line.quantity_product_uom

    def _reverse_negative_moves(self):
        for move in self:
            new_source, new_dest = move.location_dest_id, move.location_id
            move.move_line_ids.filtered(
                lambda ml, src=new_source: not ml.location_id._child_of(src),
            ).unlink()
            orig_move_ids, dest_move_ids = [], []
            for m in move.move_orig_ids | move.move_dest_ids:
                from_loc, to_loc = m.location_id, m.location_dest_id
                if m.product_uom_id.compare(m.product_uom_qty, 0) < 0:
                    from_loc, to_loc = to_loc, from_loc
                if to_loc == new_source:
                    orig_move_ids += m.ids
                elif new_dest == from_loc:
                    dest_move_ids += m.ids
            vals = {
                "location_id": new_source.id,
                "location_dest_id": new_dest.id,
                "location_final_id": new_dest.id,
                "move_orig_ids": [Command.set(orig_move_ids)],
                "move_dest_ids": [Command.set(dest_move_ids)],
                "product_uom_qty": -move.product_uom_qty,
                "procure_method": "make_to_stock",
            }
            if move.picking_type_id.return_picking_type_id:
                vals["picking_type_id"] = move.picking_type_id.return_picking_type_id.id
            move.write(vals)
        if self:
            self._update_picking()

    def _break_mto_link(self, parent_move):
        self.move_orig_ids = [Command.unlink(parent_move.id)]
        self.procure_method = "make_to_stock"
        self._recompute_state()

    def _classify_move_lines_for_lots(self):
        self.ensure_one()
        product = self.product_id
        commands = []
        lot_id_by_name = {lot.name: lot.id for lot in self.lot_ids}
        available_move_line_ids = []
        free_uom_qty = self.product_uom_id._compute_quantity(
            max(self.quantity, self.product_uom_qty),
            product.uom_id,
        )
        assigned_lot_ids = set()
        for ml in self.move_line_ids:
            lot_name = ml.lot_id.name or ml.lot_name
            if ml.product_uom_id.is_zero(ml.quantity):
                continue
            if not ml.lot_id and not ml.lot_name:
                available_move_line_ids.append(ml.id)
            elif lot_name in lot_id_by_name:
                lot_id = lot_id_by_name[lot_name]
                assigned_lot_ids.add(lot_id)
                free_uom_qty -= ml.product_uom_id._compute_quantity(
                    ml.quantity,
                    product.uom_id,
                )
                commands.append(Command.update(ml.id, {"lot_id": lot_id}))
            else:
                commands.append(Command.delete(ml.id))
        return (
            commands,
            self.env["stock.move.line"].browse(available_move_line_ids),
            assigned_lot_ids,
            free_uom_qty,
        )

    def _clean_merged(self):
        self.write({"propagate_cancel": False})

    def _create_backorder(self):
        backorder_moves_vals = []
        for move in self:
            if (
                move.product_uom_id.compare(
                    move.quantity,
                    move.product_uom_qty,
                )
                < 0
            ):
                qty_split = move.product_uom_id._compute_quantity(
                    move.product_uom_qty - move.quantity,
                    move.product_id.uom_id,
                    rounding_method="HALF-UP",
                )
                new_move_vals = move._split(qty_split)
                backorder_moves_vals += new_move_vals
        backorder_moves = self.env["stock.move"].create(backorder_moves_vals)
        backorder_moves.with_context(bypass_entire_pack=True)._action_confirm(
            merge=False,
            create_proc=False,
        )
        return backorder_moves

    def _create_lot_ids_from_move_line_vals(
        self,
        vals_list,
        product_id,
        company_id=False,
    ):
        lot_names = [vals["lot_name"] for vals in vals_list if vals.get("lot_name")]
        lot_ids = self.env["stock.lot"].search(
            [
                ("product_id", "=", product_id),
                "|",
                ("company_id", "=", company_id),
                ("company_id", "=", False),
                ("name", "in", lot_names),
            ],
        )
        lot_id_names = set(lot_ids.mapped("name"))
        missing_names = dict.fromkeys(
            lot_name for lot_name in lot_names if lot_name not in lot_id_names
        )
        lots_to_create_vals = [
            {"product_id": product_id, "name": lot_name} for lot_name in missing_names
        ]
        lot_ids |= self.env["stock.lot"].create(lots_to_create_vals)

        lot_id_by_name = {lot.name: lot.id for lot in lot_ids}
        for vals in vals_list:
            lot_name = vals.get("lot_name", None)
            if not lot_name:
                continue
            vals["lot_id"] = lot_id_by_name[lot_name]
            vals["lot_name"] = False

    def _convert_string_into_field_data(self, string, options):
        string = string.replace(",", ".")
        if regex_fullmatch(r"[0-9]+\.?[0-9]*|\.[0-9]+", string):
            return {"quantity": float(string)}
        return False

    def _delay_alert_get_documents(self):
        return list(self.mapped("picking_id"))

    def _do_unreserve(self, force=False):
        moves_to_unreserve = OrderedSet()
        for move in self:
            if (
                move.state == "cancel"
                or (move.state == "done" and move.location_dest_usage == "inventory")
                or (move.picked and not force)
            ):
                continue
            if move.state == "done":
                raise UserError(
                    _("You cannot unreserve a stock move that has been set to 'Done'."),
                )
            moves_to_unreserve.add(move.id)
        moves_to_unreserve = self.env["stock.move"].browse(moves_to_unreserve)

        ml_to_unlink = OrderedSet()
        moves_not_to_recompute = OrderedSet()
        for ml in moves_to_unreserve.move_line_ids:
            if ml.picked and not force:
                moves_not_to_recompute.add(ml.move_id.id)
                continue
            ml_to_unlink.add(ml.id)
        ml_to_unlink = self.env["stock.move.line"].browse(ml_to_unlink)
        moves_not_to_recompute = self.env["stock.move"].browse(moves_not_to_recompute)

        ml_to_unlink.unlink()
        (moves_to_unreserve - moves_not_to_recompute)._recompute_state()
        return True

    def _generate_serial_numbers(
        self,
        next_serial,
        next_serial_count=False,
        location_id=False,
    ):
        self.ensure_one()
        count = next_serial_count or self.next_serial_count
        if not count:
            raise ValidationError(
                _(
                    "The number of Serial Numbers to generate must be greater than zero.",
                ),
            )
        lot_names = self.env["stock.lot"].generate_lot_names(next_serial, count)
        field_data = [{"lot_name": lot_name, "quantity": 1} for lot_name in lot_names]
        if self._can_create_lot():
            self._create_lot_ids_from_move_line_vals(
                field_data,
                self.product_id.id,
                self.company_id.id,
            )
        move_lines_commands = self._generate_serial_move_line_commands(
            field_data,
            location_dest_id=location_id,
        )
        self.move_line_ids = move_lines_commands
        return True

    def _generate_serial_move_line_commands(
        self,
        field_data,
        location_dest_id=False,
        origin_move_line=None,
    ):
        self.ensure_one()
        origin_move_line = origin_move_line or self.env["stock.move.line"]
        loc_dest = origin_move_line.location_dest_id or location_dest_id
        move_line_vals = {
            "picking_id": self.picking_id.id,
            "location_id": self.location_id.id,
            "product_id": self.product_id.id,
            "product_uom_id": self.product_id.uom_id.id,
        }
        move_lines = self.move_line_ids.filtered(
            lambda ml: not ml.lot_id and not ml.lot_name,
        )

        if origin_move_line:
            move_line_vals.update(
                {
                    "owner_id": origin_move_line.owner_id.id,
                    "package_id": origin_move_line.package_id.id,
                },
            )

        reused, created = field_data[: len(move_lines)], field_data[len(move_lines) :]
        move_lines_commands = [
            Command.update(move_lines[i].id, command_vals)
            for i, command_vals in enumerate(reused)
        ]
        already_placed = defaultdict(float)
        for line, command_vals in zip(move_lines, reused, strict=False):
            already_placed[line.location_dest_id.id] += command_vals["quantity"]

        if loc_dest:
            locations = [loc_dest] * len(created)
        else:
            locations = self.location_dest_id._get_putaway_strategy_batch(
                self.product_id,
                [command_vals["quantity"] for command_vals in created],
                additional_qty=already_placed,
            )
        move_lines_commands += [
            Command.create(
                {**move_line_vals, **command_vals, "location_dest_id": location.id},
            )
            for command_vals, location in zip(created, locations, strict=True)
        ]
        return move_lines_commands

    def _get_description(self):
        product = self.product_id.with_context(lang=self._get_lang())
        return product._get_description(self.picking_type_id)

    def _get_partner_id(self):
        self.ensure_one()
        if self.location_id == self.company_id.internal_transit_location_id:
            return self.location_dest_id.warehouse_id.partner_id.id
        return self.partner_id.id

    def _get_relevant_state_among_moves(self):
        sort_map = {
            "assigned": 4,
            "waiting": 3,
            "partially_available": 2,
            "confirmed": 1,
        }
        moves_todo = self.filtered(
            lambda move: (
                move.state not in ["cancel", "done"]
                and not (move.state == "assigned" and not move.product_uom_qty)
            ),
        ).sorted(key=lambda move: (sort_map.get(move.state, 0), move.product_uom_qty))
        if not moves_todo:
            return "assigned"
        least_available = moves_todo[:1]
        most_available = moves_todo[-1:]
        if least_available.picking_id and least_available.picking_id.move_type == "one":
            if all(not m.product_uom_qty for m in moves_todo):
                return "assigned"
            if least_available.state in ("confirmed", "partially_available"):
                return "confirmed"
            return least_available.state or "draft"
        if least_available.state != "assigned" and any(
            move.state in ("assigned", "partially_available") for move in moves_todo
        ):
            return "partially_available"
        if (
            most_available.state == "confirmed"
            and most_available.product_uom_id.is_zero(
                most_available.product_uom_qty,
            )
        ):
            return "assigned"
        return most_available.state or "draft"

    def _get_formatting_options(self, strings):
        return {}

    def _prepare_new_picking_vals(self):
        origins = list(dict.fromkeys(self.filtered("origin").mapped("origin")))
        origin = ",".join(origins[:5]) if origins else False
        if origins and len(origins) > 5:
            origin += "..."
        partners = self.partner_id
        vals = {
            "origin": origin,
            "company_id": self.company_id.id,
            "user_id": False,
            "partner_id": partners.id if len(partners) == 1 else False,
            "picking_type_id": self.picking_type_id.id,
            "location_id": self.location_id.id,
        }
        if self.location_dest_id:
            vals["location_dest_id"] = self.location_dest_id.id
        return vals

    def _get_mto_procurement_date(self):
        return self.date

    def _get_picked_quantity(self):
        self.ensure_one()
        if self.picked and any(not ml.picked for ml in self.move_line_ids):
            picked_qty = 0
            for ml in self.move_line_ids:
                if not ml.picked:
                    continue
                picked_qty += ml.product_uom_id._compute_quantity(
                    ml.quantity,
                    self.product_uom_id,
                    round=False,
                )
            return picked_qty
        return self.quantity

    def _get_available_quantity(
        self,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=False,
        allow_negative=False,
    ):
        self.ensure_one()
        if location_id.should_bypass_reservation():
            return self.product_qty
        return self.env["stock.quant"]._get_available_quantity(
            self.product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            allow_negative=allow_negative,
        )

    def _get_available_move_lines_in(self):
        move_lines_in = self.move_orig_ids.move_dest_ids.move_orig_ids.filtered(
            lambda m: m.state == "done",
        ).mapped("move_line_ids")

        def _keys_in_groupby(ml):
            return (ml.location_dest_id, ml.lot_id, ml.result_package_id, ml.owner_id)

        grouped_move_lines_in = {}
        for k, g in groupby(move_lines_in, key=_keys_in_groupby):
            quantity = 0
            for ml in g:
                quantity += ml.product_uom_id._compute_quantity(
                    ml.quantity,
                    ml.product_id.uom_id,
                )
            grouped_move_lines_in[k] = quantity

        return grouped_move_lines_in

    def _get_available_move_lines_out(
        self,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        moves_out_siblings = self.move_orig_ids.move_dest_ids - self
        move_lines_out_done = moves_out_siblings.filtered(
            lambda m: m.state == "done",
        ).move_line_ids
        moves_out_siblings_to_consider = moves_out_siblings & self.browse(
            OrderedSet((*assigned_moves_ids, *partially_available_moves_ids)),
        )
        reserved_moves_out_siblings = moves_out_siblings.filtered(
            lambda m: m.state in ["partially_available", "assigned"],
        )
        move_lines_out_reserved = (
            reserved_moves_out_siblings | moves_out_siblings_to_consider
        ).move_line_ids

        def _keys_out_groupby(ml):
            return (ml.location_id, ml.lot_id, ml.package_id, ml.owner_id)

        grouped_move_lines_out = {}
        for k, g in groupby(move_lines_out_done, key=_keys_out_groupby):
            quantity = 0
            for ml in g:
                quantity += ml.product_uom_id._compute_quantity(
                    ml.quantity,
                    ml.product_id.uom_id,
                )
            grouped_move_lines_out[k] = quantity
        for k, g in groupby(move_lines_out_reserved, key=_keys_out_groupby):
            grouped_move_lines_out[k] = grouped_move_lines_out.get(k, 0) + sum(
                self.env["stock.move.line"]
                .concat(*list(g))
                .mapped("quantity_product_uom"),
            )

        return grouped_move_lines_out

    def _get_available_move_lines(
        self,
        assigned_moves_ids,
        partially_available_moves_ids,
    ):
        grouped_move_lines_in = self._get_available_move_lines_in()
        grouped_move_lines_out = self._get_available_move_lines_out(
            assigned_moves_ids,
            partially_available_moves_ids,
        )
        available_move_lines = {
            key: grouped_move_lines_in[key] - grouped_move_lines_out.get(key, 0)
            for key in grouped_move_lines_in
        }
        uom = self.product_id.uom_id
        return {k: v for k, v in available_move_lines.items() if uom.compare(v, 0) > 0}

    def _get_lang(self):
        return (
            self.picking_id.partner_id.lang
            or self.partner_id.lang
            or self.env.user.lang
        )

    def _get_source_document(self):
        self.ensure_one()
        return self.picking_id or False

    def _get_upstream_documents_and_responsibles(self, visited):
        if len(visited) >= self._MAX_UPSTREAM_DEPTH:
            _logger.warning(
                "stopped looking for upstream documents of move %s after %s moves; "
                "responsibles further up the chain will not be notified",
                self.id,
                len(visited),
            )
            return set()
        if (
            self not in visited
            and self.move_orig_ids
            and any(m.state not in ("done", "cancel") for m in self.move_orig_ids)
        ):
            visited |= self
            return set(
                itertools.chain.from_iterable(
                    move._get_upstream_documents_and_responsibles(visited)
                    for move in self.move_orig_ids
                    if move.state not in ("done", "cancel")
                ),
            )
        return set()

    def _get_report_description_picking(self):
        self.ensure_one()
        description = self.description_picking or ""
        if description.startswith(self.product_id.display_name):
            description = description.removeprefix(self.product_id.display_name).strip()
        return description

    def _get_forecast_availability_outgoing(self, warehouse, location_id=False):
        wh_location_query = self.env["stock.location"]._search(
            [("id", "child_of", warehouse.view_location_id.id)],
        )
        forecast_lines = self.env["stock.forecasted_product_product"]._get_report_lines(
            False,
            self.product_id.ids,
            wh_location_query,
            location_id or warehouse.lot_stock_id,
            read=False,
        )
        result = defaultdict(lambda: (0.0, False))
        for line in forecast_lines:
            move_out = line.get("move_out")
            if not move_out or not line["quantity"]:
                continue
            move_in = line.get("move_in")
            qty_expected = (
                line["quantity"] + result[move_out][0]
                if line["replenishment_filled"]
                else -line["quantity"]
            )
            date_expected = False
            if move_in:
                date_expected = (
                    max(move_in.date, result[move_out][1])
                    if result[move_out][1]
                    else move_in.date
                )
            result[move_out] = (qty_expected, date_expected)

        return result

    def _get_product_catalog_lines_data(self, parent_record=False, **kwargs):
        if not (parent_record and self):
            return {
                "quantity": 0,
            }
        self.product_id.ensure_one()
        return {
            **parent_record._get_product_price_and_data(self.product_id),
            "quantity": (
                self.product_uom_qty
                if len(self) == 1
                else sum(self.mapped("product_qty"))
            ),
            "readOnly": len(self) > 1,
            "uomDisplayName": (len(self) == 1 and self.product_uom_id.display_name)
            or self.product_id.uom_id.display_name,
        }

    def _key_assign_picking(self):
        self.ensure_one()
        keys = (
            self.reference_ids,
            self.location_id,
            self.location_dest_id,
            self.picking_type_id,
            self.company_id,
        )
        if self.move_orig_ids.picking_id and not self.reference_ids:
            keys += (self.move_orig_ids.picking_id,)
        return keys

    def _log_cancel_activity(self):
        return

    def _prepare_lot_move_line_vals(self, lot, quantity, reserved_quant=None):
        self.ensure_one()
        vals = self._prepare_move_line_vals(
            quantity=quantity,
            reserved_quant=reserved_quant,
        )
        vals.update({"lot_id": lot.id, "lot_name": lot.name})
        if self.product_id.tracking == "serial":
            vals.update({"quantity": 1.0, "product_uom_id": self.product_id.uom_id.id})
        return vals

    def _prepare_lot_commands_bypass(self, lot, available_move_lines, extra_uom_qty):
        self.ensure_one()
        product = self.product_id
        uom = product.uom_id if product.tracking == "serial" else self.product_uom_id
        if available_move_lines:
            move_line = available_move_lines[0]
            new_vals = {
                "lot_id": lot.id,
                "lot_name": lot.name,
                "product_uom_id": uom.id,
                "quantity": (
                    1.0 if product.tracking == "serial" else move_line.quantity
                ),
            }
            commands = [Command.update(move_line.id, new_vals)]
            available_move_lines -= move_line
            extra_uom_qty -= (
                uom._compute_quantity(new_vals["quantity"], product.uom_id) - 1
            )
        else:
            quantity_to_reserve = 1.0
            if (
                product.tracking == "lot"
                and product.uom_id.compare(extra_uom_qty, 0.0) > 0
            ):
                quantity_to_reserve += extra_uom_qty
                extra_uom_qty = 0
            commands = [
                Command.create(
                    self._prepare_lot_move_line_vals(lot, quantity_to_reserve),
                ),
            ]
        return commands, available_move_lines, extra_uom_qty

    def _prepare_lot_commands_reserve(self, lot, quants, extra_uom_qty):
        self.ensure_one()
        product = self.product_id
        commands = []
        reserved = False
        for quant in quants:
            if reserved and product.uom_id.compare(extra_uom_qty, 0.0) <= 0:
                break
            if product.uom_id.compare(quant.available_quantity, 0.0) <= 0:
                continue
            quantity_to_reserve = min(
                quant.available_quantity,
                max(extra_uom_qty if reserved else extra_uom_qty + 1, 1),
            )
            if product.uom_id.compare(quantity_to_reserve, 0.0) > 0:
                if product.tracking == "serial":
                    quantity_to_reserve = 1
                commands.append(
                    Command.create(
                        self._prepare_lot_move_line_vals(
                            lot,
                            quantity_to_reserve,
                            reserved_quant=quant,
                        ),
                    ),
                )
                extra_uom_qty -= (
                    quantity_to_reserve if reserved else quantity_to_reserve - 1
                )
                reserved = True
        if not reserved:
            commands.append(
                Command.create(self._prepare_lot_move_line_vals(lot, 1.0)),
            )
        return commands, extra_uom_qty

    def _prepare_lot_commands_rebalance_unlotted(
        self, available_move_lines, extra_uom_qty
    ):
        self.ensure_one()
        product = self.product_id
        commands = [Command.delete(ml.id) for ml in available_move_lines]
        for move_line in available_move_lines:
            if product.uom_id.compare(extra_uom_qty, 0.0) <= 0:
                break
            ml_quantity = move_line.product_uom_id._compute_quantity(
                move_line.quantity,
                product.uom_id,
            )
            quantity_to_reserve = min(ml_quantity, extra_uom_qty)
            new_ml_quantity = product.uom_id._compute_quantity(
                quantity_to_reserve,
                move_line.product_uom_id,
            )
            commands.append(
                Command.create(
                    move_line.copy_data(
                        {
                            "quantity": new_ml_quantity,
                            "picked": move_line.picked,
                        },
                    )[0],
                ),
            )
            extra_uom_qty -= quantity_to_reserve
        return commands

    def _get_availability_relevant_moves(self):
        return self.filtered(lambda move: move.state not in ("cancel", "done"))

    def _is_availability_short(self):
        return any(
            move.product_id
            and move.product_id.uom_id.compare(
                move.forecast_availability,
                0 if move.state == "draft" else move.product_qty,
            )
            == -1
            for move in self._get_availability_relevant_moves()
        )

    def _get_availability(self, comparison_date):
        if not self:
            return "available", False
        if self._is_availability_short():
            return "late", False
        forecast_date = max(
            self._get_availability_relevant_moves()
            .filtered("date_planned_forecast")
            .mapped("date_planned_forecast"),
            default=False,
        )
        if not forecast_date:
            return "available", False
        state = (
            "late"
            if comparison_date and comparison_date < forecast_date
            else "expected"
        )
        return state, forecast_date

    def _get_availability_state(self, comparison_date):
        return self._get_availability(comparison_date)[0]

    def _match_searched_availability(self, operator, value, comparison_date):
        if not value:
            raise UserError(_("Search not supported without a value."))
        if operator not in ("=", "!=", "in", "not in"):
            raise UserError(_("Operation not supported"))
        values = set(value) if isinstance(value, (list, tuple, set)) else {value}
        matched = self._get_availability_state(comparison_date) in values
        return matched == (operator in ("=", "in"))

    def _prepare_merge_moves_vals(self):
        state = self._get_relevant_state_among_moves()
        origin = "/".join(
            dict.fromkeys(self.filtered(lambda m: m.origin).mapped("origin")),
        )
        return {
            "product_uom_qty": sum(self.mapped("product_uom_qty")),
            "date": (
                min(self.mapped("date"))
                if all(p.move_type == "direct" for p in self.picking_id)
                else max(self.mapped("date"))
            ),
            "move_dest_ids": [(4, m.id) for m in self.mapped("move_dest_ids")],
            "move_orig_ids": [(4, m.id) for m in self.mapped("move_orig_ids")],
            "state": state,
            "origin": origin,
        }

    def _merge_move_itemgetter(self, distinct_fields, excluded_fields=None):
        field_names = set(distinct_fields or []) - set(excluded_fields or [])
        float_fields = {
            f_name for f_name in field_names if self._fields[f_name].type == "float"
        }
        non_float_fields = tuple(field_names - float_fields)

        def base_getter(move):
            return tuple(move[f_name] for f_name in non_float_fields)

        if not float_fields:
            return base_getter

        float_precision = {
            f_name: (self._fields[f_name].get_digits(self.env) or (False, 2))[1]
            for f_name in float_fields
        }
        if "price_unit" in float_fields:
            price_unit_prec = self.env["decimal.precision"].precision_get(
                "Product Price",
            )
            currency_precision = (
                min(self.company_id.mapped("currency_id.decimal_places"))
                if self.company_id
                else False
            )
            float_precision["price_unit"] = (
                min(currency_precision, price_unit_prec)
                if currency_precision
                else price_unit_prec
            )

        def _get_formatted_float_fields(move, f_name, precision):
            rounded_value = float_round(
                move[f_name],
                precision_digits=precision[f_name],
            )
            return "{:.{precision}f}".format(rounded_value, precision=precision[f_name])

        return lambda move: (
            base_getter(move)
            + tuple(
                _get_formatted_float_fields(move, f_name, float_precision)
                for f_name in float_fields
            )
        )

    def _merge_moves(self, merge_into=False):
        candidate_moves_set = set()
        if not merge_into:
            self._update_candidate_moves_list(candidate_moves_set)
        else:
            candidate_moves_set.add(merge_into | self)

        distinct_fields = (
            self | self.env["stock.move"].concat(*candidate_moves_set)
        )._prepare_merge_moves_distinct_fields()

        neg_qty_moves = self.filtered(
            lambda m: m.product_uom_id.compare(m.product_qty, 0.0) < 0,
        )
        neg_qty_moves.picking_id = False
        excluded_fields = self._prepare_merge_negative_moves_excluded_distinct_fields()
        neg_key = self._merge_move_itemgetter(distinct_fields, excluded_fields)

        moves_to_unlink, merged_moves, moves_by_neg_key = self._merge_positive_moves(
            candidate_moves_set,
            distinct_fields,
            neg_qty_moves,
            neg_key,
        )
        absorbed_moves, neg_to_unlink, moves_to_cancel = (
            self._merge_absorb_negative_moves(neg_qty_moves, moves_by_neg_key, neg_key)
        )
        merged_moves |= absorbed_moves
        moves_to_unlink |= neg_to_unlink

        (moves_to_unlink | moves_to_cancel)._clean_merged()

        if moves_to_unlink:
            moves_to_unlink._action_cancel()
            moves_to_unlink.sudo().unlink()

        if moves_to_cancel:
            moves_to_cancel.filtered(lambda m: not m.picked)._action_cancel()

        return (self | merged_moves) - moves_to_unlink

    def _merge_positive_moves(
        self,
        candidate_moves_set,
        distinct_fields,
        neg_qty_moves,
        neg_key,
    ):
        moves_to_unlink = self.env["stock.move"]
        merged_moves = self.env["stock.move"]
        moves_by_neg_key = defaultdict(lambda: self.env["stock.move"])
        merge_key = self._merge_move_itemgetter(distinct_fields)
        for candidate_moves in candidate_moves_set:
            candidate_moves = (
                candidate_moves.filtered(
                    lambda m: m.state not in ("done", "cancel", "draft"),
                )
                - neg_qty_moves
            )
            for __, g in groupby(candidate_moves, key=merge_key):
                moves = self.env["stock.move"].concat(*g)
                if len(moves) > 1:
                    moves.mapped("move_line_ids").write({"move_id": moves[0].id})
                    moves[0].write(moves._prepare_merge_moves_vals())
                    moves_to_unlink |= moves[1:]
                    merged_moves |= moves[0]
                moves_by_neg_key[neg_key(moves[0])] |= moves[0]
        return moves_to_unlink, merged_moves, moves_by_neg_key

    def _merge_absorb_negative_moves(self, neg_qty_moves, moves_by_neg_key, neg_key):
        merged_moves = self.env["stock.move"]
        moves_to_unlink = self.env["stock.move"]
        moves_to_cancel = self.env["stock.move"]
        price_unit_prec = self.env["decimal.precision"].precision_get("Product Price")

        def unit_price(total_value, quantity, uom):
            if uom.is_zero(quantity):
                return 0
            return float_round(
                total_value / quantity,
                precision_digits=price_unit_prec,
            )

        for neg_move in neg_qty_moves:
            for pos_move in moves_by_neg_key.get(neg_key(neg_move), []):
                new_total_value = (
                    pos_move.product_qty * pos_move.price_unit
                    + neg_move.product_qty * neg_move.price_unit
                )
                if (
                    pos_move.product_uom_id.compare(
                        pos_move.product_uom_qty,
                        abs(neg_move.product_uom_qty),
                    )
                    >= 0
                ):
                    new_product_qty = pos_move.product_qty + neg_move.product_qty
                    pos_move.write(
                        {
                            "product_uom_qty": pos_move.product_uom_qty
                            + neg_move.product_uom_qty,
                            "price_unit": unit_price(
                                new_total_value,
                                new_product_qty,
                                pos_move.product_id.uom_id,
                            ),
                            "move_dest_ids": [
                                Command.link(m.id)
                                for m in neg_move.mapped("move_dest_ids")
                                if m.location_id == pos_move.location_dest_id
                            ],
                            "move_orig_ids": [
                                Command.link(m.id)
                                for m in neg_move.mapped("move_orig_ids")
                                if m.location_dest_id == pos_move.location_id
                            ],
                        },
                    )
                    merged_moves |= pos_move
                    moves_to_unlink |= neg_move
                    if pos_move.product_uom_id.is_zero(pos_move.product_uom_qty):
                        moves_to_cancel |= pos_move
                    break
                neg_move.write(
                    {
                        "product_uom_qty": neg_move.product_uom_qty
                        + pos_move.product_uom_qty,
                        "price_unit": unit_price(
                            new_total_value,
                            neg_move.product_qty + pos_move.product_qty,
                            neg_move.product_id.uom_id,
                        ),
                    },
                )
                pos_move.product_uom_qty = 0
                moves_to_cancel |= pos_move
        return merged_moves, moves_to_unlink, moves_to_cancel

    def _on_demand_change(self, vals):
        new_qty = vals["product_uom_qty"]
        for move in self.filtered(
            lambda m: m.state not in ("done", "draft") and m.picking_id,
        ):
            if move.product_uom_id.compare(new_qty, move.product_uom_qty):
                self.env["stock.move.line"]._log_message(
                    move.picking_id,
                    move,
                    "stock.track_move_template",
                    vals,
                )
        if self.env.context.get("do_not_unreserve"):
            return self.browse(), self.browse()
        move_to_unreserve = self.filtered(
            lambda m: (
                m.state not in ["draft", "done", "cancel"]
                and m.product_uom_id.compare(m.quantity, new_qty) == 1
            ),
        )
        move_to_unreserve._do_unreserve()
        still_reserved = self - move_to_unreserve
        still_reserved.filtered(lambda m: m.state == "assigned").write(
            {"state": "partially_available"},
        )
        receipt_moves_to_reassign = move_to_unreserve.filtered(
            lambda m: m.location_id.usage == "supplier",
        )
        receipt_moves_to_reassign |= still_reserved.filtered(
            lambda m: (
                m.location_id.usage == "supplier"
                and m.state in ("partially_available", "assigned")
            ),
        )
        receipt_moves_to_reassign -= receipt_moves_to_reassign.filtered("picked")
        move_to_recompute_state = self - move_to_unreserve - receipt_moves_to_reassign
        return receipt_moves_to_reassign, move_to_recompute_state

    def _on_source_location_change(self):
        mls_to_unlink = self.move_line_ids.filtered(
            lambda ml: not ml.location_id._child_of(ml.move_id.location_id),
        )
        if not mls_to_unlink:
            return self.browse()
        affected = mls_to_unlink.move_id
        affected.procure_method = "make_to_stock"
        affected.move_orig_ids = [Command.clear()]
        mls_to_unlink.unlink()
        return affected

    def _post_process_created_moves(self):
        pass

    def _prepare_procurement_origin(self):
        self.ensure_one()
        return (
            (self.reference_ids and self.reference_ids[0].name)
            or self.origin
            or self.picking_id.display_name
        )

    def _prepare_procurement_qty(self):
        consumed_from_stock_dict = self.env.context.get(
            "consumed_from_stock_dict",
            defaultdict(float),
        )
        quantities = []
        mtso_products_by_locations = defaultdict(list)
        mtso_moves = set()
        for move in self:
            if move.rule_id and move.rule_id.procure_method == "mts_else_mto":
                mtso_moves.add(move.id)
                mtso_products_by_locations[move.location_id].append(move.product_id.id)

        forecasted_qties_by_loc = {}
        for location, product_ids in mtso_products_by_locations.items():
            if location.should_bypass_reservation():
                continue
            products = (
                self.env["product.product"]
                .browse(product_ids)
                .with_context(location=location.id)
            )
            forecasted_qties_by_loc[location] = {
                product.id: product.qty_free for product in products
            }
        for move in self:
            if (
                move.id not in mtso_moves
                or move.product_id.uom_id.compare(move.product_qty, 0) <= 0
            ):
                quantities.append(move.product_uom_qty)
                continue

            if move._should_bypass_reservation():
                quantities.append(move.product_uom_qty)
                continue

            qty_free = max(
                forecasted_qties_by_loc[move.location_id][move.product_id.id]
                - consumed_from_stock_dict[move.location_id, move.product_id.id],
                0,
            )
            quantity = max(move.product_qty - qty_free, 0)
            product_uom_qty = move.product_id.uom_id._compute_quantity(
                quantity,
                move.product_uom_id,
                rounding_method="HALF-UP",
            )
            quantities.append(product_uom_qty)
            consumed_from_stock_dict[move.location_id, move.product_id.id] += min(
                move.product_qty,
                qty_free,
            )

        return quantities

    def _prepare_procurement_vals(self):
        self.ensure_one()

        product_id = self.product_id.with_context(lang=self._get_lang())
        dates_info = {"date_planned": self._get_mto_procurement_date()}
        route = self.route_ids
        if not route and (result_packages := self.move_line_ids.result_package_id):
            related_packages = self.env["stock.package"].search_fetch(
                [("id", "parent_of", result_packages.ids)],
                ["package_type_id"],
            )
            route = related_packages.package_type_id.route_ids
        if (
            self.location_id.warehouse_id
            and self.location_id.warehouse_id.lot_stock_id.parent_path
            in self.location_id.parent_path
        ):
            dates_info = self.product_id._get_dates_info(
                self.date,
                self.location_id,
                route_ids=route,
            )
        warehouse = self.warehouse_id or self.picking_type_id.warehouse_id
        if not self.location_id.warehouse_id:
            warehouse = self.rule_id.route_id.supplier_wh_id

        move_dest_ids = False
        if self.procure_method == "make_to_order":
            move_dest_ids = self
        return {
            "product_description_variants": self.description_picking
            and self.description_picking.replace(
                product_id._get_description(self.picking_type_id),
                "",
            ).replace(
                product_id._get_picking_description(self.picking_type_id) or "",
                "",
            ),
            "never_product_template_attribute_value_ids": self.never_product_template_attribute_value_ids,
            "date_planned": dates_info.get("date_planned"),
            "date_order": dates_info.get("date_order"),
            "date_deadline": self.date_deadline,
            "move_dest_ids": move_dest_ids,
            "partner_id": (
                self._get_partner_id()
                if move_dest_ids or self.rule_id.procure_method == "mts_else_mto"
                else False
            ),
            "route_ids": route,
            "warehouse_id": warehouse,
            "priority": self.priority,
            "reference_ids": self.reference_ids,
            "orderpoint_id": self.orderpoint_id,
            "packaging_uom_id": self.packaging_uom_id,
        }

    def _uom_quantity_if_faithful(self, quantity, to_uom):
        self.ensure_one()
        product_uom = self.product_id.uom_id
        uom_quantity = product_uom.round(
            product_uom._compute_quantity(
                quantity,
                to_uom,
                rounding_method="HALF-UP",
            ),
        )
        back_to_product_uom = to_uom._compute_quantity(
            uom_quantity,
            product_uom,
            rounding_method="HALF-UP",
        )
        if product_uom.compare(quantity, back_to_product_uom) == 0:
            return uom_quantity
        return None

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.ensure_one()
        vals = {
            "move_id": self.id,
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "picking_id": self.picking_id.id,
            "company_id": self.company_id.id,
        }
        if quantity:
            uom_quantity = self._uom_quantity_if_faithful(quantity, self.product_uom_id)
            if uom_quantity is not None:
                vals = dict(vals, quantity=uom_quantity)
            else:
                vals = dict(
                    vals,
                    quantity=quantity,
                    product_uom_id=self.product_id.uom_id.id,
                )
        package = None
        if reserved_quant:
            package = reserved_quant.package_id
            vals = dict(
                vals,
                location_id=reserved_quant.location_id.id,
                lot_id=reserved_quant.lot_id.id or False,
                package_id=package.id or False,
                owner_id=reserved_quant.owner_id.id or False,
            )
        return vals

    def _prepare_merge_moves_distinct_fields(self):
        field_names = [
            "product_id",
            "price_unit",
            "procure_method",
            "location_id",
            "location_dest_id",
            "location_final_id",
            "product_uom_id",
            "restrict_partner_id",
            "origin_returned_move_id",
            "propagate_cancel",
            "description_picking",
            "never_product_template_attribute_value_ids",
        ]
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.merge_only_same_date")
        ):
            field_names.append("date")
        if (
            not self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.merge_ignore_date_deadline")
        ):
            field_names.append("date_deadline")
        return field_names

    def _prepare_merge_negative_moves_excluded_distinct_fields(self):
        return ["description_picking"]

    def _prepare_move_split_vals(self, qty, force_uom_id=False):
        vals = {
            "product_uom_qty": qty,
            "procure_method": self.procure_method,
            "move_dest_ids": [
                (4, x.id)
                for x in self.move_dest_ids
                if x.state not in ("done", "cancel")
            ],
            "move_orig_ids": [(4, x.id) for x in self.move_orig_ids],
            "origin_returned_move_id": self.origin_returned_move_id.id,
            "price_unit": self.price_unit,
            "date_deadline": self.date_deadline,
        }
        if force_uom_id:
            vals["product_uom_id"] = force_uom_id
        return vals

    def _get_push_rule_cached(self, StockRule, values):
        self.ensure_one()
        cache = self.env.context.get("_push_rule_cache")
        if cache is None:
            return StockRule._get_push_rule(
                self.product_id, self.location_dest_id, values
            )
        routes = values.get("route_ids")
        warehouse = values.get("warehouse_id")
        packaging_uom = values.get("packaging_uom_id")
        key = (
            self.location_dest_id.id,
            tuple(sorted(routes.ids)) if routes else (),
            tuple(sorted(self.product_id.route_ids.ids)),
            tuple(sorted(self.product_id.categ_id.total_route_ids.ids)),
            packaging_uom.id if packaging_uom else False,
            warehouse.id if warehouse else False,
            repr(values.get("domain")),
        )
        if key not in cache:
            cache[key] = StockRule._get_push_rule(
                self.product_id, self.location_dest_id, values
            )
        return cache[key]

    def _push_apply(self):
        depth = self.env.context.get("_push_apply_depth", 0) + 1
        if depth > self._MAX_PUSH_DEPTH:
            raise UserError(
                _(
                    "Push rules recursion limit reached. Check for circular push rules in your warehouse configuration."
                )
            )
        moves = self.with_context(
            _push_apply_depth=depth,
            _push_rule_cache=self.env.context.get("_push_rule_cache", {}),
        )
        plan = [move._plan_push() for move in moves]
        moves_by_rule = defaultdict(list)
        for move, rule, foreign in plan:
            if rule:
                moves_by_rule[rule, foreign].append(move.id)
        pushed = {}
        for (rule, foreign), move_ids in moves_by_rule.items():
            rule_moves = moves.browse(move_ids)
            if foreign:
                rule = rule.sudo()
                rule_moves = rule_moves.with_context(
                    allowed_companies=self.env.user.company_ids.ids,
                )
            pushed.update(rule._run_push(rule_moves))

        new_moves = moves.browse()
        for move, _rule, _foreign in plan:
            new_move = pushed.get(move.id) or moves.browse()
            new_moves |= new_move
            move._rewire_dests_after_push(new_move)
        return new_moves.sudo()._action_confirm()

    def _plan_push(self):
        self.ensure_one()
        move = self
        warehouse_id = move.warehouse_id or move.picking_id.picking_type_id.warehouse_id
        StockRule = self.env["stock.rule"]
        foreign = move.location_dest_id.company_id not in self.env.companies
        if foreign:
            StockRule = StockRule.sudo()
            move = move.with_context(
                allowed_companies=self.env.user.company_ids.ids,
            )
            warehouse_id = False

        related_packages = self.env["stock.package"]
        if result_packages := move.move_line_ids.result_package_id:
            related_packages = related_packages.search_fetch(
                [("id", "parent_of", result_packages.ids)],
                ["package_type_id"],
            )
        push_values = {
            "route_ids": move.route_ids | related_packages.package_type_id.route_ids,
            "warehouse_id": warehouse_id,
            "packaging_uom_id": move.packaging_uom_id,
        }
        rule = move._get_push_rule_cached(StockRule, push_values)
        excluded_rule_ids = []
        while (
            rule
            and rule.push_domain
            and not move.filtered_domain(literal_eval(rule.push_domain))
        ):
            excluded_rule_ids.append(rule.id)
            rule = move._get_push_rule_cached(
                StockRule,
                {**push_values, "domain": [("id", "not in", excluded_rule_ids)]},
            )
        if rule and (
            not move.origin_returned_move_id
            or move.origin_returned_move_id.location_dest_id.id
            != rule.location_dest_id.id
        ):
            return move, rule, foreign
        return move, StockRule.browse(), foreign

    def _rewire_dests_after_push(self, new_move):
        self.ensure_one()
        move_to_propagate_ids = set()
        move_to_mts_ids = set()
        for m in self.move_dest_ids - new_move:
            if (
                new_move
                and self.location_final_id
                and m.location_id == self.location_final_id
            ):
                move_to_propagate_ids.add(m.id)
            elif not m.location_id._child_of(self.location_dest_id):
                move_to_mts_ids.add(m.id)
        if move_to_mts_ids:
            self.browse(move_to_mts_ids)._break_mto_link(self)
        if move_to_propagate_ids:
            self.move_dest_ids = [
                Command.unlink(m_id) for m_id in move_to_propagate_ids
            ]
            new_move.move_dest_ids = [
                Command.link(m_id) for m_id in move_to_propagate_ids
            ]

    def _get_move_line_quantity(self):
        self.ensure_one()
        quantity = 0
        for move_line in self.move_line_ids:
            quantity += move_line.product_uom_id._compute_quantity(
                move_line.quantity,
                self.product_uom_id,
                round=False,
            )
        return quantity

    def _recompute_state(self):
        if self.env.context.get("preserve_state"):
            return
        moves_state_to_write = defaultdict(set)
        for move in self:
            uom = move.product_uom_id
            if move.state in ("cancel", "done") or (
                move.state == "draft" and not move.quantity
            ):
                continue
            if uom.compare(move.quantity, move.product_uom_qty) >= 0:
                moves_state_to_write["assigned"].add(move.id)
            elif not uom.is_zero(move.quantity):
                moves_state_to_write["partially_available"].add(move.id)
            elif (
                move.procure_method == "make_to_order" and not move.move_orig_ids
            ) or (
                move.move_orig_ids
                and any(
                    orig.product_uom_id.compare(orig.product_uom_qty, 0) > 0
                    and orig.state not in ("done", "cancel")
                    for orig in move.move_orig_ids
                )
            ):
                moves_state_to_write["waiting"].add(move.id)
            else:
                moves_state_to_write["confirmed"].add(move.id)
        for state, moves_ids in moves_state_to_write.items():
            self.browse(moves_ids).filtered(
                lambda m, state=state: m.state != state
            ).state = state

    def _rollup_move_dests_fetch(self):
        self._rollup_moves_fetch("move_dest_ids")

    def _rollup_move_origs_fetch(self):
        self._rollup_moves_fetch("move_orig_ids")

    def _rollup_moves_fetch(self, target_field):
        seen = set(self.ids)
        self.fetch([target_field])
        next_ids = set(self[target_field].ids)
        while not next_ids.issubset(seen):
            seen |= next_ids
            to_visit = self.browse(next_ids)
            to_visit.fetch([target_field])
            next_ids = set(to_visit[target_field].ids)

    def _rollup_move_dests(self, seen=False) -> OrderedSet[int]:
        return self._rollup_moves(origin=False, seen=seen)

    def _rollup_move_origs(self, seen=False) -> OrderedSet[int]:
        return self._rollup_moves(seen=seen)

    def _rollup_moves(self, origin=True, seen=False) -> OrderedSet[int]:
        target_field = "move_orig_ids" if origin else "move_dest_ids"
        if not seen:
            seen = OrderedSet()
        frontier = self
        while frontier:
            unseen = OrderedSet(frontier.ids) - seen
            if not unseen:
                break
            seen.update(unseen)
            frontier = frontier.browse(unseen)[target_field]
        return seen

    def _update_references(self):
        to_set = self.filtered(lambda m: not m.reference_ids and m.picking_id)
        for picking, moves in to_set.grouped("picking_id").items():
            if picking.reference_ids:
                moves.reference_ids = picking.reference_ids

    def _search_picking_for_assignation_domain(self):
        return [
            ("reference_ids", "in", self.reference_ids.ids),
            ("location_id", "=", self.location_id.id),
            (
                "location_dest_id",
                "=",
                (
                    self.location_dest_id.id
                    or self.picking_type_id.default_location_dest_id.id
                ),
            ),
            ("picking_type_id", "=", self.picking_type_id.id),
            ("printed", "=", False),
            (
                "state",
                "in",
                ["draft", "confirmed", "waiting", "partially_available", "assigned"],
            ),
        ]

    def _search_picking_for_assignation(self):
        self.ensure_one()
        if not self.reference_ids:
            return self.env["stock.picking"]
        domain = self._search_picking_for_assignation_domain()
        reference_set = set(self.reference_ids.ids)
        covered_picking = self.env["stock.picking"]
        for picking in self.env["stock.picking"].search(domain):
            picking_set = set(picking.reference_ids.ids)
            if picking_set == reference_set:
                return picking
            if not covered_picking and picking_set <= reference_set:
                covered_picking = picking
        return covered_picking

    def _skip_push(self):
        return self.is_inventory or (
            self.move_dest_ids
            and any(
                m.location_id._child_of(self.location_dest_id)
                or self.location_dest_id._child_of(m.location_id)
                for m in self.move_dest_ids
            )
        )

    @api.model
    def split_lots(self, lots):
        separation_char = "\t"

        if not lots:
            return []

        split_lines = [line for line in lots.splitlines() if line]
        parts_per_line = [
            line.replace(";", separation_char).split(separation_char)
            for line in split_lines
        ]
        options = self._get_formatting_options(
            [part for parts in parts_per_line for part in parts[1:]],
        )
        move_lines_vals = []
        for lot_text, lot_text_parts in zip(split_lines, parts_per_line, strict=True):
            move_line_vals = {
                "lot_name": lot_text,
                "quantity": 1,
            }
            for extra_string in lot_text_parts[1:]:
                field_data = self._convert_string_into_field_data(extra_string, options)
                if field_data:
                    lot_text = lot_text_parts[0]
                    if field_data == "ignore":
                        move_line_vals.update(lot_name=lot_text)
                    else:
                        move_line_vals.update(**field_data, lot_name=lot_text)
                else:
                    move_line_vals["lot_name"] = lot_text
                    break
            move_lines_vals.append(move_line_vals)
        return move_lines_vals

    def _split(self, qty, restrict_partner_id=False):
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError(
                _(
                    "You cannot split a stock move that has been set to 'Done' or 'Cancel'.",
                ),
            )
        if self.state == "draft":
            raise UserError(
                _("You cannot split a draft move. It needs to be confirmed first."),
            )

        if self.product_id.uom_id.is_zero(qty):
            return []

        uom_qty = self._uom_quantity_if_faithful(qty, self.product_uom_id)
        if uom_qty is not None:
            defaults = self._prepare_move_split_vals(uom_qty)
        else:
            defaults = self._prepare_move_split_vals(
                qty,
                force_uom_id=self.product_id.uom_id.id,
            )

        if restrict_partner_id:
            defaults["restrict_partner_id"] = restrict_partner_id
        new_move_vals = self.copy_data(defaults)

        new_product_qty = self.product_uom_id.round(
            self.product_id.uom_id._compute_quantity(
                max(0, self.product_qty - qty),
                self.product_uom_id,
                round=False,
            ),
        )
        self.with_context(do_not_unreserve=True).write(
            {"product_uom_qty": new_product_qty},
        )
        self._recompute_state()
        return new_move_vals

    def _update_date_deadline(self, new_deadline):
        visited = self.env.context.get("date_deadline_propagate_ids")
        if visited is None:
            visited = set()
        self._propagate_date_deadline(new_deadline, visited)

    def _propagate_date_deadline(self, new_deadline, visited):
        deadlines = self._plan_date_deadline(new_deadline, visited)
        if not deadlines:
            return
        by_value = defaultdict(OrderedSet)
        for move_id, value in deadlines.items():
            by_value[value].add(move_id)
        for value, move_ids in by_value.items():
            self.browse(move_ids).with_context(
                date_deadline_propagate_ids=visited,
            ).date_deadline = value

    def _plan_date_deadline(self, new_deadline, visited):
        planned = {}
        frontier = [(self, fields.Datetime.to_datetime(new_deadline))]
        while frontier:
            next_frontier = defaultdict(OrderedSet)
            for moves, deadline_dt in frontier:
                visited.update(moves.ids)
                for move in moves:
                    if move.date_deadline and deadline_dt:
                        delta = move.date_deadline - deadline_dt
                    else:
                        delta = 0
                    for other in move.move_dest_ids | move.move_orig_ids:
                        if other.state in ("done", "cancel") or other.id in visited:
                            continue
                        if other.date_deadline and delta:
                            value = other.date_deadline - delta
                        elif (
                            not other.date_deadline
                            or other.date_deadline != deadline_dt
                        ):
                            value = deadline_dt
                        else:
                            continue
                        planned[other.id] = value
                        next_frontier[value].add(other.id)
            for move_ids in next_frontier.values():
                visited.update(move_ids)
            frontier = [
                (self.browse(move_ids), value)
                for value, move_ids in next_frontier.items()
            ]
        return planned

    def _convert_to_move_uom(self, product_uom_qty):
        self.ensure_one()
        return self.product_id.uom_id._compute_quantity(
            product_uom_qty,
            self.product_uom_id,
            round=False,
        )

    def _prepare_quantity_done_vals(self, qty):
        self.ensure_one()
        res = []
        consumed_quant = set()
        total_qty = self.product_uom_id._compute_quantity(
            qty,
            self.product_id.uom_id,
            round=False,
        )
        qty = self._spend_on_existing_lines(total_qty, res, consumed_quant)
        qty = self._spend_on_free_quants(qty, total_qty, res, consumed_quant)
        self._add_unreserved_lines(qty, res)
        return res

    def _spend_on_existing_lines(self, qty, res, consumed_quant):
        self.ensure_one()
        for ml in self.move_line_ids:
            qty = self._spend_on_line(ml, qty, res, consumed_quant)
        return qty

    def _spend_on_line(self, ml, qty, res, consumed_quant):
        self.ensure_one()
        if ml.product_uom_id.compare(ml.quantity, 0) < 0:
            return qty
        ml_qty = ml.quantity
        if ml.product_uom_id != self.product_id.uom_id:
            ml_qty = ml.product_uom_id._compute_quantity(
                ml_qty,
                self.product_id.uom_id,
                round=False,
            )

        if self.product_uom_id.is_zero(self._convert_to_move_uom(qty)):
            res.append(Command.delete(ml.id))
            return qty

        if ml.product_id.uom_id.compare(ml_qty, qty) > 0:
            line_qty = qty
            if ml.product_uom_id != self.product_id.uom_id:
                line_qty = ml.product_id.uom_id._compute_quantity(
                    qty,
                    ml.product_uom_id,
                    round=False,
                )
            res.append(Command.update(ml.id, {"quantity": line_qty}))
            return 0

        if ml.result_package_id:
            return qty - ml_qty

        qty -= min(qty, ml_qty)
        if self.product_uom_id.compare(self._convert_to_move_uom(qty), 0) <= 0:
            return qty
        return self._grow_line_from_its_own_location(
            ml,
            ml_qty,
            qty,
            res,
            consumed_quant,
        )

    def _grow_line_from_its_own_location(
        self,
        ml,
        ml_qty,
        qty,
        res,
        consumed_quant,
    ):
        self.ensure_one()
        ml_quants = self.env["stock.quant"]._get_reserve_quantity(
            self.product_id,
            ml.location_id,
            qty,
            lot_id=ml.lot_id,
            package_id=ml.package_id,
            owner_id=ml.owner_id,
            strict=True,
        )
        avail_qty = sum(quantity for __, quantity in ml_quants)
        consumed_quant |= {quant.id for quant, __ in ml_quants}
        if self.product_uom_id.compare(avail_qty, qty) > 0:
            return qty
        qty -= avail_qty
        line_qty = avail_qty + ml_qty
        if ml.product_uom_id != self.product_id.uom_id:
            line_qty = ml.product_id.uom_id._compute_quantity(
                line_qty,
                ml.product_uom_id,
                round=False,
            )
        res.append(Command.update(ml.id, {"quantity": line_qty}))
        return qty

    def _spend_on_free_quants(self, qty, total_qty, res, consumed_quant):
        self.ensure_one()
        if self.product_uom_id.compare(self._convert_to_move_uom(qty), 0.0) <= 0:
            return qty
        quants = self.env["stock.quant"]._get_reserve_quantity(
            self.product_id,
            self.location_id,
            total_qty,
        )
        for quant, avail_qty in quants:
            if quant.id in consumed_quant:
                continue
            taken_qty = min(qty, avail_qty)
            qty -= taken_qty
            res.append(
                Command.create(
                    self._prepare_move_line_vals(
                        quantity=taken_qty,
                        reserved_quant=quant,
                    ),
                ),
            )
            if self.product_id.uom_id.compare(self._convert_to_move_uom(qty), 0.0) <= 0:
                break
        return qty

    def _add_unreserved_lines(self, qty, res):
        self.ensure_one()
        if self.product_uom_id.compare(self._convert_to_move_uom(qty), 0.0) <= 0:
            return
        if self.product_id.tracking != "serial":
            vals = self._prepare_move_line_vals(quantity=0)
            vals["quantity"] = self._convert_to_move_uom(qty)
            res.append(Command.create(vals))
            return
        for _i in range(self._serial_line_count(qty)):
            vals = self._prepare_move_line_vals(quantity=0)
            vals["quantity"] = 1
            vals["product_uom_id"] = self.product_id.uom_id.id
            res.append(Command.create(vals))

    def _update_quantity_done(self, qty):
        existing_smls = self.move_line_ids
        self.move_line_ids = self._prepare_quantity_done_vals(qty)
        (self.move_line_ids - existing_smls)._apply_putaway_strategy()

    def _sync_warehouse_from_locations(self):
        wh_by_moves = defaultdict(self.env["stock.move"].browse)
        for move in self:
            move_warehouse = (
                move.location_id.warehouse_id or move.location_dest_id.warehouse_id
            )
            if move_warehouse == move.warehouse_id:
                continue
            wh_by_moves[move_warehouse] |= move
        for warehouse, moves in wh_by_moves.items():
            moves.warehouse_id = warehouse.id

    def _trigger_scheduler(self):
        if not self or self.env["ir.config_parameter"].sudo().get_param(
            "stock.no_auto_scheduler",
        ):
            return

        seen_domain_keys = set()
        candidate_domains = []
        for move in self:
            domain_key = (
                move.product_id.id,
                move.company_id.id,
                move.location_id.id,
                move.location_dest_id.id,
            )
            if domain_key in seen_domain_keys:
                continue
            seen_domain_keys.add(domain_key)
            candidate_domains.append(
                Domain(
                    [
                        ("product_id", "=", move.product_id.id),
                        ("location_id", "parent_of", move.location_id.id),
                        ("company_id", "=", move.company_id.id),
                        "!",
                        ("location_id", "parent_of", move.location_dest_id.id),
                    ],
                ),
            )
        candidates = self.env["stock.warehouse.orderpoint"].search(
            Domain("trigger", "=", "auto") & Domain.OR(candidate_domains),
        )
        candidates_by_key = defaultdict(list)
        for candidate in candidates:
            candidates_by_key[
                candidate.product_id.id,
                candidate.company_id.id,
            ].append(candidate)

        orderpoints_by_company = defaultdict(
            lambda: self.env["stock.warehouse.orderpoint"],
        )
        orderpoints_context_by_company = defaultdict(dict)
        for move in self:
            orderpoint = next(
                (
                    candidate
                    for candidate in candidates_by_key[
                        move.product_id.id,
                        move.company_id.id,
                    ]
                    if move.location_id._child_of(candidate.location_id)
                    and not move.location_dest_id._child_of(candidate.location_id)
                ),
                self.env["stock.warehouse.orderpoint"],
            )
            if orderpoint:
                orderpoints_by_company[orderpoint.company_id] |= orderpoint
            if (
                orderpoint
                and move.product_id.uom_id.compare(
                    move.product_qty, orderpoint.product_min_qty
                )
                > 0
                and move.reference_ids
            ):
                orderpoints_context_by_company[orderpoint.company_id].setdefault(
                    orderpoint.id,
                    set(),
                )
                orderpoints_context_by_company[orderpoint.company_id][
                    orderpoint.id
                ] |= set(move.reference_ids.ids)
        for company, orderpoints in orderpoints_by_company.items():
            orderpoints.with_context(
                origins=orderpoints_context_by_company[company],
            )._procure_orderpoint_confirm(company_id=company, raise_user_error=False)

    def _trigger_assign(self):
        if not self or self.env["ir.config_parameter"].sudo().get_param(
            "stock.picking_no_auto_reserve",
        ):
            return

        product_domains = Domain.OR(
            [
                ("product_id", "in", moves.product_id.ids),
                ("location_id", "parent_of", location_dest.id),
            ]
            for location_dest, moves in self.grouped("location_dest_id").items()
        )
        static_domain = [
            ("state", "in", ["confirmed", "partially_available"]),
            ("procure_method", "=", "make_to_stock"),
            "|",
            ("date_reservation", "<=", fields.Date.today()),
            ("picking_type_id.reservation_method", "=", "at_confirm"),
        ]
        moves_to_reserve = self.env["stock.move"].search(
            Domain(static_domain) & product_domains,
            order="priority desc, date asc, id asc",
        )
        self_reference_ids = set(self.reference_ids.ids)
        moves_to_reserve = moves_to_reserve.sorted(
            key=lambda m: not self_reference_ids.isdisjoint(m.reference_ids.ids),
            reverse=True,
        )
        moves_to_reserve._action_assign()

    def _update_candidate_moves_list(self, candidate_moves_set):
        for picking in self.mapped("picking_id"):
            candidate_moves_set.add(picking.move_ids)

    def _get_orderpoints_to_update(self):
        if not self:
            return self.env["stock.warehouse.orderpoint"]
        seen = set()
        domains = []
        for move in self:
            wh_ids = tuple(
                sorted(
                    {
                        *move.location_id.warehouse_id.ids,
                        *move.location_dest_id.warehouse_id.ids,
                    },
                ),
            )
            key = (move.product_id.id, wh_ids)
            if key in seen:
                continue
            seen.add(key)
            domain_for_move = Domain("product_id", "=", move.product_id.id)
            if wh_ids:
                domain_for_move &= Domain("warehouse_id", "in", list(wh_ids))
            domains.append(domain_for_move)
        return (
            self.env["stock.warehouse.orderpoint"]
            .sudo()
            .search(Domain.OR(domains), order="id")
        )

    def _update_orderpoints(self, orderpoints=None):
        if orderpoints is None:
            orderpoints = self._get_orderpoints_to_update()
        orderpoints.invalidate_recordset(["qty_to_order", "qty_forecast"])
        self.env.add_to_compute(
            self.env["stock.warehouse.orderpoint"]._fields["qty_to_order_computed"],
            orderpoints,
        )

    def _update_reserved_quantity(
        self,
        need,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=True,
    ):
        self.ensure_one()
        move_line_vals, taken_quantity = self._update_reserved_quantity_vals(
            need,
            location_id,
            lot_id,
            package_id,
            owner_id,
            strict,
        )
        ledger = self.env.context.get("reservation_ledger")
        if ledger is not None:
            ledger.move_line_vals.extend(move_line_vals)
        elif move_line_vals:
            self.env["stock.move.line"].create(move_line_vals)
        return taken_quantity

    def _update_reserved_quantity_vals(
        self,
        need,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=True,
    ):
        self.ensure_one()
        if not lot_id:
            lot_id = self.env["stock.lot"]
        if not package_id:
            package_id = self.env["stock.package"]
        if not owner_id:
            owner_id = self.env["res.partner"]

        quants = (
            self.env["stock.quant"]
            .with_context(packaging_uom_id=self.packaging_uom_id)
            ._get_reserve_quantity(
                self.product_id,
                location_id,
                need,
                uom_id=self.product_uom_id,
                lot_id=lot_id,
                package_id=package_id,
                owner_id=owner_id,
                strict=strict,
            )
        )

        candidate_lines = self._candidate_lines_by_place()
        taken_quantity = 0
        move_line_vals = []
        for reserved_quant, quantity in self._group_quants_by_place(quants):
            taken_quantity += quantity
            move_line_vals += self._place_reserved_quant(
                reserved_quant,
                quantity,
                candidate_lines,
            )
        return move_line_vals, taken_quantity

    def _candidate_lines_by_place(self):
        self.ensure_one()
        return {
            (line.location_id, line.lot_id, line.package_id, line.owner_id): line
            for line in self.move_line_ids
            if not line.result_package_id and line.product_id.tracking != "serial"
        }

    def _group_quants_by_place(self, quants):
        grouped_quants = {}
        for quant, quantity in quants:
            key = (quant.location_id, quant.lot_id, quant.package_id, quant.owner_id)
            grouped = grouped_quants.setdefault(key, [quant, 0.0])
            grouped[1] += quantity
        return grouped_quants.values()

    def _place_reserved_quant(self, reserved_quant, quantity, candidate_lines):
        self.ensure_one()
        to_update = candidate_lines.get(
            (
                reserved_quant.location_id,
                reserved_quant.lot_id,
                reserved_quant.package_id,
                reserved_quant.owner_id,
            ),
        )
        uom_quantity = None
        if to_update:
            uom_quantity = self._uom_quantity_if_faithful(
                quantity,
                to_update.product_uom_id,
            )
        if uom_quantity is not None:
            to_update.quantity += uom_quantity
            return []
        if self.product_id.tracking == "serial" and (
            self.picking_type_id.use_create_lots
            or self.picking_type_id.use_existing_lots
        ):
            vals_list = self._add_serial_move_line_to_vals_list(
                reserved_quant,
                quantity,
            )
            if not vals_list:
                return []
            self._record_pending_reservation(reserved_quant, quantity)
            return vals_list
        self._record_pending_reservation(reserved_quant, quantity)
        return [
            self._prepare_move_line_vals(
                quantity=quantity,
                reserved_quant=reserved_quant,
            ),
        ]

    def _record_pending_reservation(self, quant, quantity):
        ledger = self.env.context.get("reservation_ledger")
        if ledger is not None:
            ledger.take(quant, quantity)

    def _get_visible_quantity(self):
        self.ensure_one()
        return self.quantity

    def _can_create_lot(self, picking_type=None):
        if picking_type is None:
            picking_type = self.picking_type_id
        return picking_type.use_existing_lots

    def _check_quantity(self):
        serial_moves = self.filtered(lambda m: m.product_id.tracking == "serial")
        if not serial_moves:
            return None
        return (
            self.env["stock.quant"]
            .sudo()
            .search(
                [
                    ("product_id", "in", serial_moves.product_id.ids),
                    ("location_id", "child_of", serial_moves.location_dest_id.ids),
                    ("lot_id", "in", serial_moves.sudo().lot_ids.ids),
                ],
            )
            .check_quantity()
        )

    def _check_write_vals(self, vals):
        if "quantity" in vals:
            if any(move.state == "cancel" for move in self):
                raise UserError(
                    _(
                        "You cannot change a cancelled stock move, create a new line instead.",
                    ),
                )
            if "lot_ids" in vals:
                vals = {"lot_ids": vals["lot_ids"], **vals}
        if (
            "product_uom_id" in vals
            and any(move.state == "done" for move in self)
            and not self.env.context.get("skip_uom_conversion")
        ):
            raise UserError(
                _(
                    "You cannot change the UoM for a stock move that has been set to 'Done'.",
                ),
            )
        return vals

    def _is_consuming(self):
        self.ensure_one()
        from_wh = self.location_id.warehouse_id
        to_wh = self.location_dest_id.warehouse_id
        return self.picking_type_id.code in ("internal", "outgoing") or (
            from_wh and to_wh and from_wh != to_wh
        )

    def _is_incoming(self):
        self.ensure_one()
        return self.location_id.usage in ("customer", "supplier") or (
            self.location_id.usage == "transit" and not self.location_id.company_id
        )

    def _is_outgoing(self):
        self.ensure_one()
        return self.location_dest_id.usage in ("customer", "supplier") or (
            self.location_dest_id.usage == "transit"
            and not self.location_dest_id.company_id
        )

    def _should_be_assigned(self):
        self.ensure_one()
        return bool(not self.picking_id and self.picking_type_id)

    def _should_bypass_reservation(self, forced_location=False):
        self.ensure_one()
        location = forced_location or self.location_id
        return location.should_bypass_reservation() or not self.product_id.is_storable

    def _should_assign_at_confirm(self):
        return (
            self._should_bypass_reservation()
            or self.picking_type_id.reservation_method == "at_confirm"
            or (self.date_reservation and self.date_reservation <= fields.Date.today())
        )
