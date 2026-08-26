from collections import Counter, defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import OrderedSet, groupby

from ..const import INVENTORY_REFERENCE_REVERTED
from odoo.addons.web.controllers.utils import clean_action

LOGGED_RELATIONS = [
    ("lot_id", "lot_name"),
    ("location_id", "location_name"),
    ("location_dest_id", "location_dest_name"),
    ("package_id", "package_name"),
    ("result_package_id", "result_package_dest_name"),
    ("owner_id", "owner_name"),
]


RESERVATION_KEY_FIELDS = (
    "product_id",
    "location_id",
    "lot_id",
    "package_id",
    "owner_id",
)

RENDERED_KEYS = frozenset(
    {
        "quantity",
        "product_uom_qty",
        "lot_name",
        "location_name",
        "location_dest_name",
        "package_name",
        "result_package_dest_name",
        "owner_name",
    }
)

SOURCE_QUANT_FIELDS = ("location_id", "package_id", "lot_id", "owner_id")

DEST_QUANT_FIELDS = ("location_dest_id", "result_package_id", "lot_id", "owner_id")

RESTOCK_TRIGGER_FIELDS = tuple(dict.fromkeys(SOURCE_QUANT_FIELDS + DEST_QUANT_FIELDS))


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
        """(%s, company_id)
        WHERE (state IS NULL OR state NOT IN ('done', 'cancel')) AND quantity_product_uom > 0 AND picked IS NOT TRUE"""
        % ", ".join(RESERVATION_KEY_FIELDS)
    )

    @api.model
    def _negative_quantity_message(self):
        return _("You can not enter negative quantities.")

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
            raise ValidationError(self._negative_quantity_message())

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = self._prepare_create_vals(vals_list)

        mls = super().create(vals_list)

        created_moves = mls._link_or_create_moves()
        mls._reserve_new_move_lines()
        created_moves._post_process_created_moves()
        done_lines = mls.filtered(lambda ml: ml.state == "done")
        for ml in done_lines.with_context(quants_cache=done_lines._quants_cache()):
            ml._settle_quant_move()

        if next_moves := done_lines._get_pending_dest_moves():
            next_moves._do_unreserve()
            next_moves._action_assign()

        if done_lines.move_id:
            done_lines.move_id._check_quantity()

        return mls

    def write(self, vals):
        self._check_write_allowed(vals)
        if vals.get("quant_id"):
            vals = {**vals, **self._prepare_quant_vals(vals)}
            self._check_write_allowed(vals)

        packages_to_check = self.env["stock.package"]
        if "result_package_id" in vals:
            packages_to_check = self._get_package_dests()

        updates = self._get_write_field_updates(vals)
        moves_to_recompute_state = self._resync_reservation(vals, updates)
        reservation_touched = bool(updates) or "quantity" in vals

        to_restock, to_adjust = (
            self._get_lines_to_requant(vals, updates)
            if reservation_touched
            else (self.browse(), self.browse())
        )
        requanted = to_restock | to_adjust
        next_moves = requanted._get_pending_dest_moves()
        requanted._log_quant_corrections(vals)
        reverted_in_dates = to_restock._revert_quant_moves(
            to_restock._filter_keeping_destination(vals, updates)
        )
        deltas = to_adjust._get_quantity_deltas(vals, updates)

        progressed = self._get_progressed_lines(vals, updates)
        if progressed == self:
            vals = {**vals, "date": fields.Datetime.now()}
            progressed = self.browse()

        res = super().write(vals)

        if progressed:
            progressed.date = fields.Datetime.now()
        to_restock._reapply_quant_moves(reverted_in_dates)
        to_adjust._apply_quantity_deltas(deltas)

        packages_to_check._clear_orphaned_package_dests()
        if reservation_touched:
            if mls_to_update := self._get_lines_not_entire_pack():
                mls_to_update.write({"is_entire_pack": False})

            next_moves._do_unreserve()
            next_moves._action_assign()

        if moves_to_recompute_state:
            moves_to_recompute_state._recompute_state()

        return res

    def unlink(self):
        self._unlink_except_done_or_cancel()
        self._release_quants()
        moves = self.mapped("move_id")
        packages = self._get_package_dests()
        res = super().unlink()
        if moves:
            moves.with_prefetch()._recompute_state()
        packages._clear_orphaned_package_dests()
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
        sudo_lines = self.sudo()
        for line, sudo_line in zip(self, sudo_lines, strict=True):
            line.allowed_uom_ids = (
                line.product_id.uom_id
                | line.product_id.uom_ids
                | sudo_line.product_id.seller_ids.product_uom_id
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

    @api.depends("picking_id.picking_type_id", "move_id.picking_type_id")
    def _compute_picking_type_id(self):
        for line in self:
            line.picking_type_id = (
                line.picking_id.picking_type_id or line.move_id.picking_type_id
            )

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
                record.move_id._get_visible_quantity() if record.move_id else 0.0
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

    @api.depends("quantity", "product_uom_id", "product_id.uom_id")
    def _compute_quantity_product_uom(self):
        for line in self:
            line.quantity_product_uom = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id, rounding_method="HALF-UP"
            )

    def _search_picking_type_id(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        return Domain("picking_id.picking_type_id", operator, value) | (
            Domain("picking_id", "=", False)
            & Domain("move_id.picking_type_id", operator, value)
        )

    @api.onchange("product_id", "product_uom_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.lots_visible = self.product_id.tracking != "none"

    @api.onchange("lot_name", "lot_id")
    def _onchange_serial_number(self):
        res = {}
        if self.product_id.tracking != "serial":
            return res
        if not self.quantity:
            self.quantity = 1

        serial = self._serial_name()
        if not serial:
            return res

        message = None
        siblings = self._get_similar_move_lines() - self
        if any(line._serial_name() == serial for line in siblings):
            message = _(
                "You cannot use the same serial number twice. Please correct the serial numbers encoded."
            )
        elif self.lot_id:
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
        else:
            quants = (
                self.env["stock.lot"]
                .search(
                    [
                        ("product_id", "=", self.product_id.id),
                        ("name", "=", serial),
                        "|",
                        ("company_id", "=", False),
                        ("company_id", "=", self.company_id.id),
                    ],
                )
                .quant_ids.filtered(
                    lambda q: (
                        not q.product_uom_id.is_zero(q.quantity)
                        and q.location_id.usage in ["customer", "internal", "transit"]
                    )
                )
            )
            if quants:
                message = _(
                    "Serial number (%(serial_number)s) already exists in location(s): %(location_list)s. Please correct the serial number encoded.",
                    serial_number=serial,
                    location_list=quants.location_id.mapped("display_name"),
                )
        if message:
            res["warning"] = {"title": _("Warning"), "message": message}
        return res

    def _serial_name(self):
        self.ensure_one()
        return self.lot_id.name or self.lot_name

    @api.onchange("quantity", "product_uom_id")
    def _onchange_quantity(self):
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
        ml_ids_tracked_without_lot = OrderedSet()
        ml_ids_to_delete = OrderedSet()
        ml_ids_needing_lot_check = OrderedSet()

        for ml in self:
            qty_done_float_compared = ml.product_uom_id.compare(ml.quantity, 0)
            if qty_done_float_compared < 0:
                raise UserError(self._negative_quantity_message())
            if qty_done_float_compared == 0:
                if not ml.is_inventory:
                    ml_ids_to_delete.add(ml.id)
                continue
            if ml.product_id.tracking == "none":
                continue
            picking_type = ml.picking_type_id
            if not ml._has_lot_context():
                ml_ids_tracked_without_lot.add(ml.id)
                continue
            if (
                not picking_type
                or ml.lot_id
                or (
                    not picking_type.use_create_lots
                    and not picking_type.use_existing_lots
                )
            ):
                continue
            if picking_type.use_create_lots:
                ml_ids_needing_lot_check.add(ml.id)
            else:
                ml_ids_tracked_without_lot.add(ml.id)

        return (
            self.browse(ml_ids_to_delete),
            self.browse(ml_ids_needing_lot_check),
            self.browse(ml_ids_tracked_without_lot),
        )

    def _resolve_done_lots(self):
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

        self.browse(ml_ids_to_create_lot)._create_production_lots()
        return self.browse(ml_ids_tracked_without_lot)

    def _raise_missing_lot(self):
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
        ml_ids_to_ignore = OrderedSet()
        for ml in self.with_context(quants_cache=self._quants_cache()):
            ml.with_context(bypass_entire_pack=True)._settle_quant_move(
                release_reserved=True, ml_ids_to_ignore=ml_ids_to_ignore
            )
            ml_ids_to_ignore.add(ml.id)

    def action_view_reference(self):
        self.ensure_one()
        if self.move_id:
            action = self.move_id.action_view_reference()
            if action.get("res_model") != "stock.move":
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
                move_lines if force_move_lines else False,
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
        if packages_to_pack:
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
        revertable = self.filtered(
            lambda ml: ml.is_inventory and not ml.product_uom_id.is_zero(ml.quantity)
        )
        move_vals = [
            move_line._prepare_revert_inventory_move_vals()
            for move_line in revertable.with_context(inventory_mode=False)
        ]
        if not revertable:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "message": _("There are no inventory adjustments to revert."),
                },
            }
        moves = (
            self.env["stock.move"].with_context(inventory_mode=False).create(move_vals)
        )
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
            locations = smls.move_id.location_dest_id.child_internal_location_ids
            excluded_smls = set(smls.ids)
            if package.package_type_id:
                smls._apply_putaway_by_package_type(package, locations, excluded_smls)
            elif package:
                smls._apply_putaway_keeping_package_together(locations, excluded_smls)
            else:
                smls._apply_putaway_per_line(excluded_smls)

    def _apply_putaway_by_package_type(self, package, locations, excluded_smls):
        for location_dest, dest_smls in self.grouped(
            lambda sml: sml.move_id.location_dest_id
        ).items():
            if not location_dest:
                continue
            dest_smls.location_dest_id = location_dest.with_context(
                exclude_sml_ids=excluded_smls,
                products=dest_smls.product_id,
                locations=locations,
            )._get_putaway_strategy(self.env["product.product"], package=package)

    def _apply_putaway_keeping_package_together(self, locations, excluded_smls):
        used_locations = set()
        for sml in self:
            if len(used_locations) > 1:
                break
            putaway_location = sml.move_id.location_dest_id.with_context(
                exclude_sml_ids=excluded_smls,
                locations=locations,
            )._get_putaway_strategy(sml.product_id, quantity=sml.quantity)
            if putaway_location != sml.location_dest_id:
                sml.location_dest_id = putaway_location
            excluded_smls.discard(sml.id)
            used_locations.add(sml.location_dest_id)
        if len(used_locations) > 1:
            for move, grouped_smls in self.grouped("move_id").items():
                grouped_smls.location_dest_id = move.location_dest_id

    def _apply_putaway_per_line(self, excluded_smls):
        for sml in self:
            putaway_location = sml.move_id.location_dest_id.with_context(
                exclude_sml_ids=excluded_smls,
            )._get_putaway_strategy(
                sml.product_id,
                quantity=sml.quantity,
                packaging=sml.move_id.packaging_uom_id,
            )
            if putaway_location != sml.location_dest_id:
                sml.location_dest_id = putaway_location
            excluded_smls.discard(sml.id)

    def _apply_quant_move(
        self, *, quantity=None, reverse=False, in_date=False, release_reserved=False
    ):
        self.ensure_one()
        qty = self.quantity_product_uom if quantity is None else quantity
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

    def _get_lines_to_requant(self, vals, updates):
        restock_ids = OrderedSet()
        adjust_ids = OrderedSet()
        for ml in self:
            if ml.state != "done" or not ml.product_id.is_storable:
                continue
            changed = ml._get_changed_write_fields(vals, updates)
            if not changed:
                continue
            if changed.intersection(RESTOCK_TRIGGER_FIELDS):
                restock_ids.add(ml.id)
            else:
                adjust_ids.add(ml.id)
        return self.browse(restock_ids), self.browse(adjust_ids)

    def _filter_keeping_destination(self, vals, updates):
        return self.filtered(
            lambda ml: (
                not ml._get_changed_write_fields(vals, updates).intersection(
                    DEST_QUANT_FIELDS
                )
            )
        )

    def _revert_quant_moves(self, keeping_destination=None):
        keep = set((keeping_destination or self.browse())._ids)
        in_dates = {}
        for ml in self.with_context(quants_cache=self._quants_cache()):
            _available_qty, in_date = ml._apply_quant_move(reverse=True)
            if ml.id in keep:
                in_dates[ml.id] = in_date
        if self.move_id:
            self.move_id._check_quantity()
        return in_dates

    def _reapply_quant_moves(self, in_dates=None):
        in_dates = in_dates or {}
        for ml in self.with_context(quants_cache=self._quants_cache()):
            ml._settle_quant_move(in_date=in_dates.get(ml.id, False))

    def _get_quantity_deltas(self, vals, updates):
        return {
            ml.id: ml._get_new_quantity_product_uom(vals, updates)
            - ml.quantity_product_uom
            for ml in self
        }

    def _apply_quantity_deltas(self, deltas):
        for ml in self.with_context(quants_cache=self._quants_cache()):
            ml._settle_quant_move(quantity=deltas[ml.id])
        if self.move_id:
            self.move_id._check_quantity()

    def _log_quant_corrections(self, vals):
        for picking, lines in self.grouped("picking_id").items():
            if not picking:
                continue
            corrections = []
            for ml in lines:
                data = ml._resolve_logged_relations(ml, vals)
                if RENDERED_KEYS & set(data):
                    corrections.append({"move": ml, "vals": data})
            if not corrections:
                continue
            picking.message_post_with_source(
                "stock.track_move_lines_template",
                render_values={"corrections": corrections},
                subtype_xmlid="mail.mt_note",
            )

    def _quants_cache(self):
        if not self:
            return None
        return self.env["stock.quant"]._get_quants_by_products_locations(
            self.product_id,
            self.location_id | self.location_dest_id,
            lot_scope=self.lot_id,
        )

    def _settle_quant_move(
        self,
        *,
        quantity=None,
        in_date=False,
        release_reserved=False,
        ml_ids_to_ignore=None,
    ):
        self.ensure_one()
        available_qty, _in_date = self._apply_quant_move(
            quantity=quantity, in_date=in_date, release_reserved=release_reserved
        )
        if self.product_id.uom_id.compare(available_qty, 0) < 0:
            self._free_reservation(
                abs(available_qty), ml_ids_to_ignore=ml_ids_to_ignore
            )

    def _reservation_key(self):
        self.ensure_one()
        return tuple(self[name] for name in RESERVATION_KEY_FIELDS)

    @api.model
    def _get_outstanding_reservation_domain(self):
        return Domain(
            [
                ("state", "not in", ["done", "cancel"]),
                ("quantity_product_uom", ">", 0.0),
                ("picked", "=", False),
            ]
        )

    def _update_quant_reservations(self, deltas):
        for (product, location, lot, package, owner), quantity in deltas.items():
            if product.uom_id.is_zero(quantity):
                continue
            self.env["stock.quant"]._update_reserved_quantity(
                product,
                location,
                quantity,
                lot_id=lot,
                package_id=package,
                owner_id=owner,
            )

    def _reserve_quants(self):
        return self._apply_reservation_sign(1)

    def _release_quants(self):
        return self._apply_reservation_sign(-1)

    def _apply_reservation_sign(self, sign):
        holding = self._reservation_holding_lines()
        deltas = defaultdict(float)
        for ml in holding:
            deltas[ml._reservation_key()] += sign * ml.quantity_product_uom
        holding._update_quant_reservations(deltas)
        return holding

    def _get_progressed_lines(self, vals, updates):
        if "date" in vals or not (
            "product_uom_id" in vals or "quantity" in vals or vals.get("picked", False)
        ):
            return self.browse()
        progressed_ids = set()
        for ml in self:
            if ml.state in ("draft", "cancel", "done"):
                continue
            if vals.get("picked", False) and not ml.picked:
                progressed_ids.add(ml.id)
                continue
            if ("quantity" in vals or "product_uom_id" in vals) and ml.picked:
                new_qty = ml._get_new_quantity_product_uom(vals, updates)
                if ml.product_uom_id.compare(ml.quantity_product_uom, new_qty) < 0:
                    progressed_ids.add(ml.id)
        return self.browse(progressed_ids)

    def _compute_sale_price(self):
        pass

    def _create_production_lots(self):
        self._check_serials_unique()
        key_to_mls = defaultdict(lambda: self.env["stock.move.line"])
        for ml in self:
            key_to_mls[ml.product_id.id, ml.lot_name] |= ml

        lots = self.env["stock.lot"].create(
            [mls[0]._prepare_new_lot_vals() for mls in key_to_mls.values()]
        )
        for lot, mls in zip(lots, key_to_mls.values(), strict=True):
            mls.with_prefetch(self._prefetch_ids).write(
                {"lot_id": lot.with_prefetch(lots._ids).id}
            )

    def _check_serials_unique(self):
        serials = Counter(
            ml.lot_name for ml in self if ml.tracking == "serial" and ml.lot_name
        )
        duplicated = sorted(name for name, count in serials.items() if count > 1)
        if duplicated:
            raise ValidationError(
                _(
                    "A serial number identifies one unit, so it can appear on one move line "
                    "only. These are used more than once:\n%(serials)s",
                    serials="\n".join(f"- {name}" for name in duplicated),
                ),
            )

    def _prepare_quant_vals(self, vals):
        quant = self.env["stock.quant"].browse(vals.get("quant_id", 0))
        return {name: quant[name].id for name in RESERVATION_KEY_FIELDS}

    def _has_lot_context(self):
        self.ensure_one()
        return (
            self.move_id.picking_type_id
            or self.is_inventory
            or self.lot_id
            or self.move_id.scrap_id
        )

    def _free_reservation(self, quantity, ml_ids_to_ignore=None):
        self.ensure_one()
        product, location = self.product_id, self.location_id
        ml_ids_to_ignore = OrderedSet(ml_ids_to_ignore or ()) | OrderedSet(self.ids)

        if self._should_bypass_reservation(location):
            return
        self = self.with_context(quants_cache=None)

        move_to_reassign = self.env["stock.move"]
        to_unlink_candidate_ids = set()
        product_uom = product.uom_id
        for candidate in self._get_outdated_candidates(ml_ids_to_ignore):
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

    def _get_outdated_candidates(self, ml_ids_to_ignore):
        self.ensure_one()

        def current_picking_first(candidate):
            date = candidate.picking_id.date_planned or candidate.move_id.date
            return (
                candidate.picking_id != self.move_id.picking_id,
                -date.timestamp() if date else 0,
                -candidate.id,
            )

        domain = self._get_outstanding_reservation_domain()
        domain &= Domain(
            [(name, "=", self[name].id) for name in RESERVATION_KEY_FIELDS]
        )
        domain &= Domain("id", "not in", tuple(ml_ids_to_ignore))
        return self.search(domain).sorted(current_picking_first)

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

    def _get_aggregated_product_quantities(
        self, *, strict=False, except_package=False, **kwargs
    ):
        aggregated_move_lines = {}
        backorders = self._get_backorders()
        base_key_by_move = {}

        def base_key(move):
            key = base_key_by_move.get(move.id)
            if key is None:
                key = base_key_by_move[move.id] = self._get_aggregated_properties(
                    move=move
                )["line_key"]
            return key

        agg_keys_by_base = defaultdict(list)
        undelivered_key = {}
        backorder_lines_by_base = defaultdict(lambda: self.env["stock.move.line"])
        for bo_line in backorders.move_line_ids:
            backorder_lines_by_base[base_key(bo_line.move_id)] |= bo_line

        for move_line in self:
            if except_package and move_line.result_package_id:
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
            undelivered_key.setdefault(move_line.move_id, line_key)
            if line_key not in aggregated_move_lines:
                agg_keys_by_base[base_key(move_line.move_id)].append(line_key)
                aggregated_move_lines[line_key] = {
                    **aggregated_properties,
                    "quantity": quantity,
                    "packaging_quantity": packaging_quantity,
                    "qty_ordered": quantity,
                    "packaging_qty_ordered": packaging_quantity,
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

        if strict:
            return aggregated_move_lines
        self._add_undelivered_quantities(
            aggregated_move_lines, undelivered_key, backorder_lines_by_base, base_key
        )
        self._aggregate_empty_moves(
            aggregated_move_lines, agg_keys_by_base, self.picking_id | backorders
        )
        return aggregated_move_lines

    def _add_undelivered_quantities(
        self, aggregated_move_lines, undelivered_key, backorder_lines_by_base, base_key
    ):
        for move, line_key in undelivered_key.items():
            entry = aggregated_move_lines[line_key]
            uom = entry["product_uom_id"]
            backorder_lines = backorder_lines_by_base.get(
                base_key(move), self.env["stock.move.line"]
            )
            undelivered = move.product_uom_qty + sum(
                backorder_lines.move_id.mapped("product_uom_qty")
            )
            undelivered -= sum(
                line.product_uom_id._compute_quantity(line.quantity, uom)
                for line in move.move_line_ids
            )
            if uom.is_zero(undelivered):
                continue
            entry["qty_ordered"] += undelivered
            entry["packaging_qty_ordered"] += uom._compute_quantity(
                undelivered, move.packaging_uom_id
            )

    def _get_backorders(self):
        backorders = self.env["stock.picking"]
        pickings = self.picking_id
        while unvisited := pickings.backorder_ids - backorders - self.picking_id:
            backorders |= unvisited
            pickings = unvisited
        return backorders

    def _aggregate_empty_moves(self, aggregated_move_lines, agg_keys_by_base, pickings):
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

            matching_keys = agg_keys_by_base.get(line_key, ())
            if not matching_keys and not to_bypass:
                agg_keys_by_base.setdefault(line_key, []).append(line_key)
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

    def get_move_line_quant_match(self, move_id, dirty_move_line_ids, dirty_quant_ids):
        move = self.env["stock.move"].browse(move_id)
        deleted_move_lines = move.move_line_ids - self
        dirty_move_lines = self.env["stock.move.line"].browse(dirty_move_line_ids)
        quants = []
        lines = []
        domain = Domain("id", "in", dirty_quant_ids) | Domain.OR(
            Domain(
                [(name, "=", move_line[name].id) for name in RESERVATION_KEY_FIELDS],
            )
            for move_line in dirty_move_lines | deleted_move_lines
        )
        if not domain.is_false():
            def _match_key(record):
                return tuple(record[name].id for name in RESERVATION_KEY_FIELDS)

            empty = self.env["stock.move.line"]
            dirty_by_key = defaultdict(lambda: empty)
            for move_line in dirty_move_lines:
                dirty_by_key[_match_key(move_line)] |= move_line
            deleted_by_key = defaultdict(lambda: empty)
            for move_line in deleted_move_lines:
                deleted_by_key[_match_key(move_line)] |= move_line

            for quant in self.env["stock.quant"].search(domain):
                key = _match_key(quant)
                dirty_lines = dirty_by_key.get(key, empty)
                deleted_lines = deleted_by_key.get(key, empty)
                quants.append(
                    {
                        "id": quant.id,
                        "available_quantity": quant.available_quantity
                        + sum(ml.quantity_product_uom for ml in deleted_lines),
                        "move_line_ids": dirty_lines.ids,
                    },
                )
                lines += [
                    {"id": ml.id, "quantity": ml.quantity, "quant_id": quant.id}
                    for ml in dirty_lines
                ]
        return {"quants": quants, "move_lines": lines}

    def _get_similar_move_lines(self):
        self.ensure_one()
        picking = self.move_id.picking_id or self.picking_id
        return picking.move_line_ids.filtered(
            lambda ml: ml.product_id == self.product_id and (ml.lot_id or ml.lot_name)
        )

    def _get_lines_and_packages_to_pack(self, picked_first=True):
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

    def _prepare_revert_inventory_move_vals(self):
        self.ensure_one()
        return {
            "inventory_name": INVENTORY_REFERENCE_REVERTED % self.reference,
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

    def _get_package_dests(self):
        return self.env["stock.package"].browse(
            self.result_package_id._get_all_package_dest_ids()
        )

    def _get_pending_dest_moves(self):
        return self.move_id.move_dest_ids.filtered(
            lambda move: move.state not in ("done", "cancel")
        )

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
        updates = {}
        if not self.env.context.get("skip_uom_conversion"):
            for key in (*RESTOCK_TRIGGER_FIELDS, "product_uom_id"):
                if key in vals:
                    updates[key] = (
                        vals[key]
                        if isinstance(vals[key], models.BaseModel)
                        else self.env[self._fields[key].comodel_name].browse(vals[key])
                    )
        return updates

    def _get_changed_write_fields(self, vals, updates):
        self.ensure_one()
        changed = {name for name, value in updates.items() if self[name] != value}
        if "quantity" in vals and self.product_uom_id.compare(
            vals["quantity"], self.quantity
        ):
            changed.add("quantity")
        return changed

    def _get_new_quantity_product_uom(self, vals, updates):
        self.ensure_one()
        return updates.get("product_uom_id", self.product_uom_id)._compute_quantity(
            vals.get("quantity", self.quantity),
            self.product_id.uom_id,
            rounding_method="HALF-UP",
        )

    def _link_or_create_moves(self):
        needing_a_move = self.filtered(
            lambda ml: not ml.move_id and ml.picking_id
        )._link_to_existing_moves()
        return needing_a_move._create_moves()

    def _link_to_existing_moves(self):
        unlinked = self.browse()
        for move_line in self:
            linkable_moves = (
                move_line._get_linkable_moves()
                if move_line.picking_id.state != "done"
                else False
            )
            if not linkable_moves:
                unlinked |= move_line
                continue
            vals = {
                "move_id": linkable_moves[0].id,
                "picking_id": linkable_moves[0].picking_id.id,
            }
            if linkable_moves[0].picked:
                vals["picked"] = True
            move_line.write(vals)
        return unlinked

    def _create_moves(self):
        new_move_vals = []
        lines_per_new_move = []
        move_idx_by_key = {}
        for move_line in self:
            key = (
                (move_line.picking_id.id, move_line.product_id.id)
                if move_line.picking_id.state != "done"
                else None
            )
            idx = move_idx_by_key.get(key) if key else None
            if idx is not None:
                lines_per_new_move[idx] |= move_line
                continue
            if key:
                move_idx_by_key[key] = len(new_move_vals)
            new_move_vals.append(move_line._prepare_stock_move_vals())
            lines_per_new_move.append(move_line)

        if not new_move_vals:
            return self.env["stock.move"]
        created_moves = self.env["stock.move"].create(new_move_vals)
        for new_move, lines in zip(created_moves, lines_per_new_move, strict=True):
            lines.move_id = new_move.id
            if new_move.picked:
                lines.picked = True
        return created_moves

    @api.model
    def _log_message(self, thread, tracked_record, template, vals):
        data = self._resolve_logged_relations(tracked_record, vals)
        thread.message_post_with_source(
            template,
            render_values={"move": tracked_record, "vals": data},
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _resolve_logged_relations(self, tracked_record, vals):
        data = dict(vals)
        for field, render_key in LOGGED_RELATIONS:
            if field not in data:
                continue
            value = data[field]
            record = (
                value
                if isinstance(value, models.BaseModel)
                else self.env[self._fields[field].comodel_name].browse(value)
            )
            if record == tracked_record[field]:
                del data[field]
                continue
            data[render_key] = record.name
        return data

    @api.model
    def _prepare_create_vals(self, vals_list):
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
        prepared = []
        for vals in vals_list:
            changes = {}
            if vals.get("move_id"):
                move = moves.browse(vals["move_id"])
                changes["company_id"] = move.company_id.id
                if "picked" not in vals:
                    changes["picked"] = move.picked
            elif vals.get("picking_id"):
                changes["company_id"] = pickings.browse(
                    vals["picking_id"]
                ).company_id.id
            if vals.get("quant_id"):
                changes.update(self._prepare_quant_vals(vals))
            prepared.append({**vals, **changes} if changes else vals)
        return prepared

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
        packages = self._get_package_dests()
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
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "picked": self.picked,
            "picking_id": self.picking_id.id,
            "state": self.picking_id.state,
            "picking_type_id": self.picking_type_id.id,
            "restrict_partner_id": self.picking_id.owner_id.id,
            "company_id": self.company_id.id,
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
        move_lines = all_lines or self
        action = move_lines._check_destinations()
        if action:
            return action
        if self._should_display_put_in_pack_wizard(
            package_id, package_type_id, package_name, from_package_wizard
        ):
            action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
                "stock.action_put_in_pack_wizard"
            )
            action["context"] = {
                **self.env["ir.actions.actions"]._eval_action_context(action.get("context")),
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
        return self.filtered(
            lambda ml: (
                not ml.product_id.uom_id.is_zero(ml.quantity_product_uom)
                and not ml._should_bypass_reservation(ml.location_id)
            )
        )

    def _reserve_new_move_lines(self):
        to_reserve = self.filtered(lambda ml: ml.state != "done")
        reserved = to_reserve._reserve_quants()
        (
            reserved.move_id
            | to_reserve.move_id.filtered(lambda move: move.state != "draft")
        )._recompute_state()

    def _resync_reservation(self, vals, updates):
        moves_to_recompute_state = self.env["stock.move"]
        if not (
            (set(updates) - {"result_package_id", "location_dest_id"})
            or "quantity" in vals
        ):
            return moves_to_recompute_state
        deltas = defaultdict(float)
        for ml in self:
            if not ml.product_id.is_storable or ml.state == "done":
                continue
            if "quantity" in vals or "product_uom_id" in vals:
                new_reserved_qty = ml._get_new_quantity_product_uom(vals, updates)
                if ml.product_id.uom_id.compare(new_reserved_qty, 0) < 0:
                    raise UserError(self._negative_quantity_message())
            else:
                new_reserved_qty = ml.quantity_product_uom

            if not ml.product_id.uom_id.is_zero(
                ml.quantity_product_uom
            ) and not ml._should_bypass_reservation(ml.location_id):
                deltas[ml._reservation_key()] -= ml.quantity_product_uom

            new_location = updates.get("location_id", ml.location_id)
            if not ml._should_bypass_reservation(new_location):
                deltas[
                    ml.product_id,
                    new_location,
                    updates.get("lot_id", ml.lot_id),
                    updates.get("package_id", ml.package_id),
                    updates.get("owner_id", ml.owner_id),
                ] += new_reserved_qty

            if (
                "quantity" in vals
                and ml.product_uom_id.compare(vals["quantity"], ml.quantity)
            ) or "product_uom_id" in vals:
                moves_to_recompute_state |= ml.move_id

        self._update_quant_reservations(deltas)
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
        if "product_id" in vals and any(
            ml.product_id
            and vals["product_id"] != ml.product_id.id
            and (ml.move_id or vals.get("state", ml.state) != "draft")
            for ml in self
        ):
            raise UserError(
                _(
                    "A move line's product is its operation's. Change it there, or"
                    " replace the line."
                )
            )

        if ("lot_id" in vals or "quant_id" in vals) and len(self.product_id) > 1:
            raise UserError(
                _(
                    "Changing the Lot/Serial number for move lines with different products is not allowed."
                ),
            )

    def _should_bypass_reservation(self, location):
        self.ensure_one()
        if self.move_id:
            return self.move_id._should_bypass_reservation(location)
        return not self.product_id.is_storable or location.should_bypass_reservation()

    def _should_display_put_in_pack_wizard(
        self, package_id, package_type_id, package_name, from_package_wizard
    ):
        return (
            self._should_set_package()
            and not from_package_wizard
            and not (package_id or package_type_id or package_name)
        )

    def _should_set_package(self):
        picking_type = self.picking_type_id
        return len(picking_type) == 1 and picking_type.set_package_type
