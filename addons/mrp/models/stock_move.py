from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import OrderedSet, float_is_zero


class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model
    def default_get(self, fields):
        defaults = super().default_get(fields)
        production_id = self.env.context.get(
            "default_raw_material_production_id"
        ) or self.env.context.get("default_production_id")
        if not production_id:
            return defaults
        production = self.env["mrp.production"].browse(production_id)
        if production.state == "draft":
            defaults["reference_ids"] = production.reference_ids.ids
            defaults["reference"] = production.name
        elif production.state == "done":
            defaults["state"] = "done"
            defaults["additional"] = True
            defaults["product_uom_qty"] = 0.0
        elif production.state != "cancel":
            # `draft` is what `_autoconfirm_production` looks for: a line added to
            # a live order is confirmed with the order's next transition, not now.
            defaults["state"] = "draft"
            defaults["product_uom_qty"] = 0.0
        return defaults

    created_production_id = fields.Many2one(
        "mrp.production",
        "Created Production Order",
        check_company=True,
        index="btree_not_null",
    )
    production_id = fields.Many2one(
        "mrp.production",
        "Production Order for finished products",
        check_company=True,
        index="btree_not_null",
        ondelete="cascade",
    )
    raw_material_production_id = fields.Many2one(
        "mrp.production",
        "Production Order for components",
        check_company=True,
        index="btree_not_null",
        ondelete="cascade",
    )
    production_group_id = fields.Many2one(
        "mrp.production.group",
        "Used for Productions",
        index="btree_not_null",
    )
    unbuild_id = fields.Many2one(
        "mrp.unbuild", "Disassembly Order", check_company=True, index="btree_not_null"
    )
    consume_unbuild_id = fields.Many2one(
        "mrp.unbuild",
        "Consumed Disassembly Order",
        check_company=True,
        index="btree_not_null",
    )
    allowed_operation_ids = fields.One2many(
        "mrp.routing.workcenter",
        related="raw_material_production_id.bom_id.operation_ids",
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter",
        "Operation To Consume",
        check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]",
    )
    workorder_id = fields.Many2one(
        "mrp.workorder",
        "Work Order To Consume",
        copy=False,
        check_company=True,
        index="btree_not_null",
    )
    bom_line_id = fields.Many2one("mrp.bom.line", "BoM Line", check_company=True)
    byproduct_id = fields.Many2one(
        "mrp.bom.byproduct",
        "By-products",
        check_company=True,
        help="By-product line that generated the move in a manufacturing order",
    )
    unit_factor = fields.Float(
        "Unit Factor", compute="_compute_unit_factor", store=True
    )
    order_finished_lot_ids = fields.Many2many(
        "stock.lot",
        string="Finished Lot/Serial Number",
        related="raw_material_production_id.lot_producing_ids",
    )
    should_consume_qty = fields.Float(
        "Quantity To Consume",
        compute="_compute_should_consume_qty",
        digits="Product Unit",
    )
    cost_share = fields.Float(
        "Cost Share (%)",
        digits=0,
        help="The percentage of the final production cost for this by-product. The total of all by-products' cost share must be smaller or equal to 100.",
    )
    product_qty_available = fields.Float(
        "Product On Hand Quantity",
        related="product_id.qty_available",
        depends=["product_id"],
    )
    product_virtual_available = fields.Float(
        "Product Forecasted Quantity",
        related="product_id.qty_available_virtual",
        depends=["product_id"],
    )
    manual_consumption = fields.Boolean(
        "Manual Consumption",
        compute="_compute_manual_consumption",
        store=True,
        readonly=False,
        help="When activated, then the registration of consumption for that component is recorded manually exclusively.\n"
        "If not activated, and any of the components consumption is edited manually on the manufacturing order, Odoo assumes manual consumption also.",
    )

    _one_production = models.Constraint(
        "CHECK (production_id IS NULL"
        " OR raw_material_production_id IS NULL"
        " OR production_id = raw_material_production_id)",
        "A stock move cannot be a component of one manufacturing order and an "
        "output of another.",
    )

    def _get_production(self):
        """The manufacturing order this move belongs to, whichever side it is on.

        A move is normally on one side only -- a component
        (`raw_material_production_id`) or an output (`production_id`). It can
        carry both: scrapping a component from an order leaves the order on both
        fields, and so does moving an output into the component list. When it
        does, `_one_production` holds that the two name the *same* order, which
        is why this can pick either and why thirteen call sites were free to
        spell the choice in whichever order they happened to.
        """
        self.ensure_one()
        return self.raw_material_production_id or self.production_id

    @api.depends("product_id.bom_ids", "product_id.bom_ids.product_uom_id")
    def _compute_allowed_uom_ids(self):
        super()._compute_allowed_uom_ids()
        for move in self:
            move.allowed_uom_ids |= move.product_id.bom_ids.product_uom_id

    @api.depends("production_id")
    def _compute_packaging_uom_id(self):
        super()._compute_packaging_uom_id()
        for move in self:
            if move.production_id:
                move.packaging_uom_id = move.production_id.product_uom_id

    @api.depends("product_id", "bom_line_id", "bom_line_id.operation_id")
    def _compute_manual_consumption(self):
        for move in self:
            if move != move._origin:
                move.manual_consumption = move._origin.manual_consumption
            elif not move.manual_consumption:
                move.manual_consumption = move._is_manual_consumption()

    @api.depends(
        "raw_material_production_id.location_src_id",
        "production_id.production_location_id",
    )
    def _compute_location_id(self):
        ids_to_super = set()
        for move in self:
            if move.production_id:
                move.location_id = move.production_id.production_location_id
            elif move.raw_material_production_id:
                move.location_id = move.raw_material_production_id.location_src_id
            else:
                ids_to_super.add(move.id)
        return super(StockMove, self.browse(ids_to_super))._compute_location_id()

    @api.depends(
        "raw_material_production_id.production_location_id",
        "production_id.location_dest_id",
    )
    def _compute_location_dest_id(self):
        ids_to_super = set()
        for move in self:
            if move.production_id:
                move.location_dest_id = move.production_id.location_dest_id
            elif move.raw_material_production_id:
                move.location_dest_id = (
                    move.raw_material_production_id.production_location_id
                )
            else:
                ids_to_super.add(move.id)
        return super(StockMove, self.browse(ids_to_super))._compute_location_dest_id()

    @api.depends(
        "bom_line_id",
        "picking_id.move_ids",
        "raw_material_production_id.move_raw_ids",
    )
    def _compute_description_picking(self):
        super()._compute_description_picking()
        # "Kit - 2/3" numbers the kit's components, so both numbers have to come
        # from a population the record fixes. Counting `self` made them depend on
        # the compute batch instead: read together the three components of a kit
        # report 1/3, 2/3, 3/3, and the same move read alone -- its own form, one
        # `read` over one id -- reported 1/1. The document is the population; the
        # BoM is not, because a line can produce no move at all (a service line,
        # an attribute-skipped line) and would still be counted.
        siblings = (
            self
            | self.picking_id.move_ids
            | self.raw_material_production_id.move_raw_ids
        )
        present_lines = siblings.bom_line_id
        bom_line_description = {}
        for bom in present_lines.bom_id:
            if bom.type != "phantom":
                continue
            # In the BoM's own order, not the order the moves arrived in: read
            # alone, a move put its own line first and called itself 1 of 3.
            line_ids = [line.id for line in bom.bom_line_ids if line in present_lines]
            total = len(line_ids)
            for i, line_id in enumerate(line_ids):
                bom_line_description[line_id] = "%s - %d/%d" % (
                    bom.display_name,
                    i + 1,
                    total,
                )

        for move in self:
            description = bom_line_description.get(move.bom_line_id.id)
            if move.description_picking_manual or not description:
                continue
            if move.description_picking == move.product_id.display_name:
                move.description_picking = ""
            move.description_picking += (
                "\n" if move.description_picking else ""
            ) + description

    @api.depends("raw_material_production_id.priority")
    def _compute_priority(self):
        super()._compute_priority()
        for move in self:
            move.priority = (
                move.raw_material_production_id.priority or move.priority or "0"
            )

    @api.depends(
        "raw_material_production_id.picking_type_id", "production_id.picking_type_id"
    )
    def _compute_picking_type_id(self):
        super()._compute_picking_type_id()
        for move in self:
            production = move._get_production()
            if production:
                move.picking_type_id = production.picking_type_id

    @api.depends("raw_material_production_id.is_locked", "production_id.is_locked")
    def _compute_is_locked(self):
        super()._compute_is_locked()
        for move in self:
            production = move._get_production()
            if production:
                move.is_locked = production.is_locked

    @api.depends(
        "product_uom_qty",
        "raw_material_production_id",
        "raw_material_production_id.product_qty",
        "raw_material_production_id.qty_produced",
        "production_id",
        "production_id.product_qty",
        "production_id.qty_produced",
    )
    def _compute_unit_factor(self):
        for move in self:
            production = move._get_production()
            if production:
                move.unit_factor = move.product_uom_qty / (
                    (production.product_qty - production.qty_produced) or 1
                )
            else:
                move.unit_factor = 1.0

    @api.depends(
        "raw_material_production_id",
        "raw_material_production_id.name",
        "production_id",
        "production_id.name",
        "unbuild_id",
        "unbuild_id.name",
    )
    def _compute_reference(self):
        # Accumulating the handled moves with `|=` rebuilt the whole id tuple on
        # every iteration (`union` is `OrderedSet(self._ids + other._ids)`), which
        # is quadratic: 448 ms at 6400 moves against 1.1 ms for collecting ids and
        # browsing once.
        ids_to_super = []
        for move in self:
            source = move.unbuild_id or move._get_production()
            if source.name:
                move.reference = source.name
            else:
                ids_to_super.append(move.id)
        super(StockMove, self.browse(ids_to_super))._compute_reference()

    def _update_references(self):
        super()._update_references()
        for move in self:
            if move.reference_ids:
                continue
            production = move._get_production()
            if production:
                move.reference_ids = [Command.set(production.reference_ids.ids)]

    def _get_qty_to_process(self):
        """How much of this move the order still expects, for what it is producing.

        `should_consume_qty` is this answer for a component. `mrp.production.
        _inverse_qty_producing` needs the same answer for a by-product, which carries
        `production_id` instead, and `_onchange_product_uom_qty` needs it for the
        move being edited -- so all three wrote the formula out, with the same
        rounding, in three places. One copy means `unit_factor`'s dependencies only
        have to be right here.
        """
        self.ensure_one()
        production = self._get_production()
        if not production or not self.product_uom_id:
            return 0.0
        return self.product_uom_id.round(
            (production.qty_producing - production.qty_produced) * self.unit_factor
        )

    @api.depends(
        "raw_material_production_id.qty_producing",
        "raw_material_production_id.qty_produced",
        "unit_factor",
        "product_uom_id",
    )
    def _compute_should_consume_qty(self):
        # The formula reads `unit_factor` and `qty_produced`; neither used to be
        # declared, and the field is not stored, so a value cached before either
        # moved survived the transaction -- measured at 10.0 against a truth of
        # 3.33.
        for move in self:
            move.should_consume_qty = (
                move._get_qty_to_process() if move.raw_material_production_id else 0.0
            )

    @api.depends("byproduct_id", "production_id.move_finished_ids")
    def _compute_show_info(self):
        super()._compute_show_info()
        finished_moves = self.production_id.move_finished_ids
        byproduct_moves = self.filtered(lambda m: m.byproduct_id or m in finished_moves)
        byproduct_moves.show_quant = False
        byproduct_moves.show_lots_m2o = True

    @api.depends("picking_type_id.use_create_components_lots")
    def _compute_display_assign_serial(self):
        super()._compute_display_assign_serial()
        for move in self:
            if (
                move.display_import_lot
                and move.raw_material_production_id
                and not move.raw_material_production_id.picking_type_id.use_create_components_lots
            ):
                move.display_import_lot = False
                move.display_assign_serial = False

    @api.onchange("product_uom_qty", "product_uom_id")
    def _onchange_product_uom_qty(self):
        if (
            self.product_uom_id
            and self.raw_material_production_id
            and self.has_tracking == "none"
            and self.state not in ("draft", "cancel", "done")
        ):
            self.quantity = self._get_qty_to_process()

    @api.onchange("quantity", "product_uom_id", "picked")
    def _onchange_quantity(self):
        if (
            self.raw_material_production_id
            and self.product_uom_id
            and not float_is_zero(
                self.quantity, precision_rounding=self.product_uom_id.rounding
            )
            and self.product_uom_id.compare(self.product_uom_qty, self.quantity) != 0
        ):
            self.manual_consumption = True
            self.picked = True

    @api.constrains("quantity", "raw_material_production_id")
    def _check_negative_quantity(self):
        for move in self:
            if (
                move.raw_material_production_id
                and move.product_uom_id.compare(move.quantity, 0) < 0
            ):
                raise ValidationError(
                    _("A component cannot be consumed in a negative quantity.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("force_manual_consumption"):
            for vals in vals_list:
                if "quantity" in vals:
                    vals["manual_consumption"] = self._is_quantity_edited(
                        vals.get("product_uom_qty"),
                        vals["quantity"],
                        self.env["uom.uom"].browse(vals.get("product_uom_id")),
                    )
                vals["picked"] = True
        # Browsing each order on its own gave it a prefetch set of one, so the six
        # reads below cost one round trip per order: 183 queries against 105 for
        # forty orders in one call. One browse for all of them is constant.
        production_ids = OrderedSet()
        location_ids = OrderedSet()
        for values in vals_list:
            mo_id = values.get("raw_material_production_id") or values.get(
                "production_id"
            )
            if mo_id:
                production_ids.add(mo_id)
            if values.get("location_dest_id"):
                location_ids.add(values["location_dest_id"])
        productions_by_id = {
            mo.id: mo for mo in self.env["mrp.production"].browse(production_ids)
        }
        locations_by_id = {
            location.id: location
            for location in self.env["stock.location"].browse(location_ids)
        }
        no_location = self.env["stock.location"]
        for values in vals_list:
            mo_id = values.get("raw_material_production_id", False) or values.get(
                "production_id", False
            )
            location_dest = locations_by_id.get(
                values.get("location_dest_id"), no_location
            )
            if mo_id and location_dest.usage != "inventory":
                mo = productions_by_id[mo_id]
                values["origin"] = mo._get_origin()
                values["propagate_cancel"] = mo.propagate_cancel
                values["reference_ids"] = mo.reference_ids.ids
                values["production_group_id"] = mo.production_group_id.id
                if values.get("raw_material_production_id", False):
                    values["location_dest_id"] = mo.production_location_id.id
                    if not values.get("location_id"):
                        values["location_id"] = mo.location_src_id.id
                    if mo.state in ["progress", "to_close"] and mo.qty_producing > 0:
                        values["picked"] = True
                    continue
                values["location_id"] = mo.production_location_id.id
                values["date"] = mo.date_end
                values["date_deadline"] = mo.date_deadline
                if not values.get("location_dest_id"):
                    values["location_dest_id"] = mo.location_dest_id.id
                if not values.get("location_final_id"):
                    values["location_final_id"] = mo.warehouse_id.lot_stock_id.id
        return super().create(vals_list)

    @api.model
    def _is_quantity_edited(self, demand, quantity, uom):
        """Did the user record something other than what the order asked for?

        Comparing the two floats with `!=` answered yes for quantities that are the
        same to the unit's precision: seven UoM pairs in a stock database round-trip
        to a value one bit away from where they started -- `Units` through
        `Pack of 6` turns 3.6666666666666665 into 3.666666666666666, and a component
        recorded at exactly its demand was filed as manually consumed. With no
        demand to compare against there is nothing to match, so it is an edit.
        """
        if not uom or demand is None:
            return True
        return uom.compare(demand, quantity) != 0

    def write(self, vals):
        moves_to_rereserve = self.env["stock.move"]
        if "product_id" in vals:
            # Changing the product of a live output move has to reach its move
            # lines, which still hold the old product. This used to copy the move,
            # confirm the copy and `unlink()` the original -- inside `write`, which
            # left every caller up the MRO holding a deleted id: with `sale_stock`
            # installed its own `write` iterates `self` right after `super()` and
            # died with MissingError. Releasing the reservation and writing the
            # product in place reaches the same move lines and keeps the record the
            # caller was given.
            moves_to_rereserve = self.filtered(
                lambda m: (
                    m.product_id.id != vals.get("product_id")
                    and m.production_id
                    and m.state not in ("draft", "cancel", "done")
                )
            )
            moves_to_rereserve._do_unreserve()
        moves_to_update = False
        if self.env.context.get("force_manual_consumption") and "quantity" in vals:
            moves_to_update = self.filtered(
                lambda move: move._is_quantity_edited(
                    move.product_uom_qty, vals["quantity"], move.product_uom_id
                )
            )
        if "product_uom_qty" in vals and "move_line_ids" in vals:
            move_line_vals = vals.pop("move_line_ids")
            super().write({"move_line_ids": move_line_vals})
        # Only `_run_procurement` reads this, and only for a demand change.
        old_demand = (
            {move.id: move.product_uom_qty for move in self}
            if "product_uom_qty" in vals
            else {}
        )
        res = super().write(vals)
        if moves_to_rereserve:
            moves_to_rereserve._action_assign()
        if moves_to_update:
            moves_to_update.write({"manual_consumption": True, "picked": True})
        if "product_uom_qty" in vals and not self.env.context.get(
            "no_procurement", False
        ):
            self.filtered(
                lambda m: (
                    m.raw_material_production_id.state
                    in ("confirmed", "progress", "to_close")
                )
            )._run_procurement(old_demand)
        return res

    def _run_procurement(self, old_qties=False):
        procurements = []
        old_qties = old_qties or {}
        # `set` here handed `browse` its own iteration order rather than `self`'s,
        # so the procurements were built in an order the caller never chose. The
        # file already imports `OrderedSet` and uses it in `action_explode`.
        to_assign_ids = OrderedSet()
        proc_move = OrderedSet()
        self._adjust_procure_method()
        for move in self:
            if (
                move.product_uom_id.compare(
                    move.product_uom_qty - old_qties.get(move.id, 0), 0
                )
                < 0
                and move.procure_method == "make_to_order"
                and move.move_orig_ids
                and all(m.state == "done" for m in move.move_orig_ids)
            ):
                continue
            if move.product_uom_id.compare(move.product_uom_qty, 0) > 0:
                if move._should_assign_at_confirm():
                    to_assign_ids.add(move.id)
            proc_move.add(move.id)

        to_assign = self.browse(to_assign_ids)
        before_assign_qties = {move.id: move.quantity for move in to_assign}
        to_assign._action_assign()
        delta_qties = {
            move.id: (
                move.quantity - before_assign_qties.get(move.id, 0)
                if move.product_id.is_storable
                else 0
            )
            for move in to_assign
        }

        proc_move = self.browse(proc_move)
        for move in proc_move:
            if (
                move.procure_method == "make_to_order"
                or move.rule_id.procure_method == "mts_else_mto"
            ):
                procurement_qty = (
                    move.product_uom_qty
                    - old_qties.get(move.id, 0)
                    - delta_qties.get(move.id, 0)
                )
                if move.move_orig_ids:
                    possible_reduceable_qty = -sum(
                        move.move_orig_ids.filtered(
                            lambda m: (
                                m.state not in ("done", "cancel") and m.product_uom_qty
                            )
                        ).mapped("product_uom_qty")
                    )
                    procurement_qty = max(procurement_qty, possible_reduceable_qty)
                values = move._prepare_procurement_vals()
                procurements.append(
                    self.env["stock.rule"].Procurement(
                        move.product_id,
                        procurement_qty,
                        move.product_uom_id,
                        move.location_id,
                        move.reference,
                        move.origin,
                        move.company_id,
                        values,
                    )
                )

        if procurements:
            self.env["stock.rule"].run(procurements)

    def _action_assign(self, force_qty=False):
        res = super()._action_assign(force_qty=force_qty)
        # Only a component's lines carry an order and a work order. The filter used
        # to admit output moves too and then wrote `raw_material_production_id.id`,
        # which is empty for them -- selecting records in order to store two falsy
        # values. Grouping by what is written turns one write per move into one per
        # (order, work order) pair.
        lines_by_owner = defaultdict(list)
        for move in self.filtered("raw_material_production_id"):
            if move.move_line_ids:
                key = (move.raw_material_production_id.id, move.workorder_id.id)
                lines_by_owner[key].extend(move.move_line_ids.ids)
        move_lines = self.env["stock.move.line"]
        for (production_id, workorder_id), line_ids in lines_by_owner.items():
            move_lines.browse(line_ids).write(
                {"production_id": production_id, "workorder_id": workorder_id}
            )
        return res

    def _action_confirm(self, merge=True, merge_into=False, create_proc=True):
        moves = self.action_explode()
        merge_into = merge_into and merge_into.action_explode()
        return super(StockMove, moves)._action_confirm(
            merge=merge, merge_into=merge_into, create_proc=create_proc
        )

    def _action_done(self, cancel_backorder=False):
        moves_to_explode = self.filtered(
            lambda m: m.product_id.is_kit and m.state not in ("cancel", "done")
        )
        exploded_moves = moves_to_explode.action_explode()
        moves = (self - moves_to_explode) | exploded_moves
        return super(StockMove, moves)._action_done(cancel_backorder)

    def _should_bypass_reservation(self, forced_location=False):
        return (
            super()._should_bypass_reservation(forced_location)
            or self.product_id.with_company(self.company_id).is_kit
        )

    def _is_explodable(self):
        """May this move be replaced by the components of its kit?

        A move with no operation type is on no document that could carry the
        components -- unless it is a scrap, or the caller has said it will place
        them itself. And an order's own output is what that order produces; it is
        never a kit to take apart here.
        """
        self.ensure_one()
        if not self.picking_type_id and not (
            self.env.context.get("is_scrap")
            or self.env.context.get("skip_picking_assignation")
        ):
            return False
        return not (
            self.production_id and self.production_id.product_id == self.product_id
        )

    def _get_kit_boms(self):
        """The kit BoM of every move here, keyed by product.

        `_bom_find` takes a recordset and returns a dict -- it is built to be asked
        once. Asked once per move it cost three calls and about five queries per
        kit; hoisting it took `action_confirm` over forty kit moves from 503
        queries to 269, with the resulting moves byte-identical. `stock.rule.run`
        already groups by company this way for the other half of kit explosion.
        """
        boms = {}
        moves_by_company = defaultdict(list)
        for move in self:
            moves_by_company[move.company_id].append(move.id)
        for company, move_ids in moves_by_company.items():
            boms.update(
                self.env["mrp.bom"]
                .sudo()
                ._bom_find(
                    self.browse(move_ids).product_id,
                    company_id=company.id,
                    bom_type="phantom",
                )
            )
        return boms

    def action_explode(self):
        moves_ids_to_return = OrderedSet()
        moves_ids_to_unlink = OrderedSet()
        phantom_moves_vals_list = []
        # One explosion scratch for the batch, and for the recursion below, which
        # inherits it through `self.env`: `_explode` is asked once per *move*, and
        # forty moves of the same kit resolved that kit's closure forty times.
        self = self.with_context(
            bom_cost_share_cache=self.env["mrp.bom"]._explosion_scratch()
        )
        explodable = self.filtered(lambda move: move._is_explodable())
        kit_boms = explodable._get_kit_boms()
        for move in self:
            bom = kit_boms.get(move.product_id) if move in explodable else None
            if not bom:
                moves_ids_to_return.add(move.id)
                continue
            quantity = (
                move.quantity
                if move.product_uom_id.is_zero(move.product_uom_qty)
                else move.product_uom_qty
            )
            factor = (
                move.product_uom_id._compute_quantity(quantity, bom.product_uom_id)
                / bom.product_qty
            )
            _dummy, lines = bom.sudo()._explode(
                move.product_id,
                factor,
                picking_type=bom.picking_type_id,
                never_attribute_values=move.never_product_template_attribute_value_ids,
            )
            phantom_moves_vals_list += move._prepare_phantom_moves_vals(lines)
            moves_ids_to_unlink.add(move.id)

        if phantom_moves_vals_list:
            phantom_moves = self.env["stock.move"].create(phantom_moves_vals_list)
            phantom_moves._adjust_procure_method()
            moves_ids_to_return |= phantom_moves.action_explode().ids
        move_to_unlink = self.env["stock.move"].browse(moves_ids_to_unlink).sudo()
        move_to_unlink.quantity = 0
        move_to_unlink._action_cancel()
        move_to_unlink.unlink()
        return self.env["stock.move"].browse(moves_ids_to_return)

    def action_show_details(self):
        self.ensure_one()
        action = super().action_show_details()
        if self.raw_material_production_id:
            action["name"] = _("Components")
            action["views"] = [
                (self.env.ref("mrp.view_stock_move_form_operations_raw").id, "form")
            ]
            action["context"]["show_destination_location"] = False
            action["context"]["force_manual_consumption"] = True
            action["context"]["active_mo_id"] = self.raw_material_production_id.id
        elif self.production_id:
            action["name"] = _("Move Byproduct")
            action["views"] = [
                (
                    self.env.ref("mrp.view_stock_move_form_operations_finished").id,
                    "form",
                )
            ]
            action["context"]["show_source_location"] = False
            action["context"]["show_reserved_quantity"] = False
        return action

    def _action_add_from_catalog(self, child_field):
        """Open the product catalog against one of the order's move lists.

        The two buttons below differ only in which list they fill; the order they
        fill it on is the same lookup either way.
        """
        production = self.env["mrp.production"].browse(self.env.context.get("order_id"))
        return production.with_context(
            child_field=child_field
        ).action_add_from_catalog()

    def action_add_from_catalog_raw(self):
        return self._action_add_from_catalog("move_raw_ids")

    def action_add_from_catalog_byproduct(self):
        return self._action_add_from_catalog("move_byproduct_ids")

    def _action_cancel(self):
        res = super()._action_cancel()
        if not self.env.context.get("skip_mo_check"):
            mo_to_cancel = self.mapped("raw_material_production_id").filtered(
                lambda p: all(m.state == "cancel" for m in p.move_raw_ids)
            )
            if mo_to_cancel:
                mo_to_cancel._action_cancel()
        return res

    def _log_cancel_activity(self):
        super()._log_cancel_activity()
        if not self:
            return None

        def _render_note_exception_cancel_dest(moves):
            values = {
                "origin_moves": moves,
                "origin_picking": moves.picking_id[:1],
                "moves_information": (
                    (move, (0.0, move.product_qty)) for move in moves
                ),
            }
            return self.env["ir.qweb"]._render("stock.exception_on_picking", values)

        cancelled_ids = set(self.ids)
        impacted_origins = self.move_orig_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
        documents = {}
        for move in impacted_origins:
            production = move.production_id
            if not production:
                continue
            cancelled_dests = move.move_dest_ids.filtered(
                lambda m: m.id in cancelled_ids
            )
            if not cancelled_dests.picking_id:
                continue
            # Two output moves of one order reach the same key, and plain
            # assignment let the second drop the first's cancellations from the
            # note. `_log_activity_get_documents`, which this stands in for,
            # accumulates.
            key = (production, production.user_id or self.env.user)
            documents[key] = documents.get(key, self.browse()) | cancelled_dests
        return self.env["mixin.stock.activity"]._log_activity(
            _render_note_exception_cancel_dest, documents
        )

    def _prepare_move_split_vals(self, qty, force_uom_id=False):
        defaults = super()._prepare_move_split_vals(qty, force_uom_id=force_uom_id)
        defaults["workorder_id"] = False
        return defaults

    def _prepare_procurement_origin(self):
        self.ensure_one()
        if (
            self.raw_material_production_id
            and self.raw_material_production_id.orderpoint_id
        ):
            return self.origin
        return super()._prepare_procurement_origin()

    def _prepare_phantom_move_vals(self, bom_line, product_qty, quantity_done):
        self.ensure_one()
        return {
            "picking_id": self.picking_id.id if self.picking_id else False,
            "product_id": bom_line.product_id.id,
            "product_uom_id": bom_line.product_uom_id.id,
            "product_uom_qty": product_qty,
            "quantity": quantity_done,
            "picked": self.picked,
            "bom_line_id": bom_line.id,
            "description_picking": self.product_id.display_name,
        }

    def _prepare_phantom_moves_vals(self, exploded_lines_data):
        """Move vals for every component this kit move explodes into.

        This was three methods deep -- one looping the lines, one wrapping
        `copy_data`, one building the defaults -- with the middle returning a list
        `copy_data` guarantees is one element long, so its caller looped over it to
        set a single key.
        """
        self.ensure_one()
        record_what_was_done = self.product_uom_id.is_zero(
            self.product_uom_qty
        ) or self.env.context.get("is_scrap")
        vals_list = []
        for bom_line, line_data in exploded_lines_data:
            if bom_line.product_id.type != "consu":
                continue
            if record_what_was_done:
                product_qty, quantity_done = 0, line_data["qty"]
            else:
                product_qty, quantity_done = line_data["qty"], 0
            vals = self.copy_data(
                default=self._prepare_phantom_move_vals(
                    bom_line, product_qty, quantity_done
                )
            )
            for val in vals:
                val["cost_share"] = line_data.get("line_cost_share", 0.0)
                if self.state == "assigned":
                    val["state"] = "assigned"
            vals_list += vals
        return vals_list

    def _is_consuming(self):
        return super()._is_consuming() or self.picking_type_id.code == "mrp_operation"

    def _get_backorder_move_vals(self):
        self.ensure_one()
        return {
            "state": "draft" if self.state == "draft" else "confirmed",
            "date_reservation": self.date_reservation,
            "date_deadline": self.date_deadline,
            "manual_consumption": self._is_manual_consumption(),
            "move_orig_ids": [Command.link(m.id) for m in self.mapped("move_orig_ids")],
            "move_dest_ids": [Command.link(m.id) for m in self.mapped("move_dest_ids")],
            "procure_method": self.procure_method,
        }

    def _get_source_document(self):
        res = super()._get_source_document()
        return res or self._get_production()

    def _get_upstream_documents_and_responsibles(self, visited):
        if self.production_id and self.production_id.state not in ("done", "cancel"):
            return [
                (
                    self.production_id,
                    self.production_id.user_id or self.env.user,
                    visited,
                )
            ]
        else:
            return super()._get_upstream_documents_and_responsibles(visited)

    def _delay_alert_get_documents(self):
        res = super()._delay_alert_get_documents()
        productions = self.raw_material_production_id | self.production_id
        return res + list(productions)

    def _should_be_assigned(self):
        res = super()._should_be_assigned()
        return bool(res and not self._get_production())

    def _should_bypass_set_qty_producing(self):
        if self.state in ("done", "cancel"):
            return True
        return self.product_uom_id.is_zero(self.product_uom_qty)

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(quantity, reserved_quant)
        if self.raw_material_production_id:
            vals["production_id"] = self.raw_material_production_id.id
        if (
            self.production_id.product_tracking == "lot"
            and self.product_id == self.production_id.product_id
            and self.production_id.lot_producing_ids
        ):
            vals["lot_id"] = self.production_id.lot_producing_ids.ids[0]
        return vals

    def _key_assign_picking(self):
        keys = super()._key_assign_picking()
        return keys + (self.created_production_id,)

    def _prepare_merge_moves_distinct_fields(self):
        res = super()._prepare_merge_moves_distinct_fields()
        res += ["created_production_id", "cost_share", "production_group_id"]
        if self.bom_line_id and ("phantom" in self.bom_line_id.bom_id.mapped("type")):
            res.append("bom_line_id")
        return res

    def _prepare_merge_negative_moves_excluded_distinct_fields(self):
        return super()._prepare_merge_negative_moves_excluded_distinct_fields() + [
            "created_production_id"
        ]

    def _get_kit_quantity(self, product_id, kit_qty, kit_bom, filters):
        qty_ratios = []
        kit_qty /= kit_bom.product_qty
        _boms, bom_sub_lines = kit_bom._explode(product_id, kit_qty)

        def get_qty(move):
            if move.picked:
                return move.product_uom_id._compute_quantity(
                    move.quantity, move.product_id.uom_id, rounding_method="HALF-UP"
                )
            else:
                return move.product_qty

        for bom_line, bom_line_data in bom_sub_lines:
            if bom_line.product_id.type == "service":
                continue
            if bom_line.product_uom_id.is_zero(bom_line_data["qty"]):
                continue
            bom_line_moves = self.filtered(
                lambda m, bom_line=bom_line: m.bom_line_id == bom_line
            )
            if bom_line_moves:
                uom_qty_per_kit = bom_line_data["qty"] / (bom_line_data["original_qty"])
                qty_per_kit = bom_line.product_uom_id._compute_quantity(
                    uom_qty_per_kit / kit_bom.product_qty,
                    bom_line.product_id.uom_id,
                    round=False,
                )
                if not qty_per_kit:
                    continue
                incoming_moves = bom_line_moves.filtered(filters["incoming_moves"])
                final_incoming_moves = incoming_moves - incoming_moves.move_orig_ids
                qty_incoming = sum(final_incoming_moves.mapped(get_qty))
                outgoing_moves = bom_line_moves.filtered(filters["outgoing_moves"])
                final_outgoing_moves = outgoing_moves - outgoing_moves.move_orig_ids
                qty_outgoing = sum(final_outgoing_moves.mapped(get_qty))
                qty_processed = qty_incoming - qty_outgoing
                qty_ratios.append(
                    bom_line.product_id.uom_id.round(qty_processed / qty_per_kit)
                )
            else:
                return 0.0
        if qty_ratios:
            return min(qty_ratios) // 1
        else:
            return 0.0

    def _update_candidate_moves_list(self, candidate_moves_set):
        super()._update_candidate_moves_list(candidate_moves_set)
        # `self.product_id` inside the lambda was re-mapped once per candidate.
        products = self.product_id
        for production in self.raw_material_production_id:
            candidate_moves_set.add(
                production.move_raw_ids.filtered(lambda m: m.product_id in products)
            )
        for production in self.production_id:
            candidate_moves_set.add(
                production.move_finished_ids.filtered(
                    lambda m: m.product_id in products
                )
            )
        for picking in self.move_dest_ids.raw_material_production_id.picking_ids:
            candidate_moves_set.add(picking.move_ids)

    def _prepare_procurement_vals(self):
        res = super()._prepare_procurement_vals()
        res["production_group_id"] = self.production_group_id.id
        res["bom_line_id"] = self.bom_line_id.id
        return res

    def _search_picking_for_assignation_domain(self):
        domain = super()._search_picking_for_assignation_domain()
        domain += self._get_production_assignation_domain()
        return domain

    def _get_production_assignation_domain(self):
        return [("move_ids.production_group_id", "=", self.production_group_id.id)]

    def action_view_reference(self):
        res = super().action_view_reference()
        source = self._get_production()
        if source and source.browse().has_access("read"):
            return {
                "res_model": source._name,
                "type": "ir.actions.act_window",
                "views": [[False, "form"]],
                "res_id": source.id,
            }
        return res

    def _is_manual_consumption(self):
        self.ensure_one()
        return self._determine_is_manual_consumption(self.bom_line_id)

    @api.model
    def _determine_is_manual_consumption(self, bom_line):
        return bool(bom_line and bom_line.operation_id)

    def _is_consumption_covered(self):
        """Is enough of this component on hand for what the order is producing?"""
        self.ensure_one()
        uom = self.product_uom_id
        if (
            self.should_consume_qty
            and uom.compare(self.quantity, self.should_consume_qty) >= 0
        ):
            return True
        return uom.compare(self.quantity, self.product_uom_qty) >= 0 or (
            self.manual_consumption and self.picked
        )

    def _get_relevant_state_among_moves(self):
        res = super()._get_relevant_state_among_moves()
        if res != "partially_available":
            return res
        # `super()` decided from the moves that are still live. Judging the lift
        # over `self` instead let a *cancelled* component -- which requires nothing
        # and which `super()` had already set aside -- veto it: two orders whose
        # remaining component was reserved identically read Ready and Not Ready
        # depending only on whether a sibling had been cancelled or deleted.
        moves = self.filtered(lambda m: m.state not in ("cancel", "done"))
        if moves.raw_material_production_id and all(
            move._is_consumption_covered() for move in moves
        ):
            res = "assigned"
        return res
