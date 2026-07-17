import itertools
from ast import literal_eval
from collections import defaultdict
from datetime import timedelta
from re import findall as regex_findall

from odoo import api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.numbers.float_utils import float_compare, float_is_zero, float_round
from odoo.tools.misc import OrderedSet, clean_context, groupby
from odoo.tools.translate import _

PROCUREMENT_PRIORITIES = [("0", "Normal"), ("1", "Urgent")]


class StockMove(models.Model):
    _name = "stock.move"
    _description = "Stock Move"
    _order = "sequence, id"
    _rec_name = "reference"

    _MAX_PUSH_DEPTH = 50

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

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

    # used to record the product cost set by the user during a picking confirmation (when costing
    # method used is 'average price' or 'real'). Value given in company currency and in product uom.
    # as it's a technical field, we intentionally don't provide the digits attribute
    price_unit = fields.Float("Unit Price", copy=False)
    scrap_id = fields.Many2one(
        comodel_name="stock.scrap",
        string="Scrap operation",
        readonly=True,
        check_company=True,
        index="btree_not_null",
    )
    procurement_values = fields.Json(
        store=False,
        help="Dummy field to store procurement values to propagate them to later steps",
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
    availability = fields.Float(
        string="Forecasted Quantity",
        compute="_compute_product_availability",
        readonly=True,
        help="Quantity in stock that can still be reserved for this move",
    )
    # used to depict a restriction on the ownership of quants to consider when marking this move as 'done'
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
    has_lines_without_result_package = fields.Boolean(
        compute="_compute_has_lines_without_result_package",
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
    is_date_editable = fields.Boolean(
        "Is Date Editable",
        compute="_compute_is_date_editable",
    )
    is_quantity_done_editable = fields.Boolean(
        string="Is quantity done editable",
        compute="_compute_is_quantity_done_editable",
    )
    move_lines_count = fields.Integer(compute="_compute_move_lines_count")
    display_assign_serial = fields.Boolean(compute="_compute_display_assign_serial")
    display_import_lot = fields.Boolean(compute="_compute_display_assign_serial")
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

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # Read every referenced picking's state in a single query instead of
        # browsing each picking on its own inside the loop (which issued one
        # SELECT per vals on batch creation).
        picking_ids = {
            vals["picking_id"] for vals in vals_list if vals.get("picking_id")
        }
        picking_state_by_id = {
            picking.id: picking.state
            for picking in self.env["stock.picking"].browse(picking_ids)
        }
        for vals in vals_list:
            # Explicit move lines win over `lot_ids` (a field derived from them).
            # A bare `quantity`, however, must NOT drop `lot_ids`: `write()`
            # applies the two together (the `lot_ids` inverse runs first, see
            # `_check_write_vals`), so `create` has to keep them too — otherwise
            # the identical payload silently loses its lots on create but not on
            # write.
            if vals.get("move_line_ids") and "lot_ids" in vals:
                vals.pop("lot_ids")
            if (
                picking_state_by_id.get(vals.get("picking_id")) == "done"
                and vals.get("state") != "done"
            ):
                vals["state"] = "done"
            if vals.get("state") == "done":
                vals["picked"] = True
        res = super().create(vals_list)
        res._update_orderpoints()
        res._set_references()
        return res

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
            self._set_date_deadline(vals.get("date_deadline"))
        if "move_orig_ids" in vals:
            move_to_recompute_state |= self.filtered(
                lambda m: m.state not in ["draft", "cancel", "done"],
            )
        if "location_id" in vals:
            move_to_check_location = self.filtered(
                lambda m: m.location_id.id != vals.get("location_id"),
            )
        if "product_id" in vals or "location_id" in vals or "location_dest_id" in vals:
            # Refresh the orderpoints of the *current* product/locations before
            # they change; the post-write call below refreshes the new ones.
            # Both calls are intentional so old and new orderpoints stay correct.
            self._update_orderpoints()

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
            # Refresh the orderpoints the moves now point to (the pre-write call
            # above already handled the values they had before this write).
            self._update_orderpoints()
        if "picking_id" in vals:
            self._set_references()
        return res

    def unlink(self):
        # With the non plannified picking, draft moves could have some move lines.
        self.with_context(prefetch_fields=False).mapped("move_line_ids").unlink()
        # Collect the impacted orderpoints before the moves disappear: deleting
        # e.g. a confirmed receipt move changes the forecast, so `qty_to_order`
        # must be refreshed once the deletion is applied.
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
        # Moves added after the picking is confirmed are flagged `additional` so they get
        # auto-confirmed (or marked done directly if the picking is already done).
        defaults = super().default_get(fields)
        if self.env.context.get("default_picking_id"):
            picking_id = self.env["stock.picking"].browse(
                self.env.context["default_picking_id"],
            )
            if picking_id.state == "done":
                defaults["state"] = "done"
                defaults["additional"] = True
            elif picking_id.state not in ["cancel", "draft", "done"]:
                defaults["additional"] = True  # to trigger `_autoconfirm_picking`
        return defaults

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_is_date_editable(self):
        for move in self:
            if move.picking_id:
                move.is_date_editable = move.picking_id.is_date_editable
            else:
                move.is_date_editable = True

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
            if move.picked:
                continue
            if (
                not (location := move.location_id)
                or move.picking_id != move._origin.picking_id
                or move.picking_type_id != move._origin.picking_type_id
            ):
                if move.picking_id:
                    location = move.picking_id.location_id
                elif move.picking_type_id:
                    location = move.picking_type_id.default_location_src_id
            move.location_id = location

    @api.depends("picking_id.location_dest_id")
    def _compute_location_dest_id(self):
        customer_loc, __ = self.env["stock.warehouse"]._get_partner_locations()
        inter_comp_location = self.env.ref(
            "stock.stock_location_inter_company",
            raise_if_not_found=False,
        )
        for move in self:
            location_dest = False
            if move.picking_id:
                location_dest = move.picking_id.location_dest_id
            elif move.rule_id.location_dest_from_rule:
                location_dest = move.rule_id.location_dest_id
            elif move.picking_type_id:
                location_dest = move.picking_type_id.default_location_dest_id
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
                # Force the location_final as dest in the following cases:
                # - The location_final is a sublocation of destination -> Means we reached the end
                # - The location dest is an out location (i.e. Customers) but the final dest is different (e.g. Inter-Company transfers)
                location_dest = move.location_final_id
            move.location_dest_id = location_dest

    @api.depends(
        "has_tracking",
        "picking_type_id.use_create_lots",
        "picking_type_id.use_existing_lots",
        "product_id",
    )
    def _compute_display_assign_serial(self):
        for move in self:
            move.display_import_lot = (
                move.has_tracking != "none"
                and move.product_id
                and move.picking_type_id.use_create_lots
                and not move.origin_returned_move_id.id
                and move.state not in ("done", "cancel")
            )
            move.display_assign_serial = move.display_import_lot

    @api.depends("move_line_ids.result_package_id")
    def _compute_has_lines_without_result_package(self):
        for move in self:
            move.has_lines_without_result_package = (
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
                # Only display the top-level packages until the move is done.
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
                # No lines to derive from: keep the current (default) value.
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
                # Keep the current value (possibly user-set) on picking-less moves.
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
        """According to this field, the button that calls `action_show_details` will be displayed
        to work on a move from its picking form view, or not.
        """
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
            move.is_quantity_done_editable = move.product_id

    @api.depends(
        "picking_id.name",
        "scrap_id.name",
        "location_dest_usage",
        "is_inventory",
        "inventory_name",
        # The inventory fallback label below switches on `quantity`; without
        # this dependency the stored reference froze at its first computation.
        "quantity",
    )
    def _compute_reference(self):
        for move in self:
            if move.scrap_id:
                move.reference = move.scrap_id.name
            elif move.is_inventory:
                if move.inventory_name:
                    move.reference = move.inventory_name
                else:
                    move.reference = (
                        _("Product Quantity Confirmed")
                        if float_is_zero(
                            move.quantity,
                            precision_rounding=move.product_uom_id.rounding,
                        )
                        else _("Product Quantity Updated")
                    )
                    if move.create_uid and move.create_uid.id != SUPERUSER_ID:
                        move.reference += f" ({move.create_uid.display_name})"
            else:
                move.reference = move.picking_id.name

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
            # Keep a manually set partner when the move has no picking; the
            # explicit self-assignment guarantees new records get a value too.
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
        """This field represents the sum of the move lines `quantity`. It allows the user to know
        if there is still work to do.

        We take care of rounding this value at the general decimal precision and not the rounding
        of the move's UOM to make sure this value is really close to the real sum, because this
        field will be used in `_action_done` in order to know if the move will need a backorder or
        an extra move.
        """
        if not any(self._ids):
            # onchange
            for move in self:
                move.quantity = move._quantity_sml()
        else:
            # compute
            move_lines_ids = set()
            for move in self:
                move_lines_ids |= set(move.move_line_ids.ids)

            data = self.env["stock.move.line"]._read_group(
                [("id", "in", list(move_lines_ids))],
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

            for move in self:
                move.quantity = sum_qty[move.id]

    @api.depends("state", "product_id", "product_qty", "location_id")
    def _compute_product_availability(self):
        """Fill the `availability` field on a stock move, which is the quantity to potentially
        reserve. When the move is done, `availability` is set to the quantity the move did actually
        move.
        """
        for move in self:
            if move.state == "done":
                move.availability = move.product_qty
            elif not move.product_id:
                move.availability = 0.0

        # One _get_available_quantity call per unique (product, location) instead of
        # one per move: moves sharing the same product+location share the cached value.
        non_done = self.filtered(lambda m: m.state != "done" and m.product_id)
        if not non_done:
            return

        Quant = self.env["stock.quant"]
        availability_cache = {}
        for move in non_done:
            key = (move.product_id.id, move.location_id.id)
            if key not in availability_cache:
                availability_cache[key] = Quant._get_available_quantity(
                    move.product_id,
                    move.location_id,
                )
            move.availability = min(move.product_qty, availability_cache[key])

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
        """Compute forecasted information of the related product by warehouse."""
        self.forecast_availability = False
        self.date_planned_forecast = False

        # Prefetch product info to avoid fetching all product fields
        self.product_id.fetch(["type", "uom_id"])

        not_product_moves = self.filtered(lambda move: not move.product_id.is_storable)
        for move in not_product_moves:
            move.forecast_availability = move.product_qty

        product_moves = self - not_product_moves
        now = fields.Datetime.now()
        virtual_available_dict = product_moves._forecast_prefetch_virtual_available(now)

        def virtual_qty(key, product_id, idx):
            # idx 0 -> qty_available_virtual, 1 -> qty_free; 0.0 when not prefetched.
            # Every direct read goes through here so the guarded/unguarded
            # accesses can never drift apart (they used to: some branches
            # indexed the dict blindly while others checked membership first).
            entry = virtual_available_dict.get(key, {}).get(product_id)
            return entry[idx] if entry else 0.0

        outgoing_unreserved_moves_per_warehouse = defaultdict(set)
        for move in product_moves:
            key = move._forecast_wh_date_key(now)
            qty_free = virtual_qty(key, move.product_id.id, 1)
            if move.state == "assigned":
                move.forecast_availability = move.product_uom_id._compute_quantity(
                    move.quantity,
                    move.product_id.uom_id,
                    rounding_method="HALF-UP",
                )
                continue
            if (
                move.state == "draft"
                and float_compare(
                    qty_free,
                    move.product_qty,
                    precision_rounding=move.product_id.uom_id.rounding,
                )
                >= 0
            ):
                move.forecast_availability = qty_free
                continue
            # Note: internal moves are always `_is_consuming()` (see that
            # method), so they are handled here as outgoing/consuming. There is
            # deliberately no separate `code == "internal"` branch: it would be
            # unreachable.
            if move._is_consuming():
                if move.state == "draft":
                    virtual_available = virtual_qty(key, move.product_id.id, 0)
                    if (
                        float_compare(
                            virtual_available,
                            move.product_qty,
                            precision_rounding=move.product_id.uom_id.rounding,
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
                incoming_key = move._forecast_wh_date_key(now, incoming=True)
                forecast_availability = virtual_qty(incoming_key, move.product_id.id, 0)
                if move.state == "draft":
                    forecast_availability += move.product_qty
                move.forecast_availability = forecast_availability

        self._forecast_apply_outgoing(outgoing_unreserved_moves_per_warehouse)

    def _forecast_wh_date_key(self, now, incoming=False):
        """Return the ``(warehouse_id, to_date)`` context key under which this
        move's virtual availability is read. Uses the destination warehouse for
        incoming moves and the source warehouse otherwise.
        """
        warehouse_id = (
            self.location_dest_id.warehouse_id.id
            if incoming
            else self.location_id.warehouse_id.id
        )
        return warehouse_id, max(self.date or now, now)

    def _forecast_prefetch_virtual_available(self, now):
        """Read ``qty_available_virtual``/``qty_free`` for the moves in `self` in one
        batch per ``(warehouse, date)`` context instead of once per move.

        :return: {(warehouse_id, to_date): {product_id: (qty_available_virtual, qty_free)}}
        """
        prefetch_virtual_available = defaultdict(set)
        for move in self:
            # Mirror exactly the reads done in `_compute_forecast_information`:
            # only consuming *draft* moves read the source-warehouse value
            # (index 0/1); non-draft consuming moves are resolved via the
            # forecast report, not this dict, so prefetching them was wasted.
            if move._is_consuming() and move.state == "draft":
                prefetch_virtual_available[move._forecast_wh_date_key(now)].add(
                    move.product_id.id,
                )
            elif move.picking_type_id.code == "incoming":
                prefetch_virtual_available[
                    move._forecast_wh_date_key(now, incoming=True)
                ].add(move.product_id.id)
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
        """Resolve forecast availability/date for the outgoing unreserved moves
        collected during the main pass, grouped by warehouse then source
        location, using the forecast report.
        """
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
                days = move.picking_type_id.reservation_days_before
                if move.priority == "1":
                    days = move.picking_type_id.reservation_days_before_priority
                # UTC frame: `move.date` is naive UTC, and so is
                # `fields.Date.today()` at every comparison site — the
                # framework pins the process clock to UTC
                # (odoo/_monkeypatches: os.environ["TZ"] = "UTC"), per the
                # backend-computes-in-UTC policy.
                move.date_reservation = fields.Date.to_date(move.date) - timedelta(
                    days=days,
                )
            elif move.picking_type_id.reservation_method == "manual":
                move.date_reservation = False
            else:
                # Keep the current value: `at_confirm` moves get their date
                # written directly by `_action_confirm` and it must survive
                # the recomputes triggered by later state changes.
                move.date_reservation = move.date_reservation

    @api.depends("product_uom_id")
    def _compute_packaging_uom_id(self):
        for move in self:
            move.packaging_uom_id = move.product_uom_id

    # `product_uom_id` matters on its own: overrides pinning `packaging_uom_id`
    # to an order line's unit (sale_stock, purchase_stock) leave it unchanged
    # when the move's unit changes, yet the conversion base below did change.
    @api.depends("product_uom_qty", "product_uom_id", "packaging_uom_id")
    def _compute_quantity_packaging_uom(self):
        for move in self:
            if move.packaging_uom_id:
                # Display value: use the report wrapper so a legacy/import
                # packaging UoM with no common reference degrades to the
                # unconverted quantity instead of raising and blocking the flush.
                move.quantity_packaging_uom = move.product_uom_id._compute_quantity_report(
                    move.product_uom_qty,
                    move.packaging_uom_id,
                )
            else:
                move.quantity_packaging_uom = 0.0

    @api.depends(
        "has_tracking",
        "picking_type_id.use_create_lots",
        "picking_type_id.use_existing_lots",
        "state",
        "origin_returned_move_id",
        "product_id.type",
        "picking_code",
    )
    def _compute_show_info(self):
        for move in self:
            move.show_quant = (
                move.picking_code != "incoming" and move.product_id.is_storable
            )
            move.show_lots_text = (
                move.has_tracking != "none"
                and move.picking_type_id.use_create_lots
                and not move.picking_type_id.use_existing_lots
                and move.state != "done"
                and not move.origin_returned_move_id.id
            )
            move.show_lots_m2o = (
                not move.show_quant
                and not move.show_lots_text
                and move.has_tracking != "none"
                and (
                    move.picking_type_id.use_existing_lots
                    or move.state == "done"
                    or move.origin_returned_move_id.id
                )
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

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

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
            # Since the move lines might have been created in a certain order to respect
            # a removal strategy, they need to be unreserved in the opposite order
            for ml in reversed(move.move_line_ids.sorted("id")):
                if self.env.context.get("unreserve_unpicked_only") and ml.picked:
                    continue
                if move.product_uom_id.is_zero(quantity):
                    break
                # `quantity` is in the move's UoM while the line may use another
                # one (e.g. serial lines are created in the product's UoM), so
                # convert the remaining decrease into the line's UoM and back.
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

        err = []
        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")
        for move in self:
            rounded_qty = float_round(
                move.quantity,
                precision_digits=precision_digits,
                rounding_method="HALF-UP",
            )
            # Compare at a stricter precision than the one used for rounding:
            # `float_compare` rounds both operands first, so comparing at
            # `precision_digits` would always return 0 and never detect a
            # quantity entered with more decimals than the precision allows.
            if (
                float_compare(
                    rounded_qty,
                    move.quantity,
                    precision_digits=precision_digits + 2,
                )
                != 0
            ):
                err.append(
                    _(
                        """
The quantity done for the product %(product)s doesn't respect the rounding precision defined on the system.
Please change the quantity done or the rounding precision in your settings.""",
                        product=move.product_id.display_name,
                    ),
                )
                continue
            delta_qty = move.quantity - move._quantity_sml()
            if move.product_uom_id.compare(delta_qty, 0) > 0:
                move._set_quantity_done(move.quantity)
            elif move.product_uom_id.compare(delta_qty, 0) < 0:
                _process_decrease(move, abs(delta_qty))
        if err:
            raise UserError("\n".join(err))

    def _inverse_product_qty(self):
        """The meaning of product_qty field changed lately and is now a functional field computing the quantity
        in the default product UoM. This code has been added to raise an error if a write is made given a value
        for `product_qty`, where the same write should set the `product_uom_qty` field instead, in order to
        detect errors.
        """
        raise UserError(
            _(
                "The requested operation cannot be processed because of a programming error setting the `product_qty` field instead of the `product_uom_qty`.",
            ),
        )

    def _inverse_lot_ids(self):
        """
        Setting the lot_ids of a stock move should adapt the reservation following these rules:

        1. Removing a lot should remove its reference from sml but not the reserved quantity.
        2. Additional lots should be handled sequentially assigning the maximum between the
           remaining demand and the available quantity of the lot if none is available.
        """
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
        # When `quantity` is written in the same call as `lot_ids`, the
        # user-set value is kept and the recompute triggered by this
        # inverse rewriting `move_line_ids` does not override it. Force
        # the recompute to keep `quantity` in sync with the move lines.
        # Target the whole recordset (not the last loop iteration) so this
        # inverse behaves correctly when writing `lot_ids` on several moves.
        self.env.add_to_compute(self._fields["quantity"], self)

    def _inverse_description_picking(self):
        for move in self:
            move.description_picking_manual = move.description_picking

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("lot_ids")
    def _onchange_lot_ids(self):
        """
        Updates the quantity of the move to match the quantity resulting from the `_inverse_lot_ids`.
        """
        product = self.product_id
        if product.tracking == "none":
            return None

        assigned_quantity = 0
        assignable_quantity = 0
        nb_of_assignable_sml = 0
        new_lot_names = OrderedSet(lot.name for lot in self.lot_ids if lot.name)
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
        quant_domain = Domain(
            [
                ("product_id", "=", self.product_id.id),
                ("lot_id", "in", extra_lot_ids),
                ("quantity", "!=", 0),
                ("location_id.usage", "in", ("internal", "transit", "customer")),
                ("company_id", "in", (False, self.company_id.id)),
            ],
        )
        uom = self.product_uom_id
        minimal_quantity = product.uom_id._compute_quantity(1, uom)
        if self._should_bypass_reservation():
            nb_of_exceed = max(len(extra_lot_names) - nb_of_assignable_sml, 0)
            if nb_of_exceed > 0:
                quantity = max(
                    self.product_uom_qty,
                    quantity + nb_of_exceed * minimal_quantity,
                )
        else:
            qty_free = self.product_uom_qty - assigned_quantity
            available_quant_domain = Domain.AND(
                [quant_domain, Domain("location_id", "child_of", base_location.id)],
            )
            quant_by_lot = (
                self.env["stock.quant"]
                .sudo()
                ._read_group(
                    available_quant_domain,
                    ["lot_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
            )
            available_quantity_by_lot_name = defaultdict(float)
            for lot, total_quantity, reserved_quantity in quant_by_lot:
                available_quantity_by_lot_name[lot.name] += (
                    product.uom_id._compute_quantity(
                        total_quantity - reserved_quantity,
                        uom,
                    )
                )
            # Since each lot needs to be represented by a move line we will by default
            # reserve at least 1 unit (in the product.uom_id) for each lot
            qty_free -= len(new_lot_names - old_lot_names) * minimal_quantity
            new_assigned_quantity = (
                len(new_lot_names - old_lot_names) * minimal_quantity
            )
            for lot_name in extra_lot_names:
                if uom.compare(qty_free, 0.0) > 0:
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
            quantity += max(0, new_assigned_quantity - assignable_quantity)

        self.update({"quantity": quantity})

        if self.product_id.tracking == "serial":
            problematic_quant_domain = Domain.AND(
                [quant_domain, ~Domain("location_id", "child_of", base_location.id)],
            )
            problematic_quants = (
                self.env["stock.quant"].sudo().search(problematic_quant_domain)
            )
            if problematic_quants:
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
        return None

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_add_packages(self):
        """Opens a list of suitable packages to add to a picking."""
        picking = self.env["stock.picking"].browse(self.env.context.get("picking_id"))
        if not picking:
            raise UserError(self.env._("You need a transfer to add these packages to."))
        return {
            "name": self.env._("Select Packages to Move"),
            "type": "ir.actions.act_window",
            "res_model": "stock.package",
            "view_mode": "list",
            "views": [(self.env.ref("stock.view_stock_package_list_add").id, "list")],
            "target": "new",
            "domain": [("location_id", "child_of", picking.location_id.id)],
            "context": {
                "picking_id": picking.id,
            },
        }

    def action_show_details(self):
        """Returns an action that will open a form view (in a popup) allowing to work on all the
        move lines of a particular move. This form view is used when "show operations" is not
        checked on the picking type.
        """
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
                auto_pick_move_lines=self.picked,
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
        if not context_data.get("default_product_id"):
            raise UserError(_("No product found to generate Serials/Lots for."))
        if mode not in ("generate", "import"):
            # RPC-reachable method: a real exception, not an `assert` that
            # disappears under `python -O`.
            raise UserError(_("Invalid mode %s.", mode))
        default_vals = {}

        def generate_lot_qty(quantity, qty_per_lot):
            if qty_per_lot <= 0:
                raise UserError(
                    _("The quantity per lot should always be a positive value."),
                )
            line_count = int(quantity // qty_per_lot)
            leftover = quantity % qty_per_lot
            qty_array = [qty_per_lot] * line_count
            if leftover:
                qty_array.append(leftover)
            return qty_array

        def remove_prefix(text, prefix):
            if text.startswith(prefix):
                return text[len(prefix) :]
            return text

        for key in context_data:
            if key.startswith("default_"):
                default_vals[remove_prefix(key, "default_")] = context_data[key]

        # RPC boundary: the fields dereferenced below come straight from the
        # client-supplied context. A missing key must surface as a clean
        # UserError, not a raw KeyError -> Fault 500.
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

        if default_vals["tracking"] == "lot" and mode == "generate":
            lot_qties = generate_lot_qty(default_vals["quantity"], count)
        else:
            lot_qties = [1] * count

        if mode == "generate":
            lot_names = self.env["stock.lot"].generate_lot_names(
                first_lot,
                len(lot_qties),
            )
        elif mode == "import":
            lot_names = self.split_lots(lot_text)
            lot_qties = [1] * len(lot_names)

        vals_list = []
        loc_dest = self.env["stock.location"].browse(
            default_vals["location_dest_id"],
        )
        product = self.env["product.product"].browse(default_vals["product_id"])
        for lot, qty in zip(lot_names, lot_qties, strict=False):
            if not lot.get("quantity"):
                lot["quantity"] = qty
            putaway_loc_dest = loc_dest._get_putaway_strategy(product, lot["quantity"])
            vals_list.append(
                {
                    **default_vals,
                    **lot,
                    "location_dest_id": putaway_loc_dest.id,
                    "product_uom_id": default_vals.get("uom_id", product.uom_id.id),
                },
            )
        if default_vals.get("picking_type_id"):
            picking_type = self.env["stock.picking.type"].browse(
                default_vals["picking_type_id"],
            )
            if picking_type.use_existing_lots or context_data.get("force_lot_m2o"):
                # `default_company_id` is not guaranteed by every client context
                # (RPC boundary); the callee accepts a falsy company.
                self._create_lot_ids_from_move_line_vals(
                    vals_list,
                    default_vals["product_id"],
                    default_vals.get("company_id", False),
                )
        # format many2one values for webclient, id + display_name
        MoveLine = self.env["stock.move.line"]
        relational_fields = {
            f_name
            for f_name in MoveLine._fields
            if isinstance(MoveLine[f_name], models.Model)
        }
        # Resolve `display_name` with one browse per field (records prefetch
        # together) instead of one browse per value across every row (N+1).
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
        if product.lot_sequence_id and first_lot:
            current_sequence = product.lot_sequence_id._get_current_sequence()
            increment = product.lot_sequence_id.number_increment
            first_number = current_sequence.number_next_actual - increment
            final_number = first_number
            # Since the value might have been incremented by the "New" button of the "Generate Serial Numbers" wizard
            # we need to consider both the decremented and the current value of the sequence
            if first_lot == product.lot_sequence_id.get_next_char(first_number):
                final_number = first_number + len(lot_qties)
            elif first_lot == product.lot_sequence_id.get_next_char(
                first_number + increment
            ):
                final_number = first_number + increment + len(lot_qties)
            if first_number != final_number:
                current_sequence.sudo().write({"number_next_actual": final_number})
        return vals_list

    def _action_confirm(self, merge=True, merge_into=False, create_proc=True):
        """Confirms stock move or put it in waiting if it's linked to another move.
        :param: merge: According to this boolean, a newly confirmed move will be merged
        in another move of the same picking sharing its characteristics.
        """
        # Use OrderedSet of id (instead of recordset + |= ) for performance
        consumed_from_stock_dict = self.env.context.get(
            "consumed_from_stock_dict",
            defaultdict(float),
        )
        move_create_proc, move_to_confirm, move_waiting = (
            OrderedSet(),
            OrderedSet(),
            OrderedSet(),
        )
        to_assign = defaultdict(OrderedSet)
        for move in self:
            if move.state != "draft":
                continue
            # if the move is preceded, then it's waiting (if preceding move is done, then action_assign has been called already and its state is already available)
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
                key = (
                    frozenset(move.reference_ids.ids),
                    move.location_id.id,
                    move.location_dest_id.id,
                )
                to_assign[key].add(move.id)

        # create procurements for make to order moves
        procurement_requests = []
        move_create_proc = self.browse(move_create_proc)
        quantities = move_create_proc.with_context(
            consumed_from_stock_dict=consumed_from_stock_dict,
        )._prepare_procurement_qty()
        for move, quantity in zip(move_create_proc, quantities, strict=False):
            values = move._prepare_procurement_vals()
            origin = move._prepare_procurement_origin()
            procurement_requests.append(
                self.env["stock.rule"].Procurement(
                    move.product_id,
                    quantity,
                    move.product_uom_id,
                    move.location_id,
                    (move.rule_id and move.rule_id.name) or "/",
                    origin,
                    move.company_id,
                    values,
                ),
            )
        self.env["stock.rule"].with_context(
            consumed_from_stock_dict=consumed_from_stock_dict,
        ).run(
            procurement_requests,
            raise_user_error=not self.env.context.get("from_orderpoint"),
        )

        move_to_confirm, move_waiting = (
            self.browse(move_to_confirm).filtered(lambda m: m.state != "cancel"),
            self.browse(move_waiting).filtered(lambda m: m.state != "cancel"),
        )
        move_to_confirm.write({"state": "confirmed"})
        move_waiting.write({"state": "waiting"})
        # procure_method sometimes changes with certain workflows so just in case, apply to all moves
        (move_to_confirm | move_waiting).filtered(
            lambda m: m.picking_type_id.reservation_method == "at_confirm",
        ).write({"date_reservation": fields.Date.today()})

        # assign picking in batch for all confirmed move that share the same details
        for moves_ids in to_assign.values():
            self.browse(moves_ids).with_context(
                clean_context(self.env.context),
            )._assign_picking()

        self._check_company()
        moves = self
        if merge:
            moves = self._merge_moves(merge_into=merge_into)

        neg_r_moves = moves.filtered(
            lambda move: move.product_uom_id.compare(move.product_uom_qty, 0) < 0,
        )

        # Push remaining quantities to next step
        neg_to_push = neg_r_moves.filtered(
            lambda move: (
                move.location_final_id
                and move.location_dest_id != move.location_final_id
            ),
        )
        new_push_moves = self.env["stock.move"]
        if neg_to_push:
            new_push_moves = neg_to_push._push_apply()

        # Transform remaining moves into returns in case of negative initial demand
        neg_r_moves._reverse_negative_moves()

        # call `_action_assign` on every confirmed move which location_id bypasses the reservation + those expected to be auto-assigned
        moves.filtered(
            lambda move: (
                move.state in ("confirmed", "partially_available")
                and (
                    move._should_bypass_reservation()
                    or move._should_assign_at_confirm()
                )
            ),
        )._action_assign()
        if new_push_moves:
            neg_push_moves = new_push_moves.filtered(
                lambda sm: sm.product_uom_id.compare(sm.product_uom_qty, 0) < 0,
            )
            (new_push_moves - neg_push_moves).sudo()._action_confirm()
            # Negative moves do not have any picking, so we should try to merge it with their siblings
            neg_push_moves._action_confirm(
                merge_into=neg_push_moves.move_orig_ids.move_dest_ids,
            )
        return moves

    def action_view_reference(self):
        """Open the form view of the move's reference document, if one exists, otherwise open form view of self"""
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
        """Reserve stock moves by creating their stock move lines. A stock move is
        considered reserved once the sum of `quantity_product_uom` for all its move
        lines is equal to its `product_qty`. If it is less, the stock move is
        considered partially available.
        """
        StockMove = self.env["stock.move"]
        assigned_moves_ids = OrderedSet()
        partially_available_moves_ids = OrderedSet()
        # Snapshot each move's `quantity` before the loop to avoid cache invalidation
        # when the reservation writes below run.
        reserved_availability = {move: move.quantity for move in self}

        roundings = {move: move.product_id.uom_id.rounding for move in self}
        move_line_vals_list = []
        # Once the quantities are assigned, we want to find a better destination location thanks
        # to the putaway rules. This redirection will be applied on moves of `moves_to_redirect`.
        moves_to_redirect = OrderedSet()
        moves_to_assign = self
        if not force_qty:
            moves_to_assign = moves_to_assign.filtered(
                lambda m: (
                    not m.picked
                    and m.state in ["confirmed", "waiting", "partially_available"]
                ),
            )
        # Build the quants cache only for chained moves: the strict, exact-location
        # gather they use is the only path that reads it. Plain MTS moves (no origin)
        # reserve with strict=False against child locations and never consult the
        # cache; an un-scanned product/location now falls back to a DB search in
        # `_gather` (see `_QuantsCache`), so leaving them out is safe.
        moves_needing_reservation = moves_to_assign.filtered(
            lambda m: m.move_orig_ids and not m._should_bypass_reservation(),
        )
        quants_cache = self.env["stock.quant"]._get_quants_by_products_locations(
            moves_needing_reservation.product_id,
            moves_needing_reservation.location_id,
        )
        for move in moves_to_assign.with_context(quants_cache=quants_cache):
            move = move.with_company(move.company_id)
            rounding = roundings[move]
            if not force_qty:
                missing_reserved_uom_quantity = (
                    move.product_uom_qty - reserved_availability[move]
                )
            else:
                missing_reserved_uom_quantity = force_qty
            if (
                float_compare(
                    missing_reserved_uom_quantity,
                    0,
                    precision_rounding=rounding,
                )
                <= 0
            ):
                assigned_moves_ids.add(move.id)
                continue
            missing_reserved_quantity = move.product_uom_id._compute_quantity(
                missing_reserved_uom_quantity,
                move.product_id.uom_id,
                rounding_method="HALF-UP",
            )
            if move._should_bypass_reservation():
                move._assign_reserved_bypass(
                    missing_reserved_quantity,
                    move_line_vals_list,
                    assigned_moves_ids,
                    partially_available_moves_ids,
                    moves_to_redirect,
                )
            elif not move._assign_reserved_with_stock(
                missing_reserved_quantity,
                rounding,
                force_qty,
                assigned_moves_ids,
                partially_available_moves_ids,
                moves_to_redirect,
            ):
                continue
            if move.product_id.tracking == "serial":
                move.next_serial_count = move.product_uom_qty

        self.env["stock.move.line"].create(move_line_vals_list)
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
        moves_to_cancel.picked = False
        # moves_to_cancel excludes cancelled and done moves, so unreserving is always safe here.
        moves_to_cancel._do_unreserve()
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
                # only cancel the next move if all my siblings are also cancelled
                if all(state == "cancel" for state in siblings_states):
                    move_dest_to_cancel = move.move_dest_ids.filtered(
                        lambda m, move=move: (
                            m.state != "done" and move.location_dest_id == m.location_id
                        )
                    )
                    move_dest_to_cancel._action_cancel()
                    # Unlink from dest if dest is not in the chain
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
            # log an activity on the non-cancelled origin to warn the user that some actions might be required
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

        # Cancel moves where necessary ; we should do it before creating the extra moves because
        # this operation could trigger a merge of moves.
        ml_ids_to_unlink = OrderedSet()
        for move in moves:
            if move.picked:
                # in theory, we should only have a mix of picked and non-picked mls in the barcode use case
                # where non-scanned mls = not picked => we definitely don't want to validate them
                ml_ids_to_unlink |= move.move_line_ids.filtered(
                    lambda ml: not ml.picked,
                ).ids
            # `quantity` is cache-rounded at the "Product Unit" decimal
            # precision (see `_compute_quantity`), so a bare comparison with 0
            # cannot be thrown off by float residue.
            if (move.quantity <= 0 or not move.picked) and not move.is_inventory:
                if (
                    move.product_uom_id.compare(move.product_uom_qty, 0.0) == 0
                    or cancel_backorder
                ):
                    move._action_cancel()
        self.env["stock.move.line"].browse(ml_ids_to_unlink).unlink()

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
        # Check the consistency of the result packages; there should be a unique location across
        # the contained quants.
        for result_package in (
            moves_todo.move_line_ids.filtered(lambda ml: ml.picked)
            .mapped("result_package_id")
            .filtered(lambda p: p.quant_ids and len(p.quant_ids) > 1)
        ):
            if (
                len(
                    result_package.quant_ids.filtered(
                        lambda q: q.product_uom_id.compare(q.quantity, 0.0) > 0,
                    ).mapped("location_id"),
                )
                > 1
            ):
                raise UserError(
                    _(
                        "You cannot move the same package content more than once in the same transfer"
                        " or split the same package into two location.",
                    )
                    + _("\nPackage: %s", result_package.name)
                )
        if any(
            ml.package_id and ml.package_id == ml.result_package_id
            for ml in moves_todo.move_line_ids
        ):
            self.env["stock.quant"]._unlink_zero_quants()
        picking = moves_todo.mapped("picking_id")
        moves_todo.write({"state": "done", "date": fields.Datetime.now()})

        move_dests_per_company = defaultdict(lambda: self.env["stock.move"])

        # Break move dest link if move dest and move_dest source are not the same,
        # so that when move_dests._action_assign is called, the move lines are not created with
        # the new location, they should not be created at all.
        moves_to_push = moves_todo.filtered(lambda m: not m._skip_push())
        if moves_to_push:
            moves_to_push._push_apply()
        for move_dest in moves_todo.move_dest_ids:
            move_dests_per_company[move_dest.company_id.id] |= move_dest
        for company_id, move_dests in move_dests_per_company.items():
            move_dests.sudo().with_company(company_id)._action_assign()

        # We don't want to create back order for scrap moves
        # Replace by a kwarg in master
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

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _adjust_procure_method(self, picking_type_code=False):
        """Set procure_method to MTO if a compatible MTO route is found for the move,
        else fall back to MTS.

        :param picking_type_code: restrict the rule search to this picking type's code
        """
        # Memoize the resolved rule: moves for the same product/locations/
        # warehouse/packaging would otherwise repeat the whole hierarchy climb.
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
                    rule = self.env["stock.rule"]._search_rule(
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
            for i in range(int(quantity))
        ]

    def _apply_lot_ids_to_move_lines(self):
        """Rewrite this move's lines so that every lot in `lot_ids` is carried
        by a line: relabel/keep matching lines, drop lines whose lot was
        removed, then place each new lot (reserving stock unless reservation
        is bypassed) and rebalance the leftover lot-less lines.
        """
        self.ensure_one()
        product = self.product_id
        (
            move_lines_commands,
            available_move_lines,
            assigned_lot_ids,
            free_uom_qty,
        ) = self._classify_move_lines_for_lots()
        should_bypass_reservation = self._should_bypass_reservation()
        # Since each lot needs to be represented by a move line we will by default
        # reserve at least 1 unit (in the product.uom_id) for each lot the
        # exceeding free_uom_qty can then be assigned from available quantity
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
                    self._lot_commands_bypass(lot, available_move_lines, extra_uom_qty)
                )
            else:
                commands, extra_uom_qty = self._lot_commands_reserve(
                    lot,
                    quants_by_lot.get(lot, self.env["stock.quant"]),
                    extra_uom_qty,
                )
            move_lines_commands += commands
        if not should_bypass_reservation and available_move_lines:
            move_lines_commands += self._lot_commands_rebalance_unlotted(
                available_move_lines,
                extra_uom_qty,
            )
        self.write({"move_line_ids": move_lines_commands})

    def _assign_picking(self):
        """Try to assign the moves to an existing picking that has not been
        reserved yet and has the same procurement group, locations and picking
        type (moves should already have them identical). Otherwise, create a new
        picking to assign them to.
        """
        Picking = self.env["stock.picking"]
        grouped_moves = groupby(self, key=lambda m: m._key_assign_picking())
        for _group, moves in grouped_moves:
            moves = self.env["stock.move"].concat(*moves)
            new_picking = False
            # moves[0] is representative: all moves in the group share the same key fields.
            picking = moves[0]._search_picking_for_assignation()
            if picking:
                # If a picking is found, we'll append `move` to its move list and thus its
                # `partner_id` and `ref` field will refer to multiple records. In this
                # case, we chose to wipe them.
                vals = moves._assign_picking_values(picking)
                if vals:
                    picking.write(vals)
            else:
                # Don't create a picking for negative moves since they will be
                # reversed and assigned to another picking.
                moves = moves.filtered(
                    lambda m: m.product_uom_id.compare(m.product_uom_qty, 0.0) >= 0,
                )
                if not moves:
                    continue
                new_picking = True
                picking = Picking.create(moves._get_new_picking_values())

            moves.write({"picking_id": picking.id})
            moves._assign_picking_post_process(new=new_picking)
        return True

    def _assign_picking_values(self, picking):
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

    def _assign_picking_post_process(self, new=False):
        pass

    def _assign_reserved_bypass(
        self,
        missing_reserved_quantity,
        move_line_vals_list,
        assigned_moves_ids,
        partially_available_moves_ids,
        moves_to_redirect,
    ):
        """Reserve a move whose source location bypasses reservation (or whose
        product is not storable): create the move line(s) without impacting quants.

        Extracted from `_action_assign`; mutates the passed accumulators in place.
        """
        self.ensure_one()
        # create the move line(s) but do not impact quants
        if self.move_orig_ids:
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

        if (
            missing_reserved_quantity
            and self.product_id.tracking == "serial"
            and (
                self.picking_type_id.use_create_lots
                or self.picking_type_id.use_existing_lots
            )
        ):
            for _i in range(int(missing_reserved_quantity)):
                move_line_vals_list.append(
                    self._prepare_move_line_vals(quantity=1),
                )
        elif missing_reserved_quantity:
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
        assigned_moves_ids.add(self.id)
        moves_to_redirect.add(self.id)

    def _assign_reserved_with_stock(
        self,
        missing_reserved_quantity,
        rounding,
        force_qty,
        assigned_moves_ids,
        partially_available_moves_ids,
        moves_to_redirect,
    ):
        """Reserve a move against real quants: either a plain MTS move (no origin)
        or a chained move distributing what its done origins brought.

        Extracted from `_action_assign`; mutates the passed accumulators in place
        and returns whether the caller should keep processing this move. Returning
        ``False`` replicates the ``continue`` the original inline code used to skip
        the trailing per-move bookkeeping.
        """
        self.ensure_one()
        if self.product_uom_id.is_zero(self.product_uom_qty) and not force_qty:
            assigned_moves_ids.add(self.id)
        elif not self.move_orig_ids:
            if self.procure_method == "make_to_order":
                return False
            # If we don't need any quantity, consider the move assigned.
            need = missing_reserved_quantity
            if float_is_zero(need, precision_rounding=rounding):
                assigned_moves_ids.add(self.id)
                return False
            taken_quantity = self._update_reserved_quantity(
                need,
                self.location_id,
                strict=False,
            )
            if float_is_zero(taken_quantity, precision_rounding=rounding):
                return False
            moves_to_redirect.add(self.id)
            if float_compare(need, taken_quantity, precision_rounding=rounding) == 0:
                assigned_moves_ids.add(self.id)
            else:
                partially_available_moves_ids.add(self.id)
        else:
            # Check what our parents brought and what our siblings took in order to
            # determine what we can distribute.
            # `quantity` is in `ml.product_uom_id` and, as we will later increase
            # the reserved quantity on the quants, convert it here in
            # `product_id.uom_id` (the UOM of the quants is the UOM of the product).
            available_move_lines = self._get_available_move_lines(
                assigned_moves_ids,
                partially_available_moves_ids,
            )
            if not available_move_lines:
                return False
            for move_line in self.move_line_ids.filtered(
                lambda m: m.quantity_product_uom,
            ):
                if available_move_lines.get(
                    (
                        move_line.location_id,
                        move_line.lot_id,
                        move_line.package_id,
                        move_line.owner_id,
                    ),
                ):
                    available_move_lines[
                        move_line.location_id,
                        move_line.lot_id,
                        move_line.package_id,
                        move_line.owner_id,
                    ] -= move_line.quantity_product_uom

            # Snapshot the reserved quantity once. `_update_reserved_quantity_vals`
            # increases matching existing lines in place, so re-reading the lines
            # inside the loop while also subtracting the returned takes counted
            # the update-path share twice (silently under-reserving the next
            # keys), and an update-only take never reached the state bookkeeping
            # (leaving a fully reserved move written back as partially
            # available).
            initial_reserved_qty = sum(
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
                need = self.product_qty - initial_reserved_qty - taken_qty_total
                if float_compare(need, 0, precision_rounding=rounding) <= 0:
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
                # `taken_quantity` covers both the lines updated in place and the
                # new lines created below: count each take exactly once.
                taken_qty_total += taken_quantity
            if all_move_line_vals:
                self.env["stock.move.line"].create(all_move_line_vals)

            # The takes were double-checked against the quants themselves inside
            # `_update_reserved_quantity_vals`: what the chained done moves
            # brought may no longer be fully available (e.g. after an inventory
            # adjustment), in which case the maximum still available was
            # reserved. This cannot happen on an MTS move, whose need is
            # measured on the quants directly.
            if not float_is_zero(taken_qty_total, precision_rounding=rounding):
                moves_to_redirect.add(self.id)
                if (
                    float_compare(
                        self.product_qty - initial_reserved_qty - taken_qty_total,
                        0,
                        precision_rounding=rounding,
                    )
                    <= 0
                ):
                    assigned_moves_ids.add(self.id)
                else:
                    partially_available_moves_ids.add(self.id)
        return True

    def _reverse_negative_moves(self):
        """Turn moves confirmed with a negative initial demand into positive
        moves in the opposite direction (a return), rewiring the chain links
        to match the new direction, then assign them to a picking.
        """
        for move in self:
            move.location_id, move.location_dest_id, move.location_final_id = (
                move.location_dest_id,
                move.location_id,
                move.location_id,
            )
            orig_move_ids, dest_move_ids = [], []
            for m in move.move_orig_ids | move.move_dest_ids:
                from_loc, to_loc = m.location_id, m.location_dest_id
                if m.product_uom_id.compare(m.product_uom_qty, 0) < 0:
                    from_loc, to_loc = to_loc, from_loc
                if to_loc == move.location_id:
                    orig_move_ids += m.ids
                elif move.location_dest_id == from_loc:
                    dest_move_ids += m.ids
            move.move_orig_ids, move.move_dest_ids = (
                [Command.set(orig_move_ids)],
                [Command.set(dest_move_ids)],
            )
            move.product_uom_qty *= -1
            if move.picking_type_id.return_picking_type_id:
                move.picking_type_id = move.picking_type_id.return_picking_type_id
            # We are returning some products, we must take them in the source location
            move.procure_method = "make_to_stock"
        self._assign_picking()

    def _break_mto_link(self, parent_move):
        self.move_orig_ids = [Command.unlink(parent_move.id)]
        self.procure_method = "make_to_stock"
        self._recompute_state()

    def _classify_move_lines_for_lots(self):
        """Match the existing move lines against `lot_ids`.

        :return: a 4-tuple of
            - the initial commands (relabel matching lines, delete lines whose
              lot is no longer wanted),
            - the lines carrying no lot at all (usable to place new lots),
            - the ids of the lots already carried by a line,
            - the remaining demand, in the product's UoM, not consumed by the
              matched lines.
        """
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
        """Cleanup hook used when merging moves"""
        self.write({"propagate_cancel": False})

    def _create_backorder(self):
        """Split off the undone quantity of each move in `self` into a backorder move."""
        backorder_moves_vals = []
        # To know whether we need to create a backorder or not, round to the general product's
        # decimal precision and not the product's UOM.
        rounding = self.env["decimal.precision"].precision_get("Product Unit")
        for move in self:
            if (
                float_compare(
                    move.quantity,
                    move.product_uom_qty,
                    precision_digits=rounding,
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
        # The backorder moves are not yet in their own picking. We do not want to check entire packs for those
        # ones as it could mess up the result_package_id of the moves being currently validated
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
        """Search or create the lot from `lot_name` and set `lot_id` in `vals_list`."""
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
        lot_names = [
            lot_name for lot_name in lot_names if lot_name not in lot_id_names
        ]  # lot_names not found to create
        lots_to_create_vals = [
            {"product_id": product_id, "name": lot_name} for lot_name in lot_names
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
        """Convert one pasted lot-line token into move line values.

        Contract (overrides extend it, e.g. `product_expiry` parses dates):
        - a dict of move line values when the token was recognized;
        - the string ``"ignore"`` when the token was recognized but does not
          apply to this move (keep the lot name, drop the token);
        - ``False`` when the token could not be parsed at all.
        """
        string = string.replace(
            ",",
            ".",
        )  # Parsing string as float works only with dot, not comma.
        if regex_findall(
            r"^([0-9]+\.?[0-9]*|\.[0-9]+)$",
            string,
        ):  # Number => Quantity.
            return {"quantity": float(string)}
        return False

    def _delay_alert_get_documents(self):
        """Returns a list of recordset of the documents linked to the stock.move in `self` in order
        to post the delay alert next activity. These documents are deduplicated. This method is meant
        to be overridden by other modules, each of them adding an element by type of recordset on
        this list.

        :return: a list of recordset of the documents linked to `self`
        :rtype: list
        """
        return list(self.mapped("picking_id"))

    def _do_unreserve(self):
        moves_to_unreserve = OrderedSet()
        for move in self:
            if (
                move.state == "cancel"
                or (move.state == "done" and move.location_dest_usage == "inventory")
                or move.picked
            ):
                # We may have cancelled move in an open picking in a "propagate_cancel" scenario.
                # We may have done move in an open picking in a scrap scenario.
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
            if ml.picked:
                moves_not_to_recompute.add(ml.move_id.id)
                continue
            ml_to_unlink.add(ml.id)
        ml_to_unlink = self.env["stock.move.line"].browse(ml_to_unlink)
        moves_not_to_recompute = self.env["stock.move"].browse(moves_not_to_recompute)

        ml_to_unlink.unlink()
        # Unlinking the lines above already recomputed the state of their moves;
        # run it explicitly for the remaining ones (e.g. moves without any move
        # line, which the unlink never saw), skipping the moves whose picked
        # lines were deliberately kept.
        (moves_to_unreserve - moves_not_to_recompute)._recompute_state()
        return True

    def _generate_serial_numbers(
        self,
        next_serial,
        next_serial_count=False,
        location_id=False,
    ):
        """Generate `lot_name` values from `next_serial` and create a move line for each.

        :param location_id: optional destination to force on the created move
            lines; when not given, the putaway strategy decides per line.
        """
        self.ensure_one()
        count = next_serial_count or self.next_serial_count
        if not count:
            raise ValidationError(
                _(
                    "The number of Serial Numbers to generate must be greater than zero.",
                ),
            )
        lot_names = self.env["stock.lot"].generate_lot_names(next_serial, count)
        field_data = [
            {"lot_name": lot_name["lot_name"], "quantity": 1} for lot_name in lot_names
        ]
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
        """Return a list of commands to update the move lines (write on
        existing ones or create new ones).
        Called when user want to create and assign multiple serial numbers in
        one time (using the button/wizard or copy-paste a list in the field).

        :param field_data: A list containing dict with at least `lot_name` and `quantity`
        :type field_data: list
        :param origin_move_line: A move line to duplicate the value from, empty record by default
        :type origin_move_line: record of :class:`stock.move.line`
        :return: A list of commands to create/update :class:`stock.move.line`
        :rtype: list
        """
        self.ensure_one()
        origin_move_line = origin_move_line or self.env["stock.move.line"]
        loc_dest = origin_move_line.location_dest_id or location_dest_id
        move_line_vals = {
            "picking_id": self.picking_id.id,
            "location_id": self.location_id.id,
            "product_id": self.product_id.id,
            "product_uom_id": self.product_id.uom_id.id,
        }
        # Reuse existing move lines that don't have a lot/serial name set yet.
        move_lines = self.move_line_ids.filtered(
            lambda ml: not ml.lot_id and not ml.lot_name,
        )

        if origin_move_line:
            # Copies `owner_id` and `package_id` if new move lines are created from an existing one.
            move_line_vals.update(
                {
                    "owner_id": origin_move_line.owner_id.id,
                    "package_id": origin_move_line.package_id.id,
                },
            )

        move_lines_commands = []
        qty_by_location = defaultdict(float)
        for command_vals in field_data:
            quantity = command_vals["quantity"]
            # We write the lot name on an existing move line (if we have still one)...
            if move_lines:
                move_lines_commands.append(
                    Command.update(move_lines[0].id, command_vals),
                )
                qty_by_location[move_lines[0].location_dest_id.id] += quantity
                move_lines = move_lines[1:]
            # ... or create a new move line with the serial name.
            else:
                loc = loc_dest or self.location_dest_id._get_putaway_strategy(
                    self.product_id,
                    quantity=quantity,
                    additional_qty=qty_by_location,
                )
                new_move_line_vals = {
                    **move_line_vals,
                    **command_vals,
                    "location_dest_id": loc.id,
                }
                move_lines_commands.append(Command.create(new_move_line_vals))
                qty_by_location[loc.id] += quantity
        return move_lines_commands

    def _get_description(self):
        product = self.product_id.with_context(lang=self._get_lang())
        return product._get_description(self.picking_type_id)

    def _get_partner_id(self):
        self.ensure_one()
        if self.location_id == self.env.company.internal_transit_location_id:
            return self.location_dest_id.warehouse_id.partner_id.id
        return self.partner_id.id

    def _get_relevant_state_among_moves(self):
        # Sort moves from least to most advanced state (confirmed < partially_available
        # < waiting < assigned) so index 0 is the one still blocking the picking.
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
        # The picking should be the same for all moves.
        if moves_todo[:1].picking_id and moves_todo[:1].picking_id.move_type == "one":
            if all(not m.product_uom_qty for m in moves_todo):
                return "assigned"
            most_important_move = moves_todo[0]
            if most_important_move.state in ("confirmed", "partially_available"):
                return "confirmed"
            return moves_todo[:1].state or "draft"
        if moves_todo[:1].state != "assigned" and any(
            move.state in ["assigned", "partially_available"] for move in moves_todo
        ):
            return "partially_available"
        least_important_move = moves_todo[-1:]
        if (
            least_important_move.state == "confirmed"
            and least_important_move.product_uom_qty == 0
        ):
            return "assigned"
        return moves_todo[-1:].state or "draft"

    def _get_formatting_options(self, strings):
        return {}

    def _get_new_picking_values(self):
        """Return the create values for a new picking linking the group of moves in self."""
        origins = self.filtered(lambda m: m.origin).mapped("origin")
        origins = list(dict.fromkeys(origins))  # dedupe, preserving order
        # Cap the displayed source document list at 5 origins when several differ.
        if len(origins) == 0:
            origin = False
        else:
            origin = ",".join(origins[:5])
            if len(origins) > 5:
                origin += "..."
        partners = self.mapped("partner_id")
        partner = (len(partners) == 1 and partners.id) or False
        vals = {
            "origin": origin,
            "company_id": self.mapped("company_id").id,
            "user_id": False,
            "partner_id": partner,
            "picking_type_id": self.mapped("picking_type_id").id,
            "location_id": self.mapped("location_id").id,
        }
        if self.location_dest_id.ids:
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

    # Hook so other modules can override reservation to restrict lot, owner, pack, location...
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
        move_lines_out_done = (
            (self.move_orig_ids.mapped("move_dest_ids") - self)
            .filtered(lambda m: m.state == "done")
            .mapped("move_line_ids")
        )
        # As we defer the write on the stock.move's state at the end of the loop, there
        # could be moves to consider in what our siblings already took.
        StockMove = self.env["stock.move"]
        moves_out_siblings = self.move_orig_ids.mapped("move_dest_ids") - self
        moves_out_siblings_to_consider = moves_out_siblings & (
            StockMove.browse(assigned_moves_ids)
            + StockMove.browse(partially_available_moves_ids)
        )
        reserved_moves_out_siblings = moves_out_siblings.filtered(
            lambda m: m.state in ["partially_available", "assigned"],
        )
        move_lines_out_reserved = (
            reserved_moves_out_siblings | moves_out_siblings_to_consider
        ).mapped("move_line_ids")

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
            grouped_move_lines_out[k] = sum(
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
        # Drop entries whose available quantity is not strictly positive.
        rounding = self.product_id.uom_id.rounding
        return {
            k: v
            for k, v in available_move_lines.items()
            if float_compare(v, 0, precision_rounding=rounding) > 0
        }

    def _get_lang(self):
        """Determine language to use for translated description"""
        return (
            self.picking_id.partner_id.lang
            or self.partner_id.lang
            or self.env.user.lang
        )

    def _get_source_document(self):
        """Return the move's document, used by `stock.forecasted_product_product`;
        override to add more document types to the report.
        """
        self.ensure_one()
        return self.picking_id or False

    def _get_upstream_documents_and_responsibles(self, visited):
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
        """Get forecasted information (sum_qty_expected, max_date_expected) of self for the warehouse's locations.
        :param warehouse: warehouse to search under
        :param  location_id: location source of outgoing moves
        :return: a defaultdict of outgoing moves from warehouse for product_id in self, values are tuple (sum_qty_expected, max_date_expected)
        :rtype: defaultdict
        """
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
        # The displayed unit is the move's UoM for a single move and the
        # product's UoM otherwise; express the quantity in that same unit.
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
        # `company_id` keeps each group mono-company: shared locations and
        # picking types (company_id unset) would otherwise let moves of several
        # companies share one picking, and `_get_new_picking_values` reads
        # `self.company_id.id` on the whole group.
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

    def _lot_commands_bypass(self, lot, available_move_lines, extra_uom_qty):
        """Place `lot` without touching quants (reservation is bypassed):
        relabel an existing lot-less line when possible, else create one.

        :return: (commands, remaining lot-less lines, remaining extra quantity)
        """
        self.ensure_one()
        product = self.product_id
        uom = product.uom_id if product.tracking == "serial" else self.product_uom_id
        if available_move_lines:
            # Updates an existing line without lot.
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
            # No line to update creates a new one.
            quantity_to_reserve = 1.0
            # For lot tracked product reserve the maximal available quantity
            if (
                product.tracking == "lot"
                and product.uom_id.compare(extra_uom_qty, 0.0) > 0
            ):
                quantity_to_reserve += extra_uom_qty
                extra_uom_qty = 0
            move_line_vals = self._prepare_move_line_vals(
                quantity=quantity_to_reserve,
            )
            move_line_vals.update({"lot_id": lot.id, "lot_name": lot.name})
            if product.tracking == "serial":
                move_line_vals.update(
                    {"quantity": 1.0, "product_uom_id": product.uom_id.id},
                )
            commands = [Command.create(move_line_vals)]
        return commands, available_move_lines, extra_uom_qty

    def _lot_commands_reserve(self, lot, quants, extra_uom_qty):
        """Place `lot` by reserving against `quants`; when no quant has
        availability, still create a 1-unit line so the lot is represented.

        :return: (commands, remaining extra quantity)
        """
        self.ensure_one()
        product = self.product_id
        commands = []
        reserved = False
        for quant in quants:
            if reserved and product.uom_id.compare(extra_uom_qty, 0.0) <= 0:
                break
            if (
                not quant.lot_id
                or product.uom_id.compare(quant.available_quantity, 0.0) <= 0
            ):
                continue
            quantity_to_reserve = min(
                quant.available_quantity,
                max(extra_uom_qty if reserved else extra_uom_qty + 1, 1),
            )
            if product.uom_id.compare(quantity_to_reserve, 0.0) > 0:
                move_line_vals = self._prepare_move_line_vals(
                    quantity=quantity_to_reserve,
                    reserved_quant=quant,
                )
                move_line_vals.update({"lot_id": lot.id, "lot_name": lot.name})
                if product.tracking == "serial":
                    quantity_to_reserve = 1
                    move_line_vals.update(
                        {"quantity": 1.0, "product_uom_id": product.uom_id.id},
                    )
                commands.append(Command.create(move_line_vals))
                extra_uom_qty -= (
                    quantity_to_reserve if reserved else quantity_to_reserve - 1
                )
                reserved = True
        if not reserved:
            move_line_vals = self._prepare_move_line_vals(quantity=1.0)
            move_line_vals.update({"lot_id": lot.id, "lot_name": lot.name})
            if product.tracking == "serial":
                move_line_vals.update(
                    {"quantity": 1.0, "product_uom_id": product.uom_id.id},
                )
            commands.append(Command.create(move_line_vals))
        return commands, extra_uom_qty

    def _lot_commands_rebalance_unlotted(self, available_move_lines, extra_uom_qty):
        """Unlink and re-create the lot-less move lines (capped to the
        remaining extra quantity) to alter the reservation order and
        prioritise lot-set move lines in the un-reservation process relying
        on the process decrease.

        :return: commands
        """
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

    def _match_searched_availability(self, operator, value, get_comparison_date):
        def get_stock_moves(moves, state):
            if state == "available":
                return moves.filtered(
                    lambda m: (
                        m.forecast_availability == m.product_qty
                        and not m.date_planned_forecast
                    ),
                )
            if state == "expected":
                return moves.filtered(
                    lambda m: (
                        m.forecast_availability == m.product_qty
                        and m.date_planned_forecast
                        and m.date_planned_forecast <= get_comparison_date(m)
                    ),
                )
            if state == "late":
                return moves.filtered(
                    lambda m: (
                        m.forecast_availability == m.product_qty
                        and m.date_planned_forecast
                        and m.date_planned_forecast > get_comparison_date(m)
                    ),
                )
            if state == "unavailable":
                return (
                    moves
                    if moves.filtered(lambda m: m.forecast_availability < m.product_qty)
                    else self.env["stock.move"]
                )
            raise UserError(_("Selection not supported."))

        if not value:
            raise UserError(_("Search not supported without a value."))

        # We consider an operation without any moves as always available since there is no goods to wait.
        if len(self) == 0:
            is_selected_available = (
                any(val == "available" for val in value)
                if isinstance(value, list)
                else value == "available"
            )
            return is_selected_available == (operator in {"=", "in"})
        moves = self
        if operator == "=":
            moves = get_stock_moves(moves, value)
        elif operator == "!=":
            moves = moves - get_stock_moves(moves, value)
        elif operator == "in":
            search_moves = self.env["stock.move"]
            for state in value:
                search_moves |= get_stock_moves(moves, state)
            moves = search_moves
        elif operator == "not in":
            search_moves = self.env["stock.move"]
            for state in value:
                search_moves |= get_stock_moves(moves, state)
            moves = self - search_moves
        else:
            raise UserError(_("Operation not supported"))
        return bool(moves)

    def _merge_moves_fields(self):
        """Return a dict of stock move values merging all the moves in `self`."""
        state = self._get_relevant_state_among_moves()
        # `dict.fromkeys` dedupes while preserving order: a plain `set` iterates in
        # a hash-seed-dependent order, making the merged `origin` non-reproducible
        # across runs (and across the `_get_new_picking_values` path, which already
        # uses this order-preserving form).
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
        fields = set(distinct_fields or []) - set(excluded_fields or [])
        float_fields = {
            f_name
            for f_name in fields
            if self.env["stock.move"]._fields[f_name].type == "float"
        }
        # Always build a tuple key. `itemgetter(*names)` returns a *scalar* for a
        # single name and raises for zero, which would break the `base_getter(move)
        # + tuple(...)` concatenation below or the call itself as soon as an
        # override trims `distinct_fields` down to one non-float field.
        non_float_fields = tuple(fields - float_fields)

        def base_getter(move):
            return tuple(move[f_name] for f_name in non_float_fields)

        if not float_fields:
            return base_getter

        float_precision = {
            f_name: (
                self.env["stock.move"]._fields[f_name].get_digits(self.env)
                or (False, 2)
            )[1]
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
            # Round and cast the value of move.f_name into a string so that rounding errors do not prevent the merge
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
        """This method will, for each move in `self`, go up in their linked picking and try to
        find in their existing moves a candidate into which we can merge the move.
        :return: Recordset of moves passed to this method. If some of the passed moves were merged
        into another existing one, return this one and not the (now unlinked) original.
        """
        candidate_moves_set = set()
        if not merge_into:
            self._update_candidate_moves_list(candidate_moves_set)
        else:
            candidate_moves_set.add(merge_into | self)

        distinct_fields = (
            self | self.env["stock.move"].concat(*candidate_moves_set)
        )._prepare_merge_moves_distinct_fields()

        # Need to check less fields for negative moves as some might not be set.
        neg_qty_moves = self.filtered(
            lambda m: m.product_uom_id.compare(m.product_qty, 0.0) < 0,
        )
        # Detach their picking as they will either get absorbed or create a backorder, so no extra logs will be put in the chatter
        neg_qty_moves.picking_id = False
        excluded_fields = self._prepare_merge_negative_moves_excluded_distinct_fields()
        neg_key = self._merge_move_itemgetter(distinct_fields, excluded_fields)

        # Phase 1: fold same-key positive moves within each candidate group.
        moves_to_unlink, merged_moves, moves_by_neg_key = self._merge_positive_moves(
            candidate_moves_set,
            distinct_fields,
            neg_qty_moves,
            neg_key,
        )
        # Phase 2: let the surviving positive moves absorb the negative ones.
        absorbed_moves, neg_to_unlink, moves_to_cancel = (
            self._merge_absorb_negative_moves(neg_qty_moves, moves_by_neg_key, neg_key)
        )
        merged_moves |= absorbed_moves
        moves_to_unlink |= neg_to_unlink

        # Reset propagate_cancel so cancelling/unlinking these moves doesn't cascade
        # to the destination moves that got merged into moves[0].
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
        """First merge phase: within each candidate group, fold every set of
        same-key positive moves into a single kept move (record 0), relinking
        their move lines onto it and marking the rest for removal.

        :return: a 3-tuple of
            - the redundant moves to unlink,
            - the kept (merged) moves,
            - a map of each kept move's negative-merge key to that move, used by
              `_merge_absorb_negative_moves` to locate absorbers.
        """
        moves_to_unlink = self.env["stock.move"]
        merged_moves = self.env["stock.move"]
        moves_by_neg_key = defaultdict(lambda: self.env["stock.move"])
        for candidate_moves in candidate_moves_set:
            # First step find move to merge.
            candidate_moves = (
                candidate_moves.filtered(
                    lambda m: m.state not in ("done", "cancel", "draft"),
                )
                - neg_qty_moves
            )
            for __, g in groupby(
                candidate_moves,
                key=self._merge_move_itemgetter(distinct_fields),
            ):
                moves = self.env["stock.move"].concat(*g)
                if len(moves) > 1:
                    # Link all move lines to record 0 (the one we will keep).
                    moves.mapped("move_line_ids").write({"move_id": moves[0].id})
                    moves[0].write(moves._merge_moves_fields())
                    moves_to_unlink |= moves[1:]
                    merged_moves |= moves[0]
                # Index the resulting single positive move by its negative-move merge key
                # so it can absorb matching negative moves below.
                moves_by_neg_key[neg_key(moves[0])] |= moves[0]
        return moves_to_unlink, merged_moves, moves_by_neg_key

    def _merge_absorb_negative_moves(self, neg_qty_moves, moves_by_neg_key, neg_key):
        """Second merge phase: let each positive move absorb the negative-demand
        moves sharing its limited (negative) key, adjusting quantities and unit
        prices and rewiring the chain links.

        :return: a 3-tuple of (moves that absorbed something, negative moves to
            unlink, positive moves left at zero demand to cancel).
        """
        merged_moves = self.env["stock.move"]
        moves_to_unlink = self.env["stock.move"]
        moves_to_cancel = self.env["stock.move"]
        price_unit_prec = self.env["decimal.precision"].precision_get("Product Price")
        for neg_move in neg_qty_moves:
            # Check all the candidates that matches the same limited key, and adjust their quantities to absorb negative moves
            for pos_move in moves_by_neg_key.get(neg_key(neg_move), []):
                new_total_value = (
                    pos_move.product_qty * pos_move.price_unit
                    + neg_move.product_qty * neg_move.price_unit
                )
                # If quantity can be fully absorbed by a single move, update its quantity and remove the negative move
                if (
                    pos_move.product_uom_id.compare(
                        pos_move.product_uom_qty,
                        abs(neg_move.product_uom_qty),
                    )
                    >= 0
                ):
                    # Single write: each `stock.move` write re-runs the whole
                    # unreserve/orderpoint/state orchestration.
                    new_product_qty = pos_move.product_qty + neg_move.product_qty
                    pos_move.write(
                        {
                            "product_uom_qty": pos_move.product_uom_qty
                            + neg_move.product_uom_qty,
                            "price_unit": (
                                float_round(
                                    new_total_value / new_product_qty,
                                    precision_digits=price_unit_prec,
                                )
                                if new_product_qty
                                else 0
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
                        "price_unit": float_round(
                            new_total_value
                            / (neg_move.product_qty + pos_move.product_qty),
                            precision_digits=price_unit_prec,
                        ),
                    },
                )
                pos_move.product_uom_qty = 0
                moves_to_cancel |= pos_move
        return merged_moves, moves_to_unlink, moves_to_cancel

    def _on_demand_change(self, vals):
        """Log the demand change and unreserve moves whose reservation now
        exceeds the new demand. Runs before the write, on the old quantities.

        :return: (receipt moves to re-assign after the write,
                  moves whose state must be recomputed after the write)
        """
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
        (self - move_to_unreserve).filtered(
            lambda m: m.state == "assigned",
        ).write({"state": "partially_available"})
        # When editing the initial demand, directly run again action assign on receipt moves.
        receipt_moves_to_reassign = move_to_unreserve.filtered(
            lambda m: m.location_id.usage == "supplier",
        )
        receipt_moves_to_reassign |= (self - move_to_unreserve).filtered(
            lambda m: (
                m.location_id.usage == "supplier"
                and m.state in ("partially_available", "assigned")
            ),
        )
        move_to_recompute_state = self - move_to_unreserve - receipt_moves_to_reassign
        return receipt_moves_to_reassign, move_to_recompute_state

    def _on_source_location_change(self):
        """Called after a write changed the moves' source location: drop the
        move lines whose own source is no longer under it and detach the
        moves from their origin chain.

        :return: the moves that must be re-assigned
        """
        mls_to_unlink = self.move_line_ids.filtered(
            lambda ml: not ml.location_id._child_of(ml.move_id.location_id),
        )
        if not mls_to_unlink:
            return self.browse()
        # Only reset the moves that actually lost a line: a batched write applies
        # the same source location to every move in `self`, but a sibling whose
        # lines are still under the new location must keep its chain/procure
        # method untouched (upstream reset the whole batch indiscriminately).
        affected = mls_to_unlink.move_id
        affected.procure_method = "make_to_stock"
        affected.move_orig_ids = [Command.clear()]
        mls_to_unlink.unlink()
        return affected

    def _post_process_created_moves(self):
        """Hook for moves auto-created alongside move lines (e.g. via the barcode app)
        that bypass `_action_confirm` and so never run its post-creation logic.
        """
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

        # Get the forecasted quantity for the `mts_else_mto` procurement.
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
        """Prepare values for the procurement created from this move by a stock rule.
        Meant to be overridden to add custom keys used in move/PO creation.
        """
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
            # TODO CLPI: maybe make this a little cleaner
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
            "procurement_values": self.procurement_values,
        }

    def _uom_quantity_if_faithful(self, quantity, to_uom):
        """Convert `quantity` (expressed in the product's UoM) into `to_uom`.

        :return: the converted quantity, rounded at the "Product Unit"
            precision, or ``None`` when `to_uom` cannot faithfully represent
            `quantity` (converting back diverges) and the caller should keep
            working in the product's UoM.
        """
        self.ensure_one()
        digits = self.env["decimal.precision"].precision_get("Product Unit")
        uom_quantity = self.product_id.uom_id._compute_quantity(
            quantity,
            to_uom,
            rounding_method="HALF-UP",
        )
        uom_quantity = float_round(uom_quantity, precision_digits=digits)
        back_to_product_uom = to_uom._compute_quantity(
            uom_quantity,
            self.product_id.uom_id,
            rounding_method="HALF-UP",
        )
        if float_compare(quantity, back_to_product_uom, precision_digits=digits) == 0:
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
            # TODO could be also move in create/write
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

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        fields = [
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
            fields.append("date")
        if (
            not self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.merge_ignore_date_deadline")
        ):
            fields.append("date_deadline")
        return fields

    @api.model
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

    def _propagate_date_log_note(self, move_orig):
        """Post a deadline change alert log note on the documents linked to `self`."""
        # TODO : get the end document (PO/SO/MO)
        doc_orig = move_orig._delay_alert_get_documents()
        documents = self._delay_alert_get_documents()
        if not documents or not doc_orig:
            return

        msg = _(
            "The deadline has been automatically updated due to a delay on %s.",
            doc_orig[0]._get_html_link(),
        )
        msg_subject = _("Deadline updated due to delay on %s", doc_orig[0].name)
        for doc in documents:
            last_message = doc.message_ids[:1]
            # Avoid posting the exact same message multiple times.
            if last_message and last_message.subject == msg_subject:
                continue
            odoobot_id = self.env["ir.model.data"]._xmlid_to_res_id("base.partner_root")
            doc.message_post(body=msg, author_id=odoobot_id, subject=msg_subject)

    def _push_apply(self):
        depth = self.env.context.get("_push_apply_depth", 0) + 1
        if depth > self._MAX_PUSH_DEPTH:
            raise UserError(
                _(
                    "Push rules recursion limit reached. Check for circular push rules in your warehouse configuration."
                )
            )
        self = self.with_context(_push_apply_depth=depth)
        new_moves = []
        for move in self:
            new_move = self.env["stock.move"]

            # if the move is a returned move, we don't want to check push rules, as returning a returned move is the only decent way
            # to receive goods without triggering the push rules again (which would duplicate chained operations)
            # first priority goes to the preferred routes defined on the move itself (e.g. coming from a SO line)
            warehouse_id = (
                move.warehouse_id or move.picking_id.picking_type_id.warehouse_id
            )

            StockRule = self.env["stock.rule"]
            if move.location_dest_id.company_id not in self.env.companies:
                StockRule = self.env["stock.rule"].sudo()
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

            rule = StockRule._get_push_rule(
                move.product_id,
                move.location_dest_id,
                {
                    "route_ids": move.route_ids
                    | related_packages.package_type_id.route_ids,
                    "warehouse_id": warehouse_id,
                    "packaging_uom_id": move.packaging_uom_id,
                },
            )

            excluded_rule_ids = []
            while (
                rule
                and rule.push_domain
                and not move.filtered_domain(literal_eval(rule.push_domain))
            ):
                # Exclude the rejected rules from the next search, otherwise
                # `_get_push_rule` keeps returning the same rule forever.
                excluded_rule_ids.append(rule.id)
                rule = StockRule._get_push_rule(
                    move.product_id,
                    move.location_dest_id,
                    {
                        "route_ids": move.route_ids
                        | related_packages.package_type_id.route_ids,
                        "warehouse_id": warehouse_id,
                        "packaging_uom_id": move.packaging_uom_id,
                        "domain": [("id", "not in", excluded_rule_ids)],
                    },
                )

            # Make sure it is not returning the return
            if rule and (
                not move.origin_returned_move_id
                or move.origin_returned_move_id.location_dest_id.id
                != rule.location_dest_id.id
            ):
                new_move = rule._run_push(move) or new_move
                if new_move:
                    new_moves.append(new_move)

            move_to_propagate_ids = set()
            move_to_mts_ids = set()
            for m in move.move_dest_ids - new_move:
                if (
                    new_move
                    and move.location_final_id
                    and m.location_id == move.location_final_id
                ):
                    move_to_propagate_ids.add(m.id)
                elif not m.location_id._child_of(move.location_dest_id):
                    move_to_mts_ids.add(m.id)
            self.env["stock.move"].browse(move_to_mts_ids)._break_mto_link(move)
            move.move_dest_ids = [
                Command.unlink(m_id) for m_id in move_to_propagate_ids
            ]
            new_move.move_dest_ids = [
                Command.link(m_id) for m_id in move_to_propagate_ids
            ]

        new_moves = self.env["stock.move"].concat(*new_moves)
        return new_moves.sudo()._action_confirm()

    def _quantity_sml(self):
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
            rounding = move.product_uom_id.rounding
            if move.state in ("cancel", "done") or (
                move.state == "draft" and not move.quantity
            ):
                continue
            if (
                float_compare(
                    move.quantity,
                    move.product_uom_qty,
                    precision_rounding=rounding,
                )
                >= 0
            ):
                moves_state_to_write["assigned"].add(move.id)
            elif (
                move.quantity
                and float_compare(
                    move.quantity,
                    move.product_uom_qty,
                    precision_rounding=rounding,
                )
                <= 0
            ):
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
                # In the process of merging a negative move, we may still have a negative move in the move_orig_ids at that point.
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
        """Prefetch the whole move chain along `target_field` (`move_dest_ids`
        or `move_orig_ids`) so later reads of it don't hit the DB one hop at a
        time.
        """
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
        """Find all moves in the chain, depending on the direction.

        :param origin: if set (default), returns the origin moves, else the destination moves
        """
        target_field = "move_orig_ids" if origin else "move_dest_ids"
        if not seen:
            seen = OrderedSet()
        # Walk the chain breadth-first rather than recursing: the recursion depth
        # used to equal the number of hops in the chain, which can be arbitrarily
        # deep (long MTO/push chains) and risk a RecursionError. This mirrors the
        # iterative approach already taken by `_rollup_moves_fetch`.
        frontier = self
        while frontier:
            unseen = OrderedSet(frontier.ids) - seen
            if not unseen:
                break
            seen.update(unseen)
            frontier = frontier.browse(unseen)[target_field]
        return seen

    def _set_references(self):
        # One write per picking instead of one per move.
        to_set = self.filtered(lambda m: not m.reference_ids and m.picking_id)
        for picking, moves in to_set.grouped("picking_id").items():
            if picking.reference_ids:
                moves.reference_ids = picking.reference_ids

    def _search_picking_for_assignation_domain(self):
        return [
            ("reference_ids", "=", self.reference_ids.ids),
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
        return self.env["stock.picking"].search(domain, limit=1)

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
        breaking_char = "\n"
        separation_char = "\t"
        options = False

        if not lots:
            return []  # Skip if the `lot_name` doesn't contain multiple values.

        # Checks the lines and prepares the move lines' values.
        split_lines = lots.split(breaking_char)
        split_lines = list(filter(None, split_lines))
        move_lines_vals = []
        for lot_text in split_lines:
            move_line_vals = {
                "lot_name": lot_text,
                "quantity": 1,
            }
            # Semicolons are also used for separation but for convenience we
            # replace them to work only with tabs.
            lot_text_parts = lot_text.replace(";", separation_char).split(
                separation_char,
            )
            options = options or self._get_formatting_options(lot_text_parts[1:])
            for extra_string in lot_text_parts[1:]:
                field_data = self._convert_string_into_field_data(extra_string, options)
                if field_data:
                    lot_text = lot_text_parts[0]
                    if field_data == "ignore":
                        # Got an unusable data for this move, updates only the lot_name part.
                        move_line_vals.update(lot_name=lot_text)
                    else:
                        move_line_vals.update(**field_data, lot_name=lot_text)
                else:
                    # At least this part of the string is erroneous and can't be converted,
                    # don't try to guess and simply use the full string as the lot name.
                    move_line_vals["lot_name"] = lot_text
                    break
            move_lines_vals.append(move_line_vals)
        return move_lines_vals

    def _split(self, qty, restrict_partner_id=False):
        """Splits `self` quantity and return values for a new moves to be created afterwards

        :param qty: float. quantity to split (given in product UoM)
        :param restrict_partner_id: optional partner that can be given in order to force the new move to restrict its choice of quants to the ones belonging to this partner.
        :returns: list of dict. stock move values
        """
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError(
                _(
                    "You cannot split a stock move that has been set to 'Done' or 'Cancel'.",
                ),
            )
        if self.state == "draft":
            # we restrict the split of a draft move because if not confirmed yet, it may be replaced by several other moves in
            # case of phantom bom (with mrp module). And we don't want to deal with this complexity by copying the product that will explode.
            raise UserError(
                _("You cannot split a draft move. It needs to be confirmed first."),
            )

        if self.product_id.uom_id.is_zero(qty):
            return []

        # `qty` passed as argument is the quantity to backorder and is always expressed in the
        # quants UOM. If we're able to convert back and forth this quantity in the move's and the
        # quants UOM, the backordered move can keep the UOM of the move. Else, we'll create it in
        # the UOM of the quants.
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

        # Update the original `product_qty` of the move. Use the general product's decimal
        # precision and not the move's UOM to handle the case where `quantity` is not
        # compatible with the move's UOM.
        new_product_qty = self.product_id.uom_id._compute_quantity(
            max(0, self.product_qty - qty),
            self.product_uom_id,
            round=False,
        )
        new_product_qty = float_round(
            new_product_qty,
            precision_digits=self.env["decimal.precision"].precision_get(
                "Product Unit",
            ),
        )
        self.with_context(do_not_unreserve=True).write(
            {"product_uom_qty": new_product_qty},
        )
        self._recompute_state()
        return new_move_vals

    def _set_date_deadline(self, new_deadline):
        """Propagate the new deadline to linked moves upstream and downstream.

        Entry point called from `write`: it resolves the set of already-visited
        move ids (threaded across the nested writes through the context) and
        delegates the actual propagation.
        """
        visited = self.env.context.get("date_deadline_propagate_ids")
        if visited is None:
            visited = set()
        self._propagate_date_deadline(new_deadline, visited)

    def _propagate_date_deadline(self, new_deadline, visited):
        """Shift the deadline of the moves linked to `self` by the same delta.

        :param visited: set of move ids already handled, updated in place. The
            writes below re-enter `_set_date_deadline` (via `write`) carrying
            the same set through the context, so every move of the chain is
            visited exactly once even across sibling branches.
        """
        visited.update(self.ids)
        for move in self.with_context(date_deadline_propagate_ids=visited):
            moves_to_update = move.move_dest_ids | move.move_orig_ids
            if move.date_deadline:
                delta = move.date_deadline - fields.Datetime.to_datetime(new_deadline)
            else:
                delta = 0
            for move_update in moves_to_update:
                if move_update.state in ("done", "cancel"):
                    continue
                if move_update.id in visited:
                    continue
                if move_update.date_deadline and delta:
                    move_update.date_deadline -= delta
                elif (
                    not move_update.date_deadline
                    or move_update.date_deadline != new_deadline
                ):
                    move_update.date_deadline = new_deadline

    def _set_quantity_done_prepare_vals(self, qty):
        def _move_qty(qty):
            return self.product_id.uom_id._compute_quantity(
                qty,
                self.product_uom_id,
                round=False,
            )

        self.ensure_one()
        res = []
        qty = self.product_uom_id._compute_quantity(
            qty,
            self.product_id.uom_id,
            round=False,
        )
        total_qty = qty
        consumed_quant = set()
        for ml in self.move_line_ids:
            ml_qty = ml.quantity
            if ml.product_uom_id.compare(ml_qty, 0) < 0:
                continue

            if ml.product_uom_id != self.product_id.uom_id:
                ml_qty = ml.product_uom_id._compute_quantity(
                    ml_qty,
                    self.product_id.uom_id,
                    round=False,
                )

            if self.product_uom_id.is_zero(_move_qty(qty)):
                res.append(Command.delete(ml.id))
                continue

            if ml.product_id.uom_id.compare(ml_qty, qty) > 0:
                if ml.product_uom_id != self.product_id.uom_id:
                    qty = ml.product_id.uom_id._compute_quantity(
                        qty,
                        ml.product_uom_id,
                        round=False,
                    )
                res.append(Command.update(ml.id, {"quantity": qty}))
                qty = 0
                continue

            if ml.result_package_id:
                qty -= ml_qty
                continue
            # remove what's already on the line
            taken_qty = min(qty, ml_qty)
            qty -= taken_qty
            if self.product_uom_id.compare(_move_qty(qty), 0) <= 0:
                continue

            # find a quant similar to the move line on which we can reserve
            ml_quants = self.env["stock.quant"]._get_reserve_quantity(
                self.product_id,
                ml.location_id,
                qty,
                lot_id=ml.lot_id,
                package_id=ml.package_id,
                owner_id=ml.owner_id,
                strict=True,
            )
            avail_qty = sum(q[1] for q in ml_quants)
            # Mark these quants as consumed so they aren't reserved again for another move line below.
            consumed_quant |= {q[0].id for q in ml_quants}
            if self.product_uom_id.compare(avail_qty, qty) <= 0:
                qty -= avail_qty  # decrease the target quantity for the next move lines
                avail_qty += ml_qty  # add the actual move line quantity as we will update it and not `+=` it
                if ml.product_uom_id != self.product_id.uom_id:
                    avail_qty = ml.product_id.uom_id._compute_quantity(
                        avail_qty,
                        ml.product_uom_id,
                        round=False,
                    )
                res.append(Command.update(ml.id, {"quantity": avail_qty}))

        # Reserve on quants before falling back to unreserved move lines.
        if self.product_uom_id.compare(_move_qty(qty), 0.0) > 0:
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
                if self.product_id.uom_id.compare(_move_qty(qty), 0.0) <= 0:
                    break

        # If quants aren't enough, create some move lines from the move itself
        if self.product_uom_id.compare(_move_qty(qty), 0.0) > 0:
            if self.product_id.tracking != "serial":
                qty = _move_qty(qty)
                vals = self._prepare_move_line_vals(quantity=0)
                vals["quantity"] = qty
                res.append((0, 0, vals))
            else:
                for _i in range(int(qty)):
                    vals = self._prepare_move_line_vals(quantity=0)
                    vals["quantity"] = 1
                    vals["product_uom_id"] = self.product_id.uom_id.id
                    res.append((0, 0, vals))
        return res

    def _set_quantity_done(self, qty):
        """Set the given quantity as done on the move through its move lines. Can handle move
        lines with a different UoM than the move, though that's best avoided.

        :param qty: quantity in the UoM of move.product_uom_id
        """
        existing_smls = self.move_line_ids
        self.move_line_ids = self._set_quantity_done_prepare_vals(qty)
        # `_set_quantity_done_prepare_vals` may return some commands to create new SMLs
        # These new SMLs need to be redirected thanks to putaway rules
        (self.move_line_ids - existing_smls)._apply_putaway_strategy()

    def _sync_warehouse_from_locations(self):
        """Realign `warehouse_id` with the warehouse of the (new) locations."""
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
        """Check for auto-triggered orderpoints and trigger them."""
        if not self or self.env["ir.config_parameter"].sudo().get_param(
            "stock.no_auto_scheduler",
        ):
            return

        # One search for every move at once instead of one `search(limit=1)`
        # per move; the per-move winner (first candidate in the model's
        # default order) is then picked in Python. Deduplicate the OR
        # branches: big batches repeat the same (product, company, locations)
        # combination many times, and one branch per move can exhaust
        # PostgreSQL's expression memory.
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
                and move.product_qty > orderpoint.product_min_qty
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
        """Check for and trigger action_assign for confirmed/partially_available moves related to done moves.
        Disable auto reservation if user configured to do so.
        """
        if not self or self.env["ir.config_parameter"].sudo().get_param(
            "stock.picking_no_auto_reserve",
        ):
            return

        # Group per destination location instead of emitting one OR branch per
        # move: the per-move form exhausted PostgreSQL's expression memory on
        # large batches (upstream 0ebb89ba47f).
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
        """Return the orderpoints whose forecast the moves in `self` impact."""
        if not self:
            return self.env["stock.warehouse.orderpoint"]
        # Deduplicate (product, warehouses) pairs: large batches usually
        # repeat a few products and would otherwise emit one OR branch per move.
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
        """Manually mark the relevant orderpoints for re-computation.
        This allows us to only recompute the qty_to_order for the orderpoints in the relevant warehouse(s),
        instead of all the orderpoints linked to the product.

        :param orderpoints: optional pre-collected orderpoints; `unlink` passes
            them because they must be gathered before the moves are deleted.
        """
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
        """Create or update move lines to reserve `need` from quants at `location_id`."""
        self.ensure_one()
        move_line_vals, taken_quantity = self._update_reserved_quantity_vals(
            need,
            location_id,
            lot_id,
            package_id,
            owner_id,
            strict,
        )
        if move_line_vals:
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

        taken_quantity = 0
        # Find a candidate move line to update or create a new one.
        candidate_lines = {}
        for line in self.move_line_ids:
            if line.result_package_id or line.product_id.tracking == "serial":
                continue
            candidate_lines[
                line.location_id,
                line.lot_id,
                line.package_id,
                line.owner_id,
            ] = line
        move_line_vals = []
        grouped_quants = {}
        # Handle quants duplication
        for quant, quantity in quants:
            if (
                quant.location_id,
                quant.lot_id,
                quant.package_id,
                quant.owner_id,
            ) not in grouped_quants:
                grouped_quants[
                    quant.location_id,
                    quant.lot_id,
                    quant.package_id,
                    quant.owner_id,
                ] = [quant, quantity]
            else:
                grouped_quants[
                    quant.location_id,
                    quant.lot_id,
                    quant.package_id,
                    quant.owner_id,
                ][1] += quantity
        for reserved_quant, quantity in grouped_quants.values():
            taken_quantity += quantity
            to_update = candidate_lines.get(
                (
                    reserved_quant.location_id,
                    reserved_quant.lot_id,
                    reserved_quant.package_id,
                    reserved_quant.owner_id,
                ),
            )
            # Whether `quantity` maps cleanly onto the candidate line's UoM (and can
            # thus be merged into it rather than spawning a new move line). Computed
            # only when there is a candidate line, so it never leaks across iterations.
            uom_quantity = None
            if to_update:
                uom_quantity = self._uom_quantity_if_faithful(
                    quantity,
                    to_update.product_uom_id,
                )
            if uom_quantity is not None:
                to_update.quantity += uom_quantity
            elif self.product_id.tracking == "serial" and (
                self.picking_type_id.use_create_lots
                or self.picking_type_id.use_existing_lots
            ):
                vals_list = self._add_serial_move_line_to_vals_list(
                    reserved_quant,
                    quantity,
                )
                if vals_list:
                    move_line_vals += vals_list
            else:
                move_line_vals.append(
                    self._prepare_move_line_vals(
                        quantity=quantity,
                        reserved_quant=reserved_quant,
                    ),
                )
        return move_line_vals, taken_quantity

    def _visible_quantity(self):
        self.ensure_one()
        return self.quantity

    # ------------------------------------------------------------
    # VALIDATION METHODS
    # ------------------------------------------------------------

    def _can_create_lot(self):
        return self.picking_type_id.use_existing_lots

    def _check_quantity(self):
        return (
            self.env["stock.quant"]
            .sudo()
            .search(
                [
                    ("product_id", "in", self.product_id.ids),
                    ("location_id", "child_of", self.location_dest_id.ids),
                    ("lot_id", "in", self.sudo().lot_ids.ids),
                ],
            )
            .check_quantity()
        )

    def _check_write_vals(self, vals):
        """Validate `vals` before writing; return it, reordered if needed."""
        if "quantity" in vals:
            if any(move.state == "cancel" for move in self):
                raise UserError(
                    _(
                        "You cannot change a cancelled stock move, create a new line instead.",
                    ),
                )
            if "lot_ids" in vals:
                # `lot_ids` must be applied before `quantity`: the `lot_ids`
                # inverse rewrites the move lines, so applying `quantity` first
                # would be undone by it. Move `lot_ids` to the front of `vals`
                # explicitly (inverses run in key order) rather than relying on
                # `lot_ids` happening to sort alphabetically before `quantity`.
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
