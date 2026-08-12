from ast import literal_eval
from collections import Counter, defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import OrderedSet, groupby

from odoo.addons.web.controllers.utils import clean_action


class StockMoveLine(models.Model):
    _name = "stock.move.line"
    _description = "Product Moves (Stock Move Line)"
    _order = "result_package_id desc, id"
    _rec_name = "product_id"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        readonly=True,
        index=True,
    )

    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
        bypass_search_access=True,
        check_company=True,
        index=True,
        help="The stock operation where the packing has been made",
    )
    picking_partner_id = fields.Many2one(
        related="picking_id.partner_id",
        readonly=True,
    )
    picking_location_id = fields.Many2one(related="picking_id.location_id")
    picking_location_dest_id = fields.Many2one(related="picking_id.location_dest_id")
    picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation type",
        compute="_compute_picking_type_id",
        search="_search_picking_type_id",
    )
    picking_type_use_create_lots = fields.Boolean(
        related="picking_type_id.use_create_lots",
        readonly=True,
    )
    picking_type_use_existing_lots = fields.Boolean(
        related="picking_type_id.use_existing_lots",
        readonly=True,
    )
    picking_code = fields.Selection(related="picking_type_id.code", readonly=True)

    move_id = fields.Many2one(
        comodel_name="stock.move",
        string="Stock Operation",
        check_company=True,
        index=True,
    )
    state = fields.Selection(
        related="move_id.state",
        store=True,
    )
    date_planned = fields.Datetime(
        related="move_id.date",
        string="Scheduled Date",
    )
    move_partner_id = fields.Many2one(
        related="move_id.partner_id",
        readonly=True,
    )
    scrap_id = fields.Many2one(
        related="move_id.scrap_id",
    )
    is_inventory = fields.Boolean(
        related="move_id.is_inventory",
    )
    is_locked = fields.Boolean(
        related="move_id.is_locked",
        readonly=True,
    )
    reference = fields.Char(
        related="move_id.reference",
    )
    origin = fields.Char(
        related="move_id.origin",
        string="Source",
    )
    description_picking = fields.Text(
        related="move_id.description_picking",
    )

    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="From",
        required=True,
        compute="_compute_location_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain="[('usage', '!=', 'view')]",
        index=True,
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="To",
        required=True,
        compute="_compute_location_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        domain="[('usage', '!=', 'view')]",
        index=True,
    )
    location_usage = fields.Selection(
        related="location_id.usage",
        string="Source Location Type",
    )
    location_dest_usage = fields.Selection(
        related="location_dest_id.usage",
        string="Destination Location Type",
    )
    owner_id = fields.Many2one(
        comodel_name="res.partner",
        string="From Owner",
        check_company=True,
        index="btree_not_null",
        help="When validating the transfer, the products will be taken from this owner.",
    )
    date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        help="Creation date of this move line until updated due to: quantity being increased, 'picked' status has updated, or move line is done.",
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        check_company=True,
        domain="[('type', '!=', 'service')]",
        ondelete="cascade",
        index=True,
    )
    product_category_name = fields.Char(
        related="product_id.categ_id.complete_name",
        string="Product Category",
    )
    tracking = fields.Selection(
        related="product_id.tracking",
        readonly=True,
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
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        compute="_compute_quantity",
        store=True,
        readonly=False,
        copy=False,
    )
    quantity_product_uom = fields.Float(
        string="Quantity in Product UoM",
        digits="Product Unit",
        compute="_compute_quantity_product_uom",
        store=True,
        copy=False,
    )
    picked = fields.Boolean(
        string="Picked",
        compute="_compute_picked",
        store=True,
        readonly=False,
        copy=False,
    )
    package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Source Package",
        check_company=True,
        domain="[('location_id', '=', location_id)]",
        ondelete="restrict",
    )
    lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Lot/Serial Number",
        check_company=True,
        domain="[('product_id', '=', product_id)]",
        index=True,
    )
    lot_name = fields.Char(string="Lot/Serial Number Name")
    result_package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Destination Package",
        required=False,
        check_company=True,
        domain="""[
        '|', '|',
        ('location_id', '=', location_dest_id),
        ('id', '=', package_id),
        '&', ('location_id', '=', False),
        '|', ('move_line_ids', '=', False),
        ('move_line_ids.location_dest_id', '=', location_dest_id)
        ]""",
        ondelete="restrict",
        help="If set, the operations are packed into this package",
    )
    result_package_dest_name = fields.Char(
        related="result_package_id.dest_complete_name",
        string="Destination Package Name",
    )
    package_history_id = fields.Many2one(
        comodel_name="stock.package.history",
        string="Package History",
        index="btree_not_null",
    )
    is_entire_pack = fields.Boolean(string="Is added through entire package")
    lots_visible = fields.Boolean(compute="_compute_lots_visible")
    consume_line_ids = fields.Many2many(
        comodel_name="stock.move.line",
        relation="stock_move_line_consume_rel",
        column1="consume_line_id",
        column2="produce_line_id",
    )
    produce_line_ids = fields.Many2many(
        comodel_name="stock.move.line",
        relation="stock_move_line_consume_rel",
        column1="produce_line_id",
        column2="consume_line_id",
    )
    quant_id = fields.Many2one(
        comodel_name="stock.quant",
        string="Pick From",
        store=False,
    )

    _free_reservation_index = models.Index(
        """(product_id, location_id, lot_id, package_id, owner_id, company_id)
        WHERE (state IS NULL OR state NOT IN ('done', 'cancel')) AND quantity_product_uom > 0 AND picked IS NOT TRUE"""
    )

    @api.constrains("lot_id", "product_id")
    def _check_lot_product(self):
        for line in self:
            if line.lot_id and line.product_id != line.lot_id.sudo().product_id:
                raise ValidationError(
                    _(
                        "This lot %(lot_name)s is incompatible with this product %(product_name)s",
                        lot_name=line.lot_id.name,
                        product_name=line.product_id.display_name,
                    ),
                )

    @api.constrains("quantity", "product_uom_id")
    def _check_positive_quantity(self):
        if any(ml.product_uom_id.compare(ml.quantity, 0) < 0 for ml in self):
            raise ValidationError(_("You can not enter negative quantities."))

    @api.model_create_multi
    def create(self, vals_list):
        self._prepare_create_vals(vals_list)

        mls = super().create(vals_list)

        created_moves = mls._link_or_create_moves()
        mls._reserve_new_move_lines()
        self.env["stock.move"].browse(created_moves)._post_process_created_moves()
        next_moves = self.env["stock.move"]
        for ml in mls:
            if ml.state == "done":
                if ml.product_id.is_storable:
                    available_qty, _in_date = ml._apply_quant_move()
                    if ml.product_id.uom_id.compare(available_qty, 0) < 0:
                        ml._free_reservation(
                            ml.product_id,
                            ml.location_id,
                            abs(available_qty),
                            lot_id=ml.lot_id,
                            package_id=ml.package_id,
                            owner_id=ml.owner_id,
                        )
                next_moves |= ml.move_id.move_dest_ids.filtered(
                    lambda move: move.state not in ("done", "cancel")
                )
        if next_moves:
            next_moves._do_unreserve()
            next_moves._action_assign()

        move_done = mls.filtered(lambda m: m.state == "done").move_id
        if move_done:
            move_done._check_quantity()

        return mls

    def write(self, vals):
        self._check_write_allowed(vals)
        if vals.get("quant_id"):
            vals = {**vals, **self._copy_quant_info(vals)}
            self._check_write_allowed(vals)

        packages_to_check = self.env["stock.package"]
        if "result_package_id" in vals:
            packages_to_check = self.env["stock.package"].browse(
                self.result_package_id._get_all_package_dest_ids()
            )

        updates = self._get_write_field_updates(vals)
        moves_to_recompute_state = self._resync_reservation(vals, updates)

        reservation_touched = bool(updates) or "quantity" in vals
        mls = self.env["stock.move.line"]
        next_moves = self.env["stock.move"]
        if reservation_touched:
            mls = self.filtered(
                lambda ml: ml.state == "done" and ml.product_id.is_storable
            )
            if not updates:
                mls = mls.filtered(
                    lambda ml: (
                        not ml.product_uom_id.is_zero(ml.quantity - vals["quantity"])
                    )
                )
            for ml in mls:
                ml._apply_quant_move(reverse=True)

                next_moves |= ml.move_id.move_dest_ids.filtered(
                    lambda move: move.state not in ("done", "cancel")
                )

                if ml.picking_id:
                    ml._log_message(
                        ml.picking_id,
                        ml,
                        "stock.track_move_template",
                        vals,
                    )
            move_done = mls.move_id
            if move_done:
                move_done._check_quantity()

        self._bump_dates(vals, updates)

        res = super().write(vals)

        for ml in mls:
            available_qty, _in_date = ml._apply_quant_move()
            if ml.product_id.uom_id.compare(available_qty, 0) < 0:
                ml._free_reservation(
                    ml.product_id,
                    ml.location_id,
                    abs(available_qty),
                    lot_id=ml.lot_id,
                    package_id=ml.package_id,
                    owner_id=ml.owner_id,
                )

        if packages_to_check:
            packages_to_check.filtered(
                lambda p: p.package_dest_id and not p.picking_ids
            ).package_dest_id = False
        if reservation_touched:
            if mls_to_update := self._get_lines_not_entire_pack():
                mls_to_update.write({"is_entire_pack": False})

            next_moves._do_unreserve()
            next_moves._action_assign()

        if moves_to_recompute_state:
            moves_to_recompute_state._recompute_state()

        return res

    def unlink(self):
        self._reservation_holding_lines()._apply_reservation_delta(-1)
        moves = self.mapped("move_id")
        packages = self.env["stock.package"].browse(
            self.result_package_id._get_all_package_dest_ids()
        )
        res = super().unlink()
        if moves:
            moves.with_prefetch()._recompute_state()
        if packages:
            packages.filtered(
                lambda p: p.package_dest_id and not p.picking_ids
            ).package_dest_id = False
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done_or_cancel(self):
        for ml in self:
            if ml.state in ("done", "cancel"):
                raise UserError(
                    _(
                        "Deleting product moves after the transfer is done?\n\n"
                        "That would be like going back in time to revert all operations triggered after this move. Who knows what the end result would be, So let's not do it.\n\n"
                        "Try changing the “done” quantity to 0 instead."
                    ),
                )

    @api.depends(
        "product_id",
        "product_id.uom_id",
        "product_id.uom_ids",
        "product_id.seller_ids",
        "product_id.seller_ids.product_uom_id",
    )
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = (
                line.product_id.uom_id
                | line.product_id.uom_ids
                | line.sudo().product_id.seller_ids.product_uom_id
            )

    @api.depends("move_id.product_uom_id", "product_id.uom_id")
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id:
                if line.move_id.product_uom_id:
                    line.product_uom_id = line.move_id.product_uom_id.id
                else:
                    line.product_uom_id = line.product_id.uom_id.id

    @api.depends("picking_id.picking_type_id", "product_id.tracking")
    def _compute_lots_visible(self):
        for line in self:
            tracked = line.product_id.tracking != "none"
            picking_type = line.picking_id.picking_type_id
            if tracked and picking_type:
                line.lots_visible = (
                    picking_type.use_existing_lots or picking_type.use_create_lots
                )
            else:
                line.lots_visible = tracked

    @api.depends("state")
    def _compute_picked(self):
        for line in self:
            if line.state == "done":
                line.picked = True

    @api.depends("picking_id")
    def _compute_picking_type_id(self):
        for line in self:
            line.picking_type_id = line.picking_id.picking_type_id

    @api.depends(
        "move_id", "move_id.location_id", "move_id.location_dest_id", "picking_id"
    )
    def _compute_location_id(self):
        for line in self:
            if (
                not line.location_id
                or line._origin.picking_id.location_id != line.picking_id.location_id
            ):
                line.location_id = (
                    line.move_id.location_id or line.picking_id.location_id
                )
            if (
                not line.location_dest_id
                or line._origin.picking_id.location_dest_id
                != line.picking_id.location_dest_id
            ):
                line.location_dest_id = (
                    line.move_id.location_dest_id or line.picking_id.location_dest_id
                )

    @api.depends("quant_id")
    def _compute_quantity(self):
        for record in self:
            if not record.quant_id or record.quantity:
                continue
            product_uom = record.product_id.uom_id
            sml_uom = record.product_uom_id
            move_visible_quantity = (
                record.move_id._visible_quantity() if record.move_id else 0.0
            )

            move_demand = record.move_id.product_uom_id._compute_quantity(
                record.move_id.product_uom_qty, sml_uom, rounding_method="HALF-UP"
            )
            move_quantity = record.move_id.product_uom_id._compute_quantity(
                move_visible_quantity, sml_uom, rounding_method="HALF-UP"
            )
            quant_qty = product_uom._compute_quantity(
                record.quant_id.available_quantity, sml_uom, rounding_method="HALF-UP"
            )

            if sml_uom.compare(move_demand, move_quantity) > 0:
                record.quantity = max(0, min(quant_qty, move_demand - move_quantity))
            else:
                record.quantity = max(0, quant_qty)

    @api.depends("quantity", "product_uom_id")
    def _compute_quantity_product_uom(self):
        for line in self:
            line.quantity_product_uom = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id, rounding_method="HALF-UP"
            )

    def _search_picking_type_id(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return Domain("picking_id.picking_type_id", operator, value)

    @api.onchange("product_id", "product_uom_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.lots_visible = self.product_id.tracking != "none"

    @api.onchange("lot_name", "lot_id")
    def _onchange_serial_number(self):
        """For a serial-tracked product: default `quantity` to 1, warn if the serial number is
        already used on another line, and warn (and relocate if possible) if it isn't in the
        expected source location.
        """
        res = {}
        if self.product_id.tracking == "serial":
            if not self.quantity:
                self.quantity = 1

            message = None
            if self.lot_name or self.lot_id:
                move_lines_to_check = self._get_similar_move_lines() - self
                if self.lot_name:
                    counter = Counter([line.lot_name for line in move_lines_to_check])
                    if counter[self.lot_name] >= 1:
                        message = _(
                            "You cannot use the same serial number twice. Please correct the serial numbers encoded."
                        )
                    elif not self.lot_id:
                        lots = self.env["stock.lot"].search(
                            [
                                ("product_id", "=", self.product_id.id),
                                ("name", "=", self.lot_name),
                                "|",
                                ("company_id", "=", False),
                                ("company_id", "=", self.company_id.id),
                            ],
                        )
                        quants = lots.quant_ids.filtered(
                            lambda q: (
                                not q.product_uom_id.is_zero(q.quantity)
                                and q.location_id.usage
                                in ["customer", "internal", "transit"]
                            )
                        )
                        if quants:
                            message = _(
                                "Serial number (%(serial_number)s) already exists in location(s): %(location_list)s. Please correct the serial number encoded.",
                                serial_number=self.lot_name,
                                location_list=quants.location_id.mapped("display_name"),
                            )
                elif self.lot_id:
                    counter = Counter([line.lot_id.id for line in move_lines_to_check])
                    if counter[self.lot_id.id] >= 1:
                        message = _(
                            "You cannot use the same serial number twice. Please correct the serial numbers encoded."
                        )
                    else:
                        message, recommended_location = (
                            self.env["stock.quant"]
                            .sudo()
                            ._check_serial_number(
                                self.product_id,
                                self.lot_id,
                                self.company_id,
                                self.location_id,
                                self.picking_id.location_id,
                            )
                        )
                        if recommended_location:
                            self.location_id = recommended_location
            if message:
                res["warning"] = {"title": _("Warning"), "message": message}
        return res

    @api.onchange("quantity", "product_uom_id")
    def _onchange_quantity(self):
        """Enforce that serial-tracked products are only ever processed in quantities of 1."""
        if self.quantity and self.product_id.tracking == "serial":
            if self.product_id.uom_id.compare(
                self.quantity_product_uom, 1.0
            ) != 0 and not self.product_id.uom_id.is_zero(self.quantity_product_uom):
                raise UserError(
                    _(
                        "You can only process 1.0 %s of products with unique serial number.",
                        self.product_id.uom_id.name,
                    ),
                )

    @api.onchange("result_package_id", "product_id", "product_uom_id", "quantity")
    def _onchange_putaway_location(self):
        default_dest_location = self._get_default_dest_location()
        if (
            not self.id
            and self.env.user.has_group("stock.group_stock_multi_locations")
            and self.product_id
            and self.quantity_product_uom
            and self.location_dest_id == default_dest_location
        ):
            quantity = self.quantity_product_uom
            self.location_dest_id = default_dest_location.with_context(
                exclude_sml_ids=self.ids
            )._get_putaway_strategy(
                self.product_id, quantity=quantity, package=self.result_package_id
            )

    def _action_done(self):
        """Called by the move's `_action_done` for all of its move lines: moves the reserved
        quants from source to destination location, releasing reservations as needed.

        Not meant to be used to edit an already-done move; see `write()` for that instead.
        """
        mls_to_delete, mls_needing_lot_check, mls_without_lot = (
            self._classify_done_lines()
        )
        (
            mls_without_lot | mls_needing_lot_check._resolve_done_lots()
        )._raise_missing_lot()

        mls_to_delete.unlink()

        mls_todo = self - mls_to_delete
        mls_todo._check_company()

        if not self.env.context.get("ignore_dest_packages"):
            package_history_vals = mls_todo._prepare_package_history_vals()
            if package_history_vals:
                self.env["stock.package.history"].create(package_history_vals)

        mls_todo._apply_done_quant_moves()

        if not self.env.context.get("ignore_dest_packages"):
            mls_todo.result_package_id._apply_dest_to_package()

        affected_pickings = mls_todo.picking_id
        if affected_pickings:
            affected_pickings._check_entire_pack()
        mls_todo.write(
            {
                "date": fields.Datetime.now(),
            }
        )

    def _classify_done_lines(self):
        """Sort these lines by what validating them requires.

        A null-quantity line is unlinked -- mandatory to free the reservation and to
        apply `_action_done` correctly on the following lines. Lines whose picking type
        creates lots are handed on for lot resolution; the rest are validated as they are.

        Missing-lot lines are *returned* rather than raised on, so the caller can report
        them together with the ones lot resolution also fails to bind -- one error
        listing every product, not one per phase.

        :return: (lines to unlink, lines whose `lot_name` still needs resolving,
                  lines that require a lot and have none)
        :raises UserError: on a negative quantity.
        """
        ml_ids_tracked_without_lot = OrderedSet()
        ml_ids_to_delete = OrderedSet()
        ml_ids_needing_lot_check = OrderedSet()

        for ml in self:
            qty_done_float_compared = ml.product_uom_id.compare(ml.quantity, 0)
            if qty_done_float_compared < 0:
                raise UserError(_("No negative quantities allowed"))
            if qty_done_float_compared == 0:
                if not ml.is_inventory:
                    ml_ids_to_delete.add(ml.id)
                continue
            if ml.product_id.tracking == "none":
                continue
            picking_type_id = ml.move_id.picking_type_id
            if not ml._exclude_requiring_lot():
                ml_ids_tracked_without_lot.add(ml.id)
                continue
            if (
                not picking_type_id
                or ml.lot_id
                or (
                    not picking_type_id.use_create_lots
                    and not picking_type_id.use_existing_lots
                )
            ):
                continue
            if picking_type_id.use_create_lots:
                ml_ids_needing_lot_check.add(ml.id)
            else:
                ml_ids_tracked_without_lot.add(ml.id)

        return (
            self.browse(ml_ids_to_delete),
            self.browse(ml_ids_needing_lot_check),
            self.browse(ml_ids_tracked_without_lot),
        )

    def _resolve_done_lots(self):
        """Bind each line's `lot_name` to an existing `stock.lot`, creating the ones that
        do not exist yet. One search per (product, company) rather than per line.

        :return: the lines left with no lot to bind, for the caller to report.
        """
        ml_ids_tracked_without_lot = OrderedSet()
        ml_ids_to_create_lot = OrderedSet()
        for (product, company), mls in self.grouped(
            lambda ml: (ml.product_id, ml.company_id)
        ).items():
            lots = self.env["stock.lot"].search(
                [
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "=", company.id),
                    ("product_id", "=", product.id),
                    ("name", "in", mls.mapped("lot_name")),
                ]
            )
            lots = {lot.name: lot for lot in lots}
            for ml in mls:
                lot = lots.get(ml.lot_name)
                if lot:
                    ml.lot_id = lot.id
                elif ml.lot_name:
                    ml_ids_to_create_lot.add(ml.id)
                else:
                    ml_ids_tracked_without_lot.add(ml.id)

        self.browse(ml_ids_to_create_lot)._create_and_assign_production_lot()
        return self.browse(ml_ids_tracked_without_lot)

    def _raise_missing_lot(self):
        """Report every line at once, so the user fixes them in one pass."""
        if not self:
            return
        products_list = "\n".join(
            f"- {product_name}"
            for product_name in self.mapped("product_id.display_name")
        )
        raise UserError(
            _(
                "You need to supply a Lot/Serial Number for product:\n%(products)s",
                products=products_list,
            ),
        )

    def _apply_done_quant_moves(self):
        """Move each line's stock from source to destination, freeing the reservations
        that the removal invalidated.

        Consuming a line releases whatever it had reserved *and* removes the stock from
        the source. Both deltas land on the same quant row, so `release_reserved` folds
        them into one update instead of gathering, locking and re-reading that row twice.
        """
        ml_ids_to_ignore = OrderedSet()
        quants_cache = self.env["stock.quant"]._get_quants_by_products_locations(
            self.product_id,
            self.location_id | self.location_dest_id,
            lot_scope=self.lot_id,
        )
        for ml in self.with_context(quants_cache=quants_cache):
            available_qty, _in_date = ml._apply_quant_move(release_reserved=True)
            if ml.product_id.uom_id.compare(available_qty, 0) < 0:
                ml.with_context(
                    quants_cache=None, bypass_entire_pack=True
                )._free_reservation(
                    ml.product_id,
                    ml.location_id,
                    abs(available_qty),
                    lot_id=ml.lot_id,
                    package_id=ml.package_id,
                    owner_id=ml.owner_id,
                    ml_ids_to_ignore=ml_ids_to_ignore,
                )
            ml_ids_to_ignore.add(ml.id)

    def action_view_reference(self):
        self.ensure_one()
        if self.move_id:
            action = self.move_id.action_view_reference()
            if action["res_model"] != "stock.move":
                return action
        return {
            "res_model": self._name,
            "type": "ir.actions.act_window",
            "views": [[False, "form"]],
            "res_id": self.id,
        }

    def action_put_in_pack(
        self, *, package_id=False, package_type_id=False, package_name=False
    ):
        move_lines = self
        if self.env.context.get("all_move_line_ids"):
            move_lines = self.env["stock.move.line"].browse(
                self.env.context["all_move_line_ids"]
            )
        force_move_lines = bool(self.env.context.get("force_move_lines"))

        move_lines_to_pack, packages_to_pack = (
            move_lines._get_lines_and_packages_to_pack(
                picked_first=not force_move_lines
            )
        )
        done_pack = False
        package = self.env["stock.package"]
        if move_lines_to_pack:
            action = move_lines_to_pack._pre_put_in_pack_hook(
                move_lines,
                package_id,
                package_type_id,
                package_name,
                self.env.context.get("from_package_wizard"),
            )
            if action:
                return action

            package = move_lines_to_pack._put_in_pack(
                package_id, package_type_id, package_name
            )
            done_pack = move_lines_to_pack._post_put_in_pack_hook(package)
        if done_pack and not force_move_lines:
            return done_pack
        elif packages_to_pack:
            if package:
                packages_to_pack -= package
                package_id = package.id
            if packages_to_pack:
                return packages_to_pack.action_put_in_pack(
                    package_id=package_id,
                    package_type_id=package_type_id,
                    package_name=package_name,
                )
        return None

    def action_revert_inventory(self):
        move_vals = []
        self = self.with_context(inventory_mode=False)
        processed_move_line = self.env["stock.move.line"]
        for move_line in self:
            if move_line.is_inventory and not move_line.product_uom_id.is_zero(
                move_line.quantity
            ):
                processed_move_line += move_line
                move_vals.append(move_line._get_revert_inventory_move_values())
        if not processed_move_line:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "message": _("There are no inventory adjustments to revert."),
                },
            }
        moves = self.env["stock.move"].create(move_vals)
        moves._action_done()
        return {
            "name": _("Reverted Moves"),
            "type": "ir.actions.act_window",
            "res_model": "stock.move.line",
            "view_mode": "list",
            "domain": [("id", "in", moves.move_line_ids.ids + self.ids)],
        }

    def _apply_putaway_strategy(self):
        if self.env.context.get("avoid_putaway_rules"):
            return
        for package, smls in groupby(
            self,
            lambda sml: sml.result_package_id.outermost_package_id,
        ):
            smls = self.env["stock.move.line"].concat(*smls)
            # Candidate locations, resolved once for the whole group instead of
            # once per line. A group can span several move destinations, so this
            # is their union; `_get_putaway_strategy` narrows it back to the
            # destination it is asked about.
            locations = smls.move_id.location_dest_id.child_internal_location_ids
            excluded_smls = set(smls.ids)
            if package.package_type_id:
                # One putaway answer per destination, not one for the group:
                # `_get_putaway_strategy` speaks for a single location, and lines
                # whose moves target different destinations cannot share an
                # answer without landing outside their own move's destination.
                # The common case — every line of a package going to the same
                # place — is a single iteration, exactly as before.
                for location_dest, dest_smls in smls.grouped(
                    lambda sml: sml.move_id.location_dest_id
                ).items():
                    if not location_dest:
                        continue
                    dest_smls.location_dest_id = location_dest.with_context(
                        exclude_sml_ids=excluded_smls,
                        products=dest_smls.product_id,
                        locations=locations,
                    )._get_putaway_strategy(
                        self.env["product.product"], package=package
                    )
            elif package:
                used_locations = set()
                for sml in smls:
                    if len(used_locations) > 1:
                        break
                    putaway_loc_id = sml.move_id.location_dest_id.with_context(
                        exclude_sml_ids=excluded_smls,
                        locations=locations,
                    )._get_putaway_strategy(sml.product_id, quantity=sml.quantity)
                    if putaway_loc_id != sml.location_dest_id:
                        sml.location_dest_id = putaway_loc_id
                    excluded_smls.discard(sml.id)
                    used_locations.add(sml.location_dest_id)
                if len(used_locations) > 1:
                    for move, grouped_smls in smls.grouped("move_id").items():
                        grouped_smls.location_dest_id = move.location_dest_id
            else:
                for sml in smls:
                    putaway_loc_id = sml.move_id.location_dest_id.with_context(
                        exclude_sml_ids=excluded_smls,
                    )._get_putaway_strategy(
                        sml.product_id,
                        quantity=sml.quantity,
                        packaging=sml.move_id.packaging_uom_id,
                    )
                    if putaway_loc_id != sml.location_dest_id:
                        sml.location_dest_id = putaway_loc_id
                    excluded_smls.discard(sml.id)

    def _apply_quant_move(
        self, *, reverse=False, in_date=False, release_reserved=False
    ):
        """Move this line's `quantity_product_uom` of *available* stock between its source and
        destination, threading the removed stock's incoming date onto the addition so FIFO
        ordering is preserved.

        The physical move is always source -> destination with `result_package_id` sitting at
        the destination; pass ``reverse=True`` to undo it (destination -> source).
        `_synchronize_quant` compensates negative quants with untracked ones on its own.

        :param release_reserved: also drop this line's reservation from the source quant.
            Validating a line consumes what it had reserved, so on-hand and reserved both
            fall by the same amount on the same row; passing this folds the pair into a
            single quant update rather than two that each gather, lock and re-read it.
            Meaningless for ``reverse=True`` (an undo restores stock, it releases nothing).
        :return: tuple (available_qty at the location we removed from, in_date), so callers can
                 free over-reservations when the source went negative.
        """
        self.ensure_one()
        qty = self.quantity_product_uom
        if reverse:
            from_loc, to_loc, from_package = (
                self.location_dest_id,
                self.location_id,
                self.result_package_id,
            )
        else:
            from_loc, to_loc, from_package = (
                self.location_id,
                self.location_dest_id,
                self.package_id,
            )
        available_qty, in_date = self._synchronize_quant(
            -qty,
            from_loc,
            package=from_package,
            in_date=in_date,
            reserved_delta=-qty if release_reserved and not reverse else None,
        )
        self._synchronize_quant(
            qty,
            to_loc,
            package=self.package_id if reverse else self.result_package_id,
            in_date=in_date,
        )
        return available_qty, in_date

    def _apply_reservation_delta(self, sign):
        """Reserve (``sign=1``) or release (``sign=-1``) these lines' quantities.

        One quant update per (product, location, lot, package, owner) tuple rather than
        one per line: repeated calls for a single tuple gather, lock and re-read the very
        same row each time. Call on :meth:`_reservation_holding_lines` -- the reserve and
        release paths share both helpers so they cannot drift apart on which lines hold a
        reservation, which is what let a line reserve without ever releasing.
        """
        qty_by_characteristics = defaultdict(float)
        for ml in self:
            qty_by_characteristics[
                ml.product_id, ml.location_id, ml.lot_id, ml.package_id, ml.owner_id
            ] += ml.quantity_product_uom
        for (
            product,
            location,
            lot,
            package,
            owner,
        ), qty in qty_by_characteristics.items():
            self.env["stock.quant"]._update_reserved_quantity(
                product,
                location,
                sign * qty,
                lot_id=lot,
                package_id=package,
                owner_id=owner,
            )

    def _bump_dates(self, vals, updates):
        """Bump `date` to now on lines that just gained progress -- newly picked, or a picked
        line whose done quantity increased -- unless the write set `date` explicitly."""
        if "date" in vals or not (
            "product_uom_id" in vals or "quantity" in vals or vals.get("picked", False)
        ):
            return
        updated_ml_ids = set()
        for ml in self:
            if ml.state in ["draft", "cancel", "done"]:
                continue
            if vals.get("picked", False) and not ml.picked:
                updated_ml_ids.add(ml.id)
                continue
            if ("quantity" in vals or "product_uom_id" in vals) and ml.picked:
                new_qty = updates.get(
                    "product_uom_id", ml.product_uom_id
                )._compute_quantity(
                    vals.get("quantity", ml.quantity),
                    ml.product_id.uom_id,
                    rounding_method="HALF-UP",
                )
                old_qty = ml.product_uom_id._compute_quantity(
                    ml.quantity, ml.product_id.uom_id, rounding_method="HALF-UP"
                )
                if ml.product_uom_id.compare(old_qty, new_qty) < 0:
                    updated_ml_ids.add(ml.id)
        self.env["stock.move.line"].browse(updated_ml_ids).date = fields.Datetime.now()

    def _compute_sale_price(self):
        pass

    def _create_and_assign_production_lot(self):
        """Create and assign new production lots for move lines."""
        lot_vals = []
        key_to_index = {}
        key_to_mls = defaultdict(lambda: self.env["stock.move.line"])
        for ml in self:
            key = (ml.product_id.id, ml.lot_name)
            key_to_mls[key] |= ml
            if ml.tracking != "lot" or key not in key_to_index:
                key_to_index[key] = len(lot_vals)
                lot_vals.append(ml._prepare_new_lot_vals())

        lots = self.env["stock.lot"].create(lot_vals)
        for key, mls in key_to_mls.items():
            lot = lots[key_to_index[key]].with_prefetch(lots._ids)
            mls.with_prefetch(self._prefetch_ids).write({"lot_id": lot.id})

    def _copy_quant_info(self, vals):
        quant = self.env["stock.quant"].browse(vals.get("quant_id", 0))
        return {
            "product_id": quant.product_id.id,
            "lot_id": quant.lot_id.id,
            "package_id": quant.package_id.id,
            "location_id": quant.location_id.id,
            "owner_id": quant.owner_id.id,
        }

    def _exclude_requiring_lot(self):
        self.ensure_one()
        return (
            self.move_id.picking_type_id
            or self.is_inventory
            or self.lot_id
            or self.move_id.scrap_id
        )

    def _free_reservation(
        self,
        product_id,
        location_id,
        quantity,
        lot_id=None,
        package_id=None,
        owner_id=None,
        ml_ids_to_ignore=None,
    ):
        """When editing a done move line or validating one with some forced quantities, it is
        possible to impact quants that were not reserved. It is therefore necessary to edit or
        unlink the move lines that reserved a quantity now unavailable.

        :param ml_ids_to_ignore: iterable of `stock.move.line` ids that should NOT be
            unreserved. Copied, not mutated: `OrderedSet.__ior__` updates in place, so
            extending the caller's own set with `self` was a side effect on an argument
            that nothing documented.
        """
        self.ensure_one()
        ml_ids_to_ignore = OrderedSet(ml_ids_to_ignore or ()) | OrderedSet(self.ids)

        if self._should_bypass_reservation(location_id):
            return

        outdated_move_lines_domain = [
            ("state", "not in", ["done", "cancel"]),
            ("product_id", "=", product_id.id),
            ("lot_id", "=", lot_id.id if lot_id else False),
            ("location_id", "=", location_id.id),
            ("owner_id", "=", owner_id.id if owner_id else False),
            ("package_id", "=", package_id.id if package_id else False),
            ("quantity_product_uom", ">", 0.0),
            ("picked", "=", False),
            ("id", "not in", tuple(ml_ids_to_ignore)),
        ]

        def current_picking_first(cand):
            date = cand.picking_id.date_planned or cand.move_id.date
            return (
                cand.picking_id != self.move_id.picking_id,
                -date.timestamp() if date else 0,
                -cand.id,
            )

        outdated_candidates = (
            self.env["stock.move.line"]
            .search(outdated_move_lines_domain)
            .sorted(current_picking_first)
        )

        move_to_reassign = self.env["stock.move"]
        to_unlink_candidate_ids = set()

        product_uom = product_id.uom_id
        for candidate in outdated_candidates:
            move_to_reassign |= candidate.move_id
            if product_uom.compare(candidate.quantity_product_uom, quantity) <= 0:
                quantity -= candidate.quantity_product_uom
                to_unlink_candidate_ids.add(candidate.id)
                if product_uom.is_zero(quantity):
                    break
            else:
                candidate.quantity -= candidate.product_id.uom_id._compute_quantity(
                    quantity, candidate.product_uom_id, rounding_method="HALF-UP"
                )
                break

        move_line_to_unlink = self.env["stock.move.line"].browse(
            to_unlink_candidate_ids
        )
        moves_to_sever = move_line_to_unlink.move_id.filtered(
            lambda m: not (m.move_line_ids - move_line_to_unlink)
        )
        moves_to_sever.write(
            {"procure_method": "make_to_stock", "move_orig_ids": [Command.clear()]}
        )
        (move_to_reassign - moves_to_sever).filtered(
            lambda m: m.procure_method != "make_to_stock"
        ).procure_method = "make_to_stock"
        move_line_to_unlink.unlink()
        move_to_reassign[::-1]._action_assign()

    def _get_aggregated_properties(self, move_line=False, move=False):
        move = move or move_line.move_id
        uom = move.product_uom_id or move_line.product_uom_id
        packaging_uom = move.packaging_uom_id
        name = move.product_id.display_name
        description = move.description_picking or ""
        product = move.product_id
        if description.startswith(name):
            description = description.removeprefix(name).strip()
        elif description.startswith(product.name):
            description = description.removeprefix(product.name).strip()
        line_key = f"{product.id}_{product.display_name}_{description or ''}_{uom.id}_{packaging_uom.id}"
        properties = {
            "line_key": line_key,
            "name": name,
            "description": description,
            "product_uom_id": uom,
            "packaging_uom_id": packaging_uom,
            "move": move,
        }
        if move_line and move_line.result_package_id:
            properties["package"] = move_line.result_package_id
            properties["package_history"] = move_line.package_history_id
            properties["line_key"] += f"_{move_line.result_package_id.id}"
        return properties

    def _get_aggregated_product_quantities(self, **kwargs):
        """Aggregate quantities across move lines for reports (e.g. delivery slips).

        Move lines are grouped by product/description/uom/packaging (and destination package,
        when set), ignoring lots/serials since those are expected to already be split per line.

        :return: dict keyed by that grouping, mapping to product/name/description/quantity info.
        """
        aggregated_move_lines = {}

        backorders = self.env["stock.picking"]
        pickings = self.picking_id
        while pickings.backorder_ids:
            backorders |= pickings.backorder_ids
            pickings = pickings.backorder_ids

        base_key_by_move = {}

        def base_key(move):
            key = base_key_by_move.get(move.id)
            if key is None:
                key = base_key_by_move[move.id] = self._get_aggregated_properties(
                    move=move
                )["line_key"]
            return key

        base_by_agg_key = {}

        backorder_lines_by_base = defaultdict(lambda: self.env["stock.move.line"])
        for bo_line in backorders.move_line_ids:
            backorder_lines_by_base[base_key(bo_line.move_id)] |= bo_line

        for move_line in self:
            if kwargs.get("except_package") and move_line.result_package_id:
                continue
            aggregated_properties = self._get_aggregated_properties(move_line=move_line)
            line_key, uom = (
                aggregated_properties["line_key"],
                aggregated_properties["product_uom_id"],
            )
            quantity = move_line.product_uom_id._compute_quantity(
                move_line.quantity, uom
            )
            packaging_quantity = uom._compute_quantity(
                quantity, move_line.move_id.packaging_uom_id
            )
            if line_key not in aggregated_move_lines:
                move_base_key = base_key(move_line.move_id)
                qty_ordered = None
                packaging_qty_ordered = None
                if not kwargs.get("strict"):
                    qty_ordered = move_line._original_ordered_quantity(
                        uom,
                        backorder_lines_by_base.get(
                            move_base_key, self.env["stock.move.line"]
                        ),
                    )
                    packaging_qty_ordered = uom._compute_quantity(
                        qty_ordered, move_line.move_id.packaging_uom_id
                    )
                base_by_agg_key[line_key] = move_base_key
                aggregated_move_lines[line_key] = {
                    **aggregated_properties,
                    "quantity": quantity,
                    "packaging_quantity": packaging_quantity,
                    "qty_ordered": qty_ordered if qty_ordered is not None else quantity,
                    "packaging_qty_ordered": packaging_qty_ordered
                    if packaging_qty_ordered is not None
                    else packaging_quantity,
                    "product": move_line.product_id,
                }
            else:
                aggregated_move_lines[line_key]["qty_ordered"] += quantity
                aggregated_move_lines[line_key]["packaging_qty_ordered"] += (
                    packaging_quantity
                )
                aggregated_move_lines[line_key]["quantity"] += quantity
                aggregated_move_lines[line_key]["packaging_quantity"] += (
                    packaging_quantity
                )

        if kwargs.get("strict"):
            return aggregated_move_lines
        self._aggregate_empty_moves(
            aggregated_move_lines, base_by_agg_key, self.picking_id | backorders
        )
        return aggregated_move_lines

    def _original_ordered_quantity(self, uom, backorder_lines):
        """Reconstruct, in `uom`, what this line's move was originally asked to deliver.

        The move's own demand shrinks when a transfer is split, so the demand that moved
        to the backorders is added back and the quantity the move's *other* lines already
        account for is taken out -- they all share this move's base aggregation key by
        construction, so they land in this entry's group.

        :param backorder_lines: the backorder move lines sharing this move's base key.
        """
        self.ensure_one()
        qty_ordered = self.move_id.product_uom_qty
        qty_ordered += sum(backorder_lines.move_id.mapped("product_uom_qty"))
        qty_ordered -= sum(
            line.product_uom_id._compute_quantity(line.quantity, uom)
            for line in self.move_id.move_line_ids - self
        )
        return qty_ordered

    def _aggregate_empty_moves(self, aggregated_move_lines, base_by_agg_key, pickings):
        """Fold in the moves left with no move line when a partially done transfer is
        validated and split -- their ordered quantity would otherwise vanish from the
        report.

        Mutates `aggregated_move_lines` (and `base_by_agg_key`) in place, the way the
        line loop that precedes it builds them.

        :param base_by_agg_key: base (package-less) aggregation key of each entry
            already present, so an empty move joins its own group. Matched on *exact*
            base equality: the historical `str.startswith` prefix test merged unrelated
            groups whenever one key was a textual prefix of another.
        """
        for empty_move in pickings.move_ids:
            to_bypass = False
            if not (
                empty_move.product_uom_qty
                and empty_move.product_uom_id.is_zero(empty_move.quantity)
            ):
                continue
            if empty_move.state != "cancel":
                if empty_move.state != "confirmed" or empty_move.move_line_ids:
                    continue
                to_bypass = True
            aggregated_properties = self._get_aggregated_properties(move=empty_move)
            line_key = aggregated_properties["line_key"]

            matching_keys = [
                key for key, base in base_by_agg_key.items() if base == line_key
            ]
            if not matching_keys and not to_bypass:
                base_by_agg_key[line_key] = line_key
                aggregated_move_lines[line_key] = {
                    **aggregated_properties,
                    "quantity": False,
                    "packaging_quantity": 0,
                    "packaging_qty_ordered": 0,
                    "qty_ordered": empty_move.product_uom_qty,
                    "product": empty_move.product_id,
                }
            elif line_key in aggregated_move_lines:
                aggregated_move_lines[line_key]["qty_ordered"] += (
                    empty_move.product_uom_qty
                )
            elif matching_keys:
                aggregated_move_lines[matching_keys[0]]["qty_ordered"] += (
                    empty_move.product_uom_qty
                )

    def _get_default_dest_location(self):
        if not self.env.user.has_group("stock.group_stock_multi_locations"):
            return self.location_dest_id[:1]
        if self.env.context.get("default_location_dest_id"):
            return self.env["stock.location"].browse(
                [self.env.context.get("default_location_dest_id")],
            )
        return (
            self.move_id.location_dest_id
            or self.picking_id.location_dest_id
            or self.location_dest_id
        )[:1]

    def _get_putaway_additional_qty(self):
        additional_qty = {}
        for ml in self._origin:
            qty = ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            additional_qty[ml.location_dest_id.id] = (
                additional_qty.get(ml.location_dest_id.id, 0) - qty
            )
        return additional_qty

    def get_move_line_quant_match(self, move_id, dirty_move_line_ids, dirty_quant_ids):
        move = self.env["stock.move"].browse(move_id)
        deleted_move_lines = move.move_line_ids - self
        dirty_move_lines = self.env["stock.move.line"].browse(dirty_move_line_ids)
        quants_data = []
        move_lines_data = []
        domain = Domain("id", "in", dirty_quant_ids) | Domain.OR(
            Domain(
                [
                    ("product_id", "=", move_line.product_id.id),
                    ("lot_id", "=", move_line.lot_id.id),
                    ("location_id", "=", move_line.location_id.id),
                    ("package_id", "=", move_line.package_id.id),
                    ("owner_id", "=", move_line.owner_id.id),
                ],
            )
            for move_line in dirty_move_lines | deleted_move_lines
        )
        if not domain.is_false():

            def _match_key(record):
                return (
                    record.product_id.id,
                    record.lot_id.id,
                    record.location_id.id,
                    record.package_id.id,
                    record.owner_id.id,
                )

            empty = self.env["stock.move.line"]
            dirty_by_key = defaultdict(lambda: empty)
            for move_line in dirty_move_lines:
                dirty_by_key[_match_key(move_line)] |= move_line
            deleted_by_key = defaultdict(lambda: empty)
            for move_line in deleted_move_lines:
                deleted_by_key[_match_key(move_line)] |= move_line

            quants = self.env["stock.quant"].search(domain)
            for quant in quants:
                key = _match_key(quant)
                dirty_lines = dirty_by_key.get(key, empty)
                deleted_lines = deleted_by_key.get(key, empty)
                quants_data.append(
                    (
                        quant.id,
                        {
                            "available_quantity": quant.available_quantity
                            + sum(ml.quantity_product_uom for ml in deleted_lines),
                            "move_line_ids": dirty_lines.ids,
                        },
                    ),
                )
                move_lines_data += [
                    (ml.id, {"quantity": ml.quantity, "quant_id": quant.id})
                    for ml in dirty_lines
                ]
        return [quants_data, move_lines_data]

    def _get_similar_move_lines(self):
        self.ensure_one()
        lines = self.env["stock.move.line"]
        picking_id = self.move_id.picking_id if self.move_id else self.picking_id
        if picking_id:
            lines |= picking_id.move_line_ids.filtered(
                lambda ml: (
                    ml.product_id == self.product_id and (ml.lot_id or ml.lot_name)
                )
            )
        return lines

    def _get_lines_and_packages_to_pack(self, picked_first=True):
        """Get all move lines & packages that need to be put in a pack.

        :param picked_first: If enabled, will prioritize picked move lines over other move lines.
        :return: move_lines_to_pack: All move lines without a pack that can be packed
        :return: packages_to_pack: All packages that can be packed
        """
        if len(self.picking_type_id) > 1:
            raise UserError(
                _(
                    "You cannot pack products into the same package when they are from different transfers with different operation types"
                ),
            )

        quantity_move_lines = self.filtered(
            lambda ml: (
                ml.state not in ("done", "cancel")
                and ml.product_uom_id.compare(ml.quantity, 0.0) > 0
            )
        )
        if picked_first:
            picked_move_lines = quantity_move_lines.filtered(lambda ml: ml.picked)
            if picked_move_lines:
                quantity_move_lines = picked_move_lines

        move_lines_to_pack = quantity_move_lines.filtered(
            lambda ml: not ml.result_package_id
        )
        packages_to_pack = (
            quantity_move_lines - move_lines_to_pack
        ).result_package_id.outermost_package_id

        return move_lines_to_pack, packages_to_pack

    def _get_lines_not_entire_pack(self):
        """Checks within self for move lines that should no longer be considered as entire packs."""
        relevant_move_lines = self.filtered(lambda ml: ml.is_entire_pack)
        if not relevant_move_lines:
            return self.browse()

        ids_to_update = set(
            relevant_move_lines.filtered(
                lambda ml: ml.package_id != ml.result_package_id
            ).ids
        )
        for package, move_lines in relevant_move_lines.grouped("package_id").items():
            pickings = move_lines.picking_id
            if (
                not pickings._is_single_transfer()
                or not pickings._check_move_lines_map_quant_package(package)
            ):
                ids_to_update.update(
                    pickings.move_line_ids.filtered(
                        lambda ml, package=package: ml.package_id == package
                    ).ids
                )

        return self.env["stock.move.line"].browse(ids_to_update)

    def _get_revert_inventory_move_values(self):
        self.ensure_one()
        return {
            "inventory_name": _("%s [reverted]", self.reference),
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "product_uom_qty": self.quantity,
            "company_id": self.company_id.id or self.env.company.id,
            "state": "confirmed",
            "location_id": self.location_dest_id.id,
            "location_dest_id": self.location_id.id,
            "is_inventory": True,
            "picked": True,
            "move_line_ids": [
                Command.create(
                    {
                        "product_id": self.product_id.id,
                        "product_uom_id": self.product_uom_id.id,
                        "quantity": self.quantity,
                        "location_id": self.location_dest_id.id,
                        "location_dest_id": self.location_id.id,
                        "company_id": self.company_id.id or self.env.company.id,
                        "lot_id": self.lot_id.id,
                        "package_id": self.package_id.id,
                        "result_package_id": self.package_id.id,
                        "owner_id": self.owner_id.id,
                    },
                )
            ],
        }

    def _get_linkable_moves(self):
        self.ensure_one()
        moves = self.picking_id.move_ids.filtered(
            lambda x: x.product_id == self.product_id
        )
        return moves.sorted(
            key=lambda m: m.product_uom_id.compare(m.quantity, m.product_uom_qty) < 0,
            reverse=True,
        )

    def _get_write_field_updates(self, vals):
        """Resolve the reservation-affecting relational fields present in `vals` to recordsets,
        so the reservation re-sync can compare old vs new characteristics. Returns an empty dict
        when the caller opts out via the `skip_uom_conversion` context key."""
        triggers = [
            ("location_id", "stock.location"),
            ("location_dest_id", "stock.location"),
            ("lot_id", "stock.lot"),
            ("package_id", "stock.package"),
            ("result_package_id", "stock.package"),
            ("owner_id", "res.partner"),
            ("product_uom_id", "uom.uom"),
        ]
        updates = {}
        if not self.env.context.get("skip_uom_conversion"):
            for key, model in triggers:
                if key in vals:
                    updates[key] = (
                        vals[key]
                        if isinstance(vals[key], models.BaseModel)
                        else self.env[model].browse(vals[key])
                    )
        return updates

    def _link_or_create_moves(self):
        """Give a `stock.move` to move lines created directly on a picking (e.g. from detailed
        operations). For an ongoing picking, attach to a compatible existing move if any, else
        a new one; a done picking always gets a fresh done move. New moves are batched --
        ongoing lines sharing a (picking, product) reuse one (mirroring `_get_linkable_moves`),
        while each done line gets its own.

        The link to an *existing* move is written per line on purpose, not batched:
        `stock.move.quantity` is the sum of its lines, so attaching one line changes
        whether `_get_linkable_moves` still reports that move as short of its demand for
        the next one. Deferring the writes would pile every line onto the first short
        move instead of spreading them.

        :return: OrderedSet of the newly created move ids.
        """
        new_move_vals = []
        lines_per_new_move = []
        new_move_idx_by_key = {}
        for move_line in self:
            if move_line.move_id or not move_line.picking_id:
                continue
            if move_line.picking_id.state != "done":
                linkable_moves = move_line._get_linkable_moves()
                if linkable_moves:
                    vals = {
                        "move_id": linkable_moves[0].id,
                        "picking_id": linkable_moves[0].picking_id.id,
                    }
                    if linkable_moves[0].picked:
                        vals["picked"] = True
                    move_line.write(vals)
                    continue
                key = (move_line.picking_id.id, move_line.product_id.id)
                idx = new_move_idx_by_key.get(key)
                if idx is None:
                    new_move_idx_by_key[key] = len(new_move_vals)
                    new_move_vals.append(move_line._prepare_stock_move_vals())
                    lines_per_new_move.append(move_line)
                else:
                    lines_per_new_move[idx] |= move_line
            else:
                new_move_vals.append(move_line._prepare_stock_move_vals())
                lines_per_new_move.append(move_line)

        created_moves = OrderedSet()
        if new_move_vals:
            for new_move, lines in zip(
                self.env["stock.move"].create(new_move_vals),
                lines_per_new_move,
                strict=True,
            ):
                lines.move_id = new_move.id
                if new_move.picked:
                    lines.picked = True
                created_moves.add(new_move.id)
        return created_moves

    @api.model
    def _log_message(self, thread, tracked_record, template, vals):
        """Post a chatter note on `thread` describing the changes `vals` applied to
        `tracked_record` (a `stock.move` or `stock.move.line`), resolving each changed
        relational id to its display name.

        This uses no records from `self`; `tracked_record` is passed to the template under the
        name ``move`` (the render contract expected by ``stock.message_body`` & friends).
        """
        data = vals.copy()
        if "lot_id" in vals and vals["lot_id"] != tracked_record.lot_id.id:
            data["lot_name"] = self.env["stock.lot"].browse(vals.get("lot_id")).name
        if "location_id" in vals:
            data["location_name"] = (
                self.env["stock.location"].browse(vals.get("location_id")).name
            )
        if "location_dest_id" in vals:
            data["location_dest_name"] = (
                self.env["stock.location"].browse(vals.get("location_dest_id")).name
            )
        if "package_id" in vals and vals["package_id"] != tracked_record.package_id.id:
            data["package_name"] = (
                self.env["stock.package"].browse(vals.get("package_id")).name
            )
        if (
            "result_package_id" in vals
            and vals["result_package_id"] != tracked_record.result_package_id.id
        ):
            data["result_package_dest_name"] = (
                self.env["stock.package"].browse(vals["result_package_id"]).name
            )
        if "owner_id" in vals and vals["owner_id"] != tracked_record.owner_id.id:
            data["owner_name"] = (
                self.env["res.partner"].browse(vals.get("owner_id")).name
            )
        thread.message_post_with_source(
            template,
            render_values={"move": tracked_record, "vals": dict(vals, **data)},
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _prepare_create_vals(self, vals_list):
        """Fill `company_id`, default `picked`, and quant-derived characteristics into each
        vals before creation, prefetching the parent moves/pickings in one shot so the per-vals
        reads (company_id, picked) don't fire a query each."""
        moves = self.env["stock.move"].browse(
            OrderedSet(vals["move_id"] for vals in vals_list if vals.get("move_id"))
        )
        pickings = self.env["stock.picking"].browse(
            OrderedSet(
                vals["picking_id"]
                for vals in vals_list
                if not vals.get("move_id") and vals.get("picking_id")
            )
        )
        moves.fetch(["company_id", "picked"])
        pickings.fetch(["company_id"])
        for vals in vals_list:
            if vals.get("move_id"):
                move = moves.browse(vals["move_id"])
                vals["company_id"] = move.company_id.id
                if "picked" not in vals:
                    vals["picked"] = move.picked
            elif vals.get("picking_id"):
                vals["company_id"] = pickings.browse(vals["picking_id"]).company_id.id
            if vals.get("quant_id"):
                vals.update(self._copy_quant_info(vals))

    def _prepare_new_lot_vals(self):
        self.ensure_one()
        vals = {
            "name": self.lot_name,
            "product_id": self.product_id.id,
        }
        if self.product_id.company_id and self.company_id in (
            self.product_id.company_id.all_child_ids | self.product_id.company_id
        ):
            vals["company_id"] = self.company_id.id
        return vals

    def _prepare_package_history_vals(self):
        packages = self.env["stock.package"].browse(
            self.result_package_id._get_all_package_dest_ids()
        )
        return [
            {
                "location_id": package.location_id.id,
                "location_dest_id": package.location_dest_id.id,
                "move_line_ids": [
                    Command.set(
                        package.move_line_ids.filtered(
                            lambda ml, package=package: ml.result_package_id == package
                        ).ids
                    )
                ],
                "picking_ids": [Command.set(package.picking_ids.ids)],
                "package_id": package.id,
                "package_name": package.dest_complete_name,
                "parent_orig_id": package.parent_package_id.id,
                "parent_orig_name": package.parent_package_id.complete_name,
                "parent_dest_id": package.package_dest_id.id,
                "parent_dest_name": package.package_dest_id.dest_complete_name,
                "outermost_dest_id": package.outermost_package_id.id,
            }
            for package in packages
        ]

    def _prepare_stock_move_vals(self):
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "product_uom_qty": (
                0
                if self.picking_id and self.picking_id.state != "done"
                else self.quantity
            ),
            "product_uom_id": self.product_uom_id.id,
            "location_id": self.picking_id.location_id.id,
            "location_dest_id": self.picking_id.location_dest_id.id,
            "picked": self.picked,
            "picking_id": self.picking_id.id,
            "state": self.picking_id.state,
            "picking_type_id": self.picking_id.picking_type_id.id,
            "restrict_partner_id": self.picking_id.owner_id.id,
            "company_id": self.picking_id.company_id.id,
            "partner_id": self.picking_id.partner_id.id,
        }

    def _pre_put_in_pack_hook(
        self,
        all_lines=False,
        package_id=False,
        package_type_id=False,
        package_name=False,
        from_package_wizard=False,
    ):
        move_lines = (
            all_lines
            if self.env.context.get("force_move_lines") and all_lines
            else self
        )
        action = move_lines._check_destinations()
        if action:
            return action
        if self._should_display_put_in_pack_wizard(
            package_id, package_type_id, package_name, from_package_wizard
        ):
            action = self.env["ir.actions.actions"]._for_xml_id(
                "stock.action_put_in_pack_wizard"
            )
            action["context"] = {
                **literal_eval(action.get("context", "{}")),
                "all_move_line_ids": move_lines.ids,
                "default_move_line_ids": self.ids,
                "default_location_dest_id": self.location_dest_id.id,
                "picking_ids": move_lines.picking_id.ids,
            }
            return action
        return None

    def _put_in_pack(self, package_id=False, package_type_id=False, package_name=False):
        if package_id:
            package = self.env["stock.package"].browse(package_id)
        elif package_type_id:
            package = self.env["stock.package"].create(
                {
                    "name": package_name,
                    "package_type_id": package_type_id,
                }
            )
        else:
            package_vals = {"name": package_name}
            package_type = self.move_id.packaging_uom_id.package_type_id
            if len(package_type) == 1:
                package_vals["package_type_id"] = package_type.id
            package = self.env["stock.package"].create(package_vals)
        if len(self) == 1:
            default_dest_location = self._get_default_dest_location()
            self.location_dest_id = default_dest_location._get_putaway_strategy(
                product=self.product_id, quantity=self.quantity, package=package
            )
        self.write({"result_package_id": package.id})
        return package

    def _post_put_in_pack_hook(self, package):
        if package and self.picking_type_id.auto_print_package_label:
            action = None
            if self.picking_type_id.package_label_to_print == "pdf":
                action = self.env.ref(
                    "stock.action_report_package_barcode_small"
                ).report_action(package.id, config=False)
            elif self.picking_type_id.package_label_to_print == "zpl":
                action = self.env.ref("stock.label_package_template").report_action(
                    package.id, config=False
                )
            if action:
                action.update({"close_on_report_download": True})
                clean_action(action, self.env)
                return action
        return package

    def _reservation_holding_lines(self):
        """The lines that hold a quant reservation: a non-zero quantity at a location
        that does not bypass reservation.

        The bypass verdict is taken on the *line's* own location, which is where
        :meth:`_apply_reservation_delta` puts the reservation. Deciding it on the move's
        location instead -- as the create path once did -- let a line whose source
        differed from its move's in usage class reserve without releasing (the release
        then landed on a sibling line's reservation) or release without reserving
        (stranding a reservation on a virtual location forever).

        (No `reserved_quant` context indirection either: quant
        `_update_reserved_quantity` is @api.model and `_gather` never filters `self`,
        so routing the call through a quant recordset from the context was a no-op
        pretending to target that quant.)
        """
        return self.filtered(
            lambda ml: (
                not ml.product_id.uom_id.is_zero(ml.quantity_product_uom)
                and not ml._should_bypass_reservation(ml.location_id)
            )
        )

    def _reserve_new_move_lines(self):
        """Reserve quants for the freshly created, not-yet-done move lines, then recompute the
        state of the moves whose reservation changed."""
        lines = self.filtered(
            lambda ml: ml.state != "done"
        )._reservation_holding_lines()
        lines._apply_reservation_delta(1)
        lines.move_id._recompute_state()

    def _resync_reservation(self, vals, updates):
        """Writing a reserved line's location, lot, package, owner, product_uom_id or quantity
        desyncs the quants' reserved quantity from the sum of the lines' `quantity_product_uom`,
        so unreserve the old characteristics and reserve the new ones (falling back to whatever
        is available). Runs for any reservation-affecting change -- `quantity`, or any trigger
        except the destination-side ones (`result_package_id`, `location_dest_id`), which are
        irrelevant to a reservation keyed on source characteristics; those keys are subtracted
        rather than tested for absence so the re-sync still fires when one is written alongside
        a real trigger.

        :return: the moves whose state must be recomputed because their quantity/uom changed.
        """
        moves_to_recompute_state = self.env["stock.move"]
        if not (
            (set(updates) - {"result_package_id", "location_dest_id"})
            or "quantity" in vals
        ):
            return moves_to_recompute_state
        for ml in self:
            if not ml.product_id.is_storable or ml.state == "done":
                continue
            if "quantity" in vals or "product_uom_id" in vals:
                new_ml_uom = updates.get("product_uom_id", ml.product_uom_id)
                new_reserved_qty = new_ml_uom._compute_quantity(
                    vals.get("quantity", ml.quantity),
                    ml.product_id.uom_id,
                    rounding_method="HALF-UP",
                )
                if ml.product_id.uom_id.compare(new_reserved_qty, 0) < 0:
                    raise UserError(
                        _("Reserving a negative quantity is not allowed."),
                    )
            else:
                new_reserved_qty = ml.quantity_product_uom

            if not ml.product_id.uom_id.is_zero(ml.quantity_product_uom):
                ml._synchronize_quant(
                    -ml.quantity_product_uom, ml.location_id, action="reserved"
                )

            if not ml._should_bypass_reservation(
                updates.get("location_id", ml.location_id)
            ):
                ml._synchronize_quant(
                    new_reserved_qty,
                    updates.get("location_id", ml.location_id),
                    action="reserved",
                    lot=updates.get("lot_id", ml.lot_id),
                    package=updates.get("package_id", ml.package_id),
                    owner=updates.get("owner_id", ml.owner_id),
                )

            if (
                "quantity" in vals
                and ml.product_uom_id.compare(vals["quantity"], ml.quantity)
            ) or "product_uom_id" in vals:
                moves_to_recompute_state |= ml.move_id
        return moves_to_recompute_state

    def _synchronize_quant(
        self,
        quantity,
        location,
        action="available",
        in_date=False,
        reserved_delta=None,
        **quants_value,
    ):
        """quantity is expressed in the product's UoM.

        ``reserved_delta`` is a signed reservation change applied to the *same* quant
        row, in the *same* update, as ``quantity`` -- for callers that change both at
        once (see `_apply_quant_move`'s ``release_reserved``). It is subject to the same
        bypass rule as ``action="reserved"``: a location that bypasses reservation holds
        none to change. It is meaningful only for ``action="available"``; the
        ``"reserved"`` branch changes a reservation and nothing else.

        A removal that drives a lot's on-hand negative is compensated from untracked
        stock at the same location. That repair is sized by the *on-hand shortfall*
        (:meth:`stock.quant._get_on_hand_shortfall`), capped at what this call moved --
        never by ``available_qty``, which nets off reserved quantity and so both
        overstates the repair and reports a shortfall for a quant that merely has all
        of its stock reserved. ``available_qty < 0`` survives only as the cheap
        pre-filter it validly is: reserved is non-negative, so a negative on-hand always
        shows up as a negative availability first.
        """
        lot = quants_value.get("lot", self.lot_id)
        package = quants_value.get("package", self.package_id)
        owner = quants_value.get("owner", self.owner_id)
        available_qty = 0
        if not self.product_id.is_storable or self.product_id.uom_id.is_zero(quantity):
            return 0, False
        if action == "available":
            if reserved_delta and self._should_bypass_reservation(location):
                reserved_delta = None
            available_qty, in_date = self.env["stock.quant"]._update_available_quantity(
                self.product_id,
                location,
                quantity,
                reserved_quantity=reserved_delta or False,
                lot_id=lot,
                package_id=package,
                owner_id=owner,
                in_date=in_date,
            )
        elif action == "reserved" and not self._should_bypass_reservation(location):
            self.env["stock.quant"]._update_reserved_quantity(
                self.product_id,
                location,
                quantity,
                lot_id=lot,
                package_id=package,
                owner_id=owner,
            )
        if lot and self.product_id.uom_id.compare(available_qty, 0) < 0:
            self._compensate_lot_shortfall(
                location, lot, package, owner, abs(quantity), in_date
            )
        return available_qty, in_date

    def _compensate_lot_shortfall(self, location, lot, package, owner, cap, in_date):
        """Cover a negative on-hand on `lot`'s quant by moving untracked stock at the
        same location onto it.

        Sized by the *on-hand* shortfall, capped at `cap` (what the caller just moved),
        and capped again at the untracked stock actually there. Never by
        `available_qty`: that nets off reserved quantity, so it both overstates the
        repair -- restoring the lot to where it started rather than to zero, leaving a
        shipped lot still showing stock -- and reports a shortfall for a quant whose
        on-hand is fine and merely fully reserved.
        """
        Quant = self.env["stock.quant"]
        shortfall = Quant._get_on_hand_shortfall(
            self.product_id, location, lot, package_id=package, owner_id=owner
        )
        if not shortfall:
            return
        untracked_qty = Quant._get_available_quantity(
            self.product_id,
            location,
            lot_id=False,
            package_id=package,
            owner_id=owner,
            strict=True,
        )
        if not untracked_qty:
            return
        taken_from_untracked_qty = min(untracked_qty, shortfall, cap)
        Quant._update_available_quantity(
            self.product_id,
            location,
            -taken_from_untracked_qty,
            lot_id=False,
            package_id=package,
            owner_id=owner,
            in_date=in_date,
        )
        Quant._update_available_quantity(
            self.product_id,
            location,
            taken_from_untracked_qty,
            lot_id=lot,
            package_id=package,
            owner_id=owner,
            in_date=in_date,
        )

    def _check_destinations(self):
        if len(self.location_dest_id) > 1:
            view_id = self.env.ref("stock.stock_package_destination_form_view").id
            wiz = self.env["stock.package.destination"].create(
                {
                    "move_line_ids": self.ids,
                    "location_dest_id": self[0].location_dest_id.id,
                }
            )
            return {
                "name": _("Choose destination location"),
                "view_mode": "form",
                "res_model": "stock.package.destination",
                "view_id": view_id,
                "views": [(view_id, "form")],
                "type": "ir.actions.act_window",
                "res_id": wiz.id,
                "target": "new",
            }
        return None

    def _check_write_allowed(self, vals):
        """Guard writes this fork forbids: changing the product outside 'draft' state, or
        changing the lot/serial across move lines of differing products.

        Idempotent, and `write` calls it twice on purpose: once on the raw vals, so the
        multi-product guard rejects a `quant_id` write before anything tries to resolve
        it, and again once `_copy_quant_info` has expanded `quant_id` into the
        characteristics it implies -- otherwise `quant_id` is a back door that changes
        `product_id` on a non-draft line without ever tripping the guard that a direct
        `product_id` write hits.

        A line that has *no* product yet is exempt from the first rule: filling one in
        is not changing one, and a blank detail row picking its product from a quant is
        the ordinary "Pick From" flow.
        """
        if "product_id" in vals and any(
            ml.product_id
            and vals.get("state", ml.state) != "draft"
            and vals["product_id"] != ml.product_id.id
            for ml in self
        ):
            raise UserError(_("Changing the product is only allowed in 'Draft' state."))

        if ("lot_id" in vals or "quant_id" in vals) and len(self.product_id) > 1:
            raise UserError(
                _(
                    "Changing the Lot/Serial number for move lines with different products is not allowed."
                ),
            )

    def _should_bypass_reservation(self, location):
        """Whether this line's stock at ``location`` is exempt from reservation.

        ``location`` is always the one the reservation actually sits at -- this
        line's, never its move's. Every reserve/release path routes through here so
        the two cannot disagree: deciding on the move's location while reserving at
        the line's let a line reserve without releasing (or release without
        reserving) whenever the two differed in usage class.

        Safe for lines without a move: ``stock.move._should_bypass_reservation``
        ``ensure_one()``s, so calling it through an empty ``move_id`` raises.
        """
        self.ensure_one()
        if self.move_id:
            return self.move_id._should_bypass_reservation(location)
        return not self.product_id.is_storable or location.should_bypass_reservation()

    def _should_display_put_in_pack_wizard(
        self, package_id, package_type_id, package_name, from_package_wizard
    ):
        define_package_type = self._should_set_package()
        return (
            define_package_type
            and not from_package_wizard
            and (not package_id and not package_type_id and not package_name)
        )

    def _should_set_package(self):
        """Reads `picking_type_id`, not `picking_id.picking_type_id`: the field is the
        one derivation of the concept, and modules that source it from elsewhere (mrp
        from the production order) extend the compute. Spelling it through the picking
        answered False for every line whose operation type does not come from one."""
        package_type = self.picking_type_id
        return len(package_type) == 1 and package_type.set_package_type
