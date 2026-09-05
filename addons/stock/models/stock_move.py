import logging
from ast import literal_eval
from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.tools.misc import OrderedSet, clean_context, groupby
from odoo.tools.translate import _

from ..const import (
    BLOCK_REASON_COMPLETING,
    BLOCK_REASON_DISPOSAL,
    BLOCK_REASON_OVERRIDE_HARD,
    BLOCK_REASON_OVERRIDE_SOFT,
    CONTEXT_BLOCK_COMPLETING,
    CONTEXT_BLOCK_IS_INVENTORY,
    DISPOSAL_DEST_USAGES,
    INCOMING_BLOCK_TYPES,
    INTERNAL_CONTEXT_FLAG,
    INVENTORY_REFERENCE_CONFIRMED,
    INVENTORY_REFERENCE_UPDATED,
    OUTGOING_BLOCK_TYPES,
)

_logger = logging.getLogger(__name__)

PROCUREMENT_PRIORITIES = [("0", "Normal"), ("1", "Urgent")]

GENERATED_LOT_VALS_MAX = 10000

FIELD_DATA_IGNORED = "ignore"


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
    move_lines_count = fields.Count("move_line_ids")
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
        self._unlink_except_done_or_linked()
        self.with_context(prefetch_fields=False).mapped("move_line_ids").unlink()
        orderpoints = self._get_orderpoints_to_update()
        res = super().unlink()
        self._update_orderpoints(orderpoints)
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done_or_linked(self):
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
                    location_dest._is_child_of(customer_loc)
                    and move.location_final_id == inter_comp_location
                )
            if (
                location_dest
                and move.location_final_id
                and (
                    move.location_final_id._is_child_of(location_dest)
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
    @api.depends_context("uid")
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
        self.check_singleton()
        label = (
            INVENTORY_REFERENCE_CONFIRMED
            if self.product_uom_id.is_zero(self.quantity)
            else INVENTORY_REFERENCE_UPDATED
        )
        if self.create_uid and self.create_uid.id != SUPERUSER_ID:
            label += f" ({self.create_uid.display_name})"
        return label

    @api.depends("product_id", "product_uom_id", "product_uom_qty")
    def _compute_product_qty(self):
        for move in self:
            move.product_qty = move.product_uom_id._compute_quantity_stored(
                move.product_uom_qty,
                move.product_id.uom_id,
            )

    @api.depends("picking_id.partner_id")
    def _compute_partner_id(self):
        for move in self:
            if move.picking_id:
                move.partner_id = move.picking_id.partner_id
            else:
                move.partner_id = move.partner_id

    @api.depends("move_line_ids.quantity", "move_line_ids.product_uom_id")
    def _compute_quantity(self):
        new_moves = self._new_records
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
            if ml.location_dest_id._is_child_of(ml.move_id.location_dest_id):
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
        def decrease_move_line_quantities(move, quantity):
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
                decrease_move_line_quantities(move, abs(delta_qty))

    def _inverse_product_qty(self):
        raise UserError(
            _(
                "The requested operation cannot be processed because of a programming error setting the `product_qty` field instead of the `product_uom_qty`.",
            ),
        )

    def _inverse_description_picking(self):
        for move in self:
            move.description_picking_manual = move.description_picking

    def action_show_details(self):
        self.check_singleton()
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
        self.check_singleton()
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
    def _get_allocation_allowed_states(self, include_assigned=False):
        states = ["confirmed", "partially_available", "waiting"]
        if include_assigned:
            states.append("assigned")
        return states

    @api.model
    def _get_domain_allocatable_demand(
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

        moves._filtered_to_assign_at_confirm()._action_assign()
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
        self.check_singleton()
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
        moves_to_cancel._unreserve(force=True)
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
                "move_orig_ids": [Command.clear()],
                "procure_method": "make_to_stock",
            },
        )
        return True

    def _action_done(self, cancel_backorder=False):
        self = self.with_context(**self._prepare_block_completion_context())

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
            moves_todo._post_block_audit()
            return moves_todo

        if picking and not cancel_backorder:
            backorder = picking._create_backorder()
            if any(m.state == "assigned" for m in backorder.move_ids):
                backorder._check_entire_pack()
        if moves_todo:
            moves_todo._check_quantity()
            moves_todo._action_synch_order()
            moves_todo._post_block_audit()
        return moves_todo

    def _prepare_block_completion_context(self):
        context = {CONTEXT_BLOCK_COMPLETING: INTERNAL_CONTEXT_FLAG}
        if self and all(self.mapped("is_inventory")):
            context[CONTEXT_BLOCK_IS_INVENTORY] = INTERNAL_CONTEXT_FLAG
        return context

    def _get_block_audit_entries(self):
        deciding = self.with_context(
            **{CONTEXT_BLOCK_COMPLETING: None, CONTEXT_BLOCK_IS_INVENTORY: None},
        ).env
        decisions = {}
        entries = []
        for line in self.move_line_ids:
            if not line.quantity:
                continue
            for direction, location, block_types in (
                ("out", line.location_id, OUTGOING_BLOCK_TYPES),
                ("in", line.location_dest_id, INCOMING_BLOCK_TYPES),
            ):
                if location.effective_block_type not in block_types:
                    continue
                key = (location.id, direction)
                if key not in decisions:
                    decisions[key] = location.with_env(deciding)._get_block_decision(
                        direction,
                    )
                allowed, override = decisions[key]
                if direction == "out" and (
                    line.location_dest_id.usage in DISPOSAL_DEST_USAGES
                ):
                    reason = BLOCK_REASON_DISPOSAL
                elif override:
                    reason = override
                elif not allowed:
                    reason = BLOCK_REASON_COMPLETING
                else:
                    continue
                entries.append(
                    {
                        "picking": line.picking_id,
                        "location": location,
                        "direction": direction,
                        "reason": reason,
                        "product": line.product_id.display_name,
                        "quantity": line.quantity,
                        "uom": line.product_uom_id.name,
                    },
                )
        return entries

    def _post_block_audit(self):
        entries = self._get_block_audit_entries()
        if not entries:
            return
        by_thread = defaultdict(list)
        for entry in entries:
            by_thread[entry["picking"] or entry["location"]].append(entry)
        author = self.env.user.partner_id
        for thread, thread_entries in by_thread.items():
            thread.sudo().message_post(
                body=self._prepare_block_audit_body(thread_entries),
                subject=self.env._("Blocked Location Operation"),
                author_id=author.id,
            )

    def _prepare_block_audit_body(self, entries):
        reason_labels = {
            BLOCK_REASON_OVERRIDE_HARD: self.env._("Hard Block override"),
            BLOCK_REASON_OVERRIDE_SOFT: self.env._("Soft Block override"),
            BLOCK_REASON_COMPLETING: self.env._("completing a prior reservation"),
            BLOCK_REASON_DISPOSAL: self.env._("scrap, correction or consumption"),
        }
        direction_labels = {
            "out": self.env._("Out of blocked locations:"),
            "in": self.env._("Into blocked locations:"),
        }
        body = Markup("<p><b>%s</b></p>") % self.env._(
            "Blocked location operation by %(user)s",
            user=self.env.user.name,
        )
        for direction in ("out", "in"):
            directed = [entry for entry in entries if entry["direction"] == direction]
            if not directed:
                continue
            body += Markup("<p><b>%s</b></p><ul>") % direction_labels[direction]
            grouped = defaultdict(list)
            for entry in directed:
                grouped[(entry["location"], entry["reason"])].append(entry)
            for (location, reason), group in grouped.items():
                body += Markup("<li><b>%s</b> (%s: %s)<ul>") % (
                    location.display_name,
                    location._get_block_type_label(location.effective_block_type),
                    reason_labels[reason],
                )
                for entry in group:
                    body += Markup("<li>%s: %s %s</li>") % (
                        entry["product"],
                        f"{entry['quantity']:g}",
                        entry["uom"] or "",
                    )
                body += Markup("</ul></li>")
            body += Markup("</ul>")
        return body

    def _drop_unpicked_lines_and_cancel_empty(self, cancel_backorder):
        ml_ids_to_unlink = OrderedSet()
        move_ids_to_cancel = OrderedSet()
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
                move_ids_to_cancel.add(move.id)
        if move_ids_to_cancel:
            self.browse(move_ids_to_cancel)._action_cancel()
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
        moves_to_push = self.filtered(lambda m: not m._is_excluded_from_push())
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

    def _update_picking(self):
        Picking = self.env["stock.picking"]
        grouped_moves = groupby(self, key=lambda m: m._get_picking_assignation_key())
        for _group, moves in grouped_moves:
            moves = self.env["stock.move"].concat(*moves)
            new_picking = False
            picking = moves[0]._get_picking_for_assignation()
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

    def _reverse_negative_moves(self):
        for move in self:
            new_source, new_dest = move.location_dest_id, move.location_id
            move.move_line_ids.filtered(
                lambda ml, src=new_source: not ml.location_id._is_child_of(src),
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

    def _get_description(self):
        product = self.product_id.with_context(lang=self._get_lang())
        return product._get_description(self.picking_type_id)

    def _get_partner_id(self):
        self.check_singleton()
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

    def _get_picked_quantity(self):
        self.check_singleton()
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

    def _get_lang(self):
        return (
            self.picking_id.partner_id.lang
            or self.partner_id.lang
            or self.env.user.lang
        )

    def _get_source_document(self):
        self.check_singleton()
        return self.picking_id or False

    def _get_report_description_picking(self):
        self.check_singleton()
        description = self.description_picking or ""
        if description.startswith(self.product_id.display_name):
            description = description.removeprefix(self.product_id.display_name).strip()
        return description

    def _get_product_catalog_lines_data(self, parent_record=False, **kwargs):
        if not (parent_record and self):
            return {
                "quantity": 0,
            }
        self.product_id.check_singleton()
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

    def _get_picking_assignation_key(self):
        self.check_singleton()
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
        move_to_unreserve._unreserve()
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
            lambda ml: not ml.location_id._is_child_of(ml.move_id.location_id),
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
        self.check_singleton()
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
        self.check_singleton()

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

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        self.check_singleton()
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

    def _get_push_rule_cached(self, StockRule, values):
        self.check_singleton()
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
        self.check_singleton()
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
        self.check_singleton()
        move_to_propagate_ids = set()
        move_to_mts_ids = set()
        for m in self.move_dest_ids - new_move:
            if (
                new_move
                and self.location_final_id
                and m.location_id == self.location_final_id
            ):
                move_to_propagate_ids.add(m.id)
            elif not m.location_id._is_child_of(self.location_dest_id):
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
        self.check_singleton()
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

    def _prefetch_rollup_move_dests(self):
        self._prefetch_rollup_moves("move_dest_ids")

    def _prefetch_rollup_move_origs(self):
        self._prefetch_rollup_moves("move_orig_ids")

    def _prefetch_rollup_moves(self, target_field):
        seen = set(self.ids)
        self.fetch([target_field])
        next_ids = set(self[target_field].ids)
        while not next_ids.issubset(seen):
            seen |= next_ids
            to_visit = self.browse(next_ids)
            to_visit.fetch([target_field])
            next_ids = set(to_visit[target_field].ids)

    def _rollup_move_dest_ids(self, seen=False) -> OrderedSet[int]:
        return self._rollup_move_ids(origin=False, seen=seen)

    def _rollup_move_orig_ids(self, seen=False) -> OrderedSet[int]:
        return self._rollup_move_ids(seen=seen)

    def _rollup_move_ids(self, origin=True, seen=False) -> OrderedSet[int]:
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

    def _get_domain_picking_for_assignation(self):
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

    def _get_picking_for_assignation(self):
        self.check_singleton()
        if not self.reference_ids:
            return self.env["stock.picking"]
        domain = self._get_domain_picking_for_assignation()
        reference_set = set(self.reference_ids.ids)
        covered_picking = self.env["stock.picking"]
        for picking in self.env["stock.picking"].search(domain):
            picking_set = set(picking.reference_ids.ids)
            if picking_set == reference_set:
                return picking
            if not covered_picking and picking_set <= reference_set:
                covered_picking = picking
        return covered_picking

    def _is_excluded_from_push(self):
        return self.is_inventory or (
            self.move_dest_ids
            and any(
                m.location_id._is_child_of(self.location_dest_id)
                or self.location_dest_id._is_child_of(m.location_id)
                for m in self.move_dest_ids
            )
        )

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
                    if move.location_id._is_child_of(candidate.location_id)
                    and not move.location_dest_id._is_child_of(candidate.location_id)
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

    def _get_visible_quantity(self):
        self.check_singleton()
        return self.quantity

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
        self.check_singleton()
        from_wh = self.location_id.warehouse_id
        to_wh = self.location_dest_id.warehouse_id
        return self.picking_type_id.code in ("internal", "outgoing") or (
            from_wh and to_wh and from_wh != to_wh
        )

    def _is_incoming(self):
        self.check_singleton()
        return self.location_id.usage in ("customer", "supplier") or (
            self.location_id.usage == "transit" and not self.location_id.company_id
        )

    def _is_outgoing(self):
        self.check_singleton()
        return self.location_dest_id.usage in ("customer", "supplier") or (
            self.location_dest_id.usage == "transit"
            and not self.location_dest_id.company_id
        )

    def _should_be_assigned(self):
        self.check_singleton()
        return bool(not self.picking_id and self.picking_type_id)
