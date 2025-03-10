from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools import float_compare
from odoo.tools.translate import _


class SaleOrderLine(models.Model):
    "Inherit SaleOrderLine"

    _inherit = "sale.order.line"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    is_storable = fields.Boolean(related="product_id.is_storable")
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        compute="_compute_warehouse_id",
        store=True,
    )
    customer_lead = fields.Float(
        compute="_compute_customer_lead",
        store=True,
        precompute=True,
        readonly=False,
        inverse="_inverse_customer_lead",
    )
    route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Route",
        domain=[("sale_selectable", "=", True)],
        ondelete="restrict",
    )
    move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="sale_line_id",
        string="Stock Moves",
        readonly=True,
        copy=False,
    )
    date_planned = fields.Datetime(
        compute="_compute_qty_at_date",
    )
    date_planned_forecast = fields.Datetime(
        compute="_compute_qty_at_date",
    )
    qty_available_today = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_at_date",
    )
    qty_available_virtual_at_date = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_at_date",
    )
    qty_free_today = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_at_date",
    )
    qty_to_transfer = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_transfered",
        store=True,
    )
    display_qty_widget = fields.Boolean(
        compute="_compute_display_qty_widget",
    )
    is_mto = fields.Boolean(
        compute="_compute_is_mto",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def write(self, vals):
        self._check_write_product_uom_qty(vals)
        return super().write(vals)

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("order_id.warehouse_id", "product_id", "route_id")
    def _compute_warehouse_id(self):
        for line in self:
            if line.route_id:
                domain = [
                    (
                        "location_dest_id",
                        "=",
                        line.order_id.partner_shipping_id.property_stock_customer.id,
                    ),
                    ("action", "!=", "push"),
                ]
                # prefer rules on the route itself even if they pull from a different warehouse than the SO's
                rules = sorted(
                    self.env["stock.rule"].search(
                        domain=expression.AND(
                            [[("route_id", "=", line.route_id.id)], domain]
                        ),
                        order="route_sequence, sequence",
                    ),
                    # if there are multiple rules on the route, prefer those that pull from the SO's warehouse
                    # or those that are not warehouse specific
                    key=lambda rule: (
                        0
                        if rule.location_src_id.warehouse_id
                        in (False, line.order_id.warehouse_id)
                        else 1
                    ),
                )
                if rules:
                    line.warehouse_id = rules[0].location_src_id.warehouse_id
            # Moved this condition to the else block to avoid unnecessary
            # computation of warehouse_id when route_id is set. lmmg
            else:
                line.warehouse_id = line.order_id.warehouse_id

    @api.depends("product_id")
    def _compute_customer_lead(self):
        super()._compute_customer_lead()  # Reset customer_lead when the product is modified
        for line in self:
            line.customer_lead = line.product_id.sale_delay

    @api.depends("product_id", "product_id.route_ids", "route_id", "warehouse_id")
    def _compute_is_mto(self):
        """Verify the route of the product based on the warehouse
        set 'is_available' at True if the product availability in stock does
        not need to be verified, which is the case in MTO, Drop-Shipping"""
        self.is_mto = False
        for line in self:
            if not line.display_qty_widget:
                continue

            product = line.product_id
            product_routes = line.route_id or (
                product.route_ids + product.categ_id.total_route_ids
            )

            # Check MTO
            mto_route = line.warehouse_id.mto_pull_id.route_id
            if not mto_route:
                try:
                    mto_route = self.env[
                        "stock.warehouse"
                    ]._find_or_create_global_route(
                        "stock.route_warehouse0_mto",
                        _("Replenish on Order (MTO)"),
                        create=False,
                    )
                except UserError:
                    # if route MTO not found in ir_model_data, we treat the product as in MTS
                    pass

            if mto_route and mto_route in product_routes:
                line.is_mto = True
            else:
                line.is_mto = False

    @api.depends("move_ids")
    def _compute_product_updatable(self):
        super()._compute_product_updatable()
        for line in self:
            if line.move_ids.filtered(lambda m: m.state != "cancel"):
                line.product_updatable = False

    @api.depends(
        "product_uom_qty",
        "move_ids.state",
        "move_ids.product_uom",
        "move_ids.quantity",
        "move_ids.scrapped",
    )
    def _compute_qty_transfered(self):
        lines_by_stock_move = self.filtered(
            lambda line: line.qty_transfered_method == "stock_move"
        )
        super(SaleOrderLine, self - lines_by_stock_move)._compute_qty_transfered()
        for line in lines_by_stock_move:
            vals = {
                "qty_transfered": 0.0,
                "qty_to_transfer": 0.0,
            }

            if line.state != "sale":
                line.write(vals)
                continue

            vals["qty_to_transfer"] = line.product_uom_qty

            if not line.move_ids:
                line.write(vals)
                continue

            outgoing_moves, incoming_moves = line._get_outgoing_incoming_moves()
            for move in outgoing_moves:
                if move.state != "done":
                    continue

                vals["qty_transfered"] += move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id, rounding_method="HALF-UP"
                )
            for move in incoming_moves:
                if move.state != "done":
                    continue

                vals["qty_transfered"] -= move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id, rounding_method="HALF-UP"
                )

            vals["qty_to_transfer"] = max(
                0, vals["qty_to_transfer"] - vals["qty_transfered"]
            )
            line.write(vals)

    @api.depends(
        "state",
        "product_id",
        "is_storable",
        "product_uom_id",
        "product_uom_qty",
        "move_ids",
        "qty_to_transfer",
    )
    def _compute_display_qty_widget(self):
        """Compute the visibility of the inventory widget."""
        for line in self:
            if (
                line.state in ("draft", "sale")
                and line.is_storable
                and line.product_uom_id
                and line.qty_to_transfer > 0
            ):
                if line.state == "sale" and not line.move_ids:
                    line.display_qty_widget = False
                else:
                    line.display_qty_widget = True
            else:
                line.display_qty_widget = False

    @api.depends(
        "order_id.date_commitment",
        "product_id",
        "product_uom_id",
        "product_uom_qty",
        "customer_lead",
        "warehouse_id",
        "move_ids",
        "move_ids.forecast_date_planned",
        "move_ids.forecast_availability",
    )
    def _compute_qty_at_date(self):
        """Compute the quantity forecasted of product at delivery date. There are
        two cases:
         1. The quotation has a commitment_date, we take it as delivery date
         2. The quotation hasn't commitment_date, we compute the estimated delivery
            date based on lead time"""
        treated = self.browse()
        all_move_ids = {
            move.id
            for line in self
            if line.state == "sale"
            for move in line.move_ids
            | self.env["stock.move"].browse(line.move_ids._rollup_move_origs())
            if move.product_id == line.product_id
        }
        all_moves = self.env["stock.move"].browse(all_move_ids)
        date_planned_forecast_per_move = dict(
            all_moves.mapped(lambda m: (m.id, m.forecast_date_planned))
        )
        # If the state is already in sale the picking is created and a simple forecasted quantity isn't enough
        # Then use the forecasted data of the related stock.move
        for line in self.filtered(lambda l: l.state == "sale"):
            if not line.display_qty_widget:
                continue

            moves = line.move_ids | self.env["stock.move"].browse(
                line.move_ids._rollup_move_origs()
            )
            moves = moves.filtered(
                lambda m: m.product_id == line.product_id
                and m.state not in ("cancel", "done")
            )
            line.date_planned_forecast = max(
                (
                    date_planned_forecast_per_move[move.id]
                    for move in moves
                    if date_planned_forecast_per_move[move.id]
                ),
                default=False,
            )
            line.qty_available_today = 0
            line.qty_free_today = 0
            for move in moves:
                line.qty_available_today += move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id
                )
                line.qty_free_today += move.product_id.uom_id._compute_quantity(
                    move.forecast_availability, line.product_uom_id
                )
            line.date_planned = (
                line.order_id.date_commitment or line._get_date_planned()
            )
            line.qty_available_virtual_at_date = False
            treated |= line

        qty_processed_per_product = defaultdict(lambda: 0)
        grouped_lines = defaultdict(lambda: self.env["sale.order.line"])
        # We first loop over the SO lines to group them by warehouse and schedule
        # date in order to batch the read of the quantities computed field.
        for line in self.filtered(lambda l: l.state in ("draft", "sent")):
            if not (line.product_id and line.display_qty_widget):
                continue

            grouped_lines[
                (
                    line.warehouse_id.id,
                    line.order_id.date_commitment or line._get_date_planned(),
                )
            ] |= line

        for (warehouse, date_planned), lines in grouped_lines.items():
            product_qties = (
                lines.mapped("product_id")
                .with_context(to_date=date_planned, warehouse_id=warehouse)
                .read(
                    [
                        "qty_available",
                        "free_qty",
                        "virtual_available",
                    ]
                )
            )
            qties_per_product = {
                product["id"]: (
                    product["qty_available"],
                    product["free_qty"],
                    product["virtual_available"],
                )
                for product in product_qties
            }
            for line in lines:
                line.date_planned = date_planned
                qty_available_today, qty_free_today, qty_available_virtual_at_date = (
                    qties_per_product[line.product_id.id]
                )
                line.qty_available_today = (
                    qty_available_today - qty_processed_per_product[line.product_id.id]
                )
                line.qty_free_today = (
                    qty_free_today - qty_processed_per_product[line.product_id.id]
                )
                line.qty_available_virtual_at_date = (
                    qty_available_virtual_at_date
                    - qty_processed_per_product[line.product_id.id]
                )
                line.date_planned_forecast = False
                product_qty = line.product_uom_qty
                if (
                    line.product_uom_id
                    and line.product_id.uom_id
                    and line.product_uom_id != line.product_id.uom_id
                ):
                    line.qty_available_today = line.product_id.uom_id._compute_quantity(
                        line.qty_available_today, line.product_uom_id
                    )
                    line.qty_free_today = line.product_id.uom_id._compute_quantity(
                        line.qty_free_today, line.product_uom_id
                    )
                    line.qty_available_virtual_at_date = (
                        line.product_id.uom_id._compute_quantity(
                            line.qty_available_virtual_at_date, line.product_uom_id
                        )
                    )
                    product_qty = line.product_uom_id._compute_quantity(
                        product_qty, line.product_id.uom_id
                    )
                qty_processed_per_product[line.product_id.id] += product_qty
            treated |= lines
        remaining = self - treated
        remaining.qty_available_virtual_at_date = False
        remaining.date_planned = False
        remaining.date_planned_forecast = False
        remaining.qty_free_today = False
        remaining.qty_available_today = False

    # -------------------------------------------------------------------------
    # INVERSE METHODS
    # -------------------------------------------------------------------------

    def _inverse_customer_lead(self):
        for line in self:
            if line.state == "sale" and not line.order_id.date_commitment:
                # Propagate deadline on related stock move
                line.move_ids.date_deadline = line.order_id.date_order + timedelta(
                    days=line.customer_lead or 0.0
                )

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _action_launch_stock_rule(self, **kwargs):
        """Launch procurement group run method with required/custom fields generated
        by a sale order line. procurement group will launch '_run_pull', '_run_buy'
        or '_run_manufacture' depending on the sale order line product rule."""
        if self._context.get("skip_procurement"):
            return True

        precision = self.env["decimal.precision"].precision_get("Product Unit")
        procurements = []
        for line in self:
            line = line.with_company(line.company_id)
            if line.state != "sale" or line.locked or line.product_id.type != "consu":
                continue

            previous_vals = kwargs.get("previous_vals") or False
            previous_product_uom_qty = (
                previous_vals[line.id].get("product_uom_qty", False)
                if previous_vals
                else False
            )
            qty = line._get_procurement_qty(previous_product_uom_qty)
            if (
                float_compare(qty, line.product_uom_qty, precision_digits=precision)
                == 0
            ):
                continue

            group_id = line._get_procurement_group()
            if not group_id:
                group_id = self.env["procurement.group"].create(
                    line._prepare_procurement_group_vals()
                )
                line.order_id.procurement_group_id = group_id
            else:
                # In case the procurement group is already created and the order was
                # cancelled, we need to update certain values of the group.
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update(
                        {"partner_id": line.order_id.partner_shipping_id.id}
                    )
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({"move_type": line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)

            procurement_vals = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty
            line_uom = line.product_uom_id
            quant_uom = line.product_id.uom_id
            origin = (
                f"{line.order_id.name} - {line.order_id.client_order_ref}"
                if line.order_id.client_order_ref
                else line.order_id.name
            )
            product_qty, procurement_uom = line_uom._adjust_uom_quantities(
                product_qty, quant_uom
            )
            procurements += line._create_procurements(
                product_qty, procurement_uom, origin, procurement_vals
            )

        if procurements:
            self.env["procurement.group"].run(procurements)

        # This next block is currently needed only because the scheduler trigger
        # is done by picking confirmation rather than stock.move confirmation
        orders = self.mapped("order_id")
        for order in orders:
            pickings_to_confirm = order.picking_ids.filtered(
                lambda p: p.state not in ["cancel", "done"]
            )
            if pickings_to_confirm:
                # Trigger the Scheduler for Pickings
                pickings_to_confirm.action_confirm()
        return True

    def _create_procurements(self, product_qty, procurement_uom, origin, values):
        self.ensure_one()
        return [
            self.env["procurement.group"].Procurement(
                self.product_id,
                product_qty,
                procurement_uom,
                self._get_location_final(),
                self.product_id.display_name,
                origin,
                self.order_id.company_id,
                values,
            )
        ]

    def _hook_on_created_confirmed_lines(self):
        super()._hook_on_created_confirmed_lines()
        for line in self:
            line._action_launch_stock_rule()

    def _hook_on_written_confirmed_lines(self, write_vals, previous_vals):
        super()._hook_on_written_confirmed_lines(write_vals, previous_vals)
        if "product_uom_qty" in write_vals:
            self._action_launch_stock_rule(previous_vals=previous_vals)

    def _get_location_final(self):
        # Can be overriden for inter-company transactions.
        self.ensure_one()
        return self.order_id.partner_shipping_id.property_stock_customer

    def _get_outgoing_incoming_moves(self, strict=True):
        """Return the outgoing and incoming moves of the sale order line.
        @param strict:
        If True, only consider the moves that are strictly delivered to the customer (old behavior).
        If False, consider the moves that were created through the initial rule
        of the delivery route, to support the new push mechanism."""
        outgoing_moves_ids = set()
        incoming_moves_ids = set()
        moves = self.move_ids.filtered(
            lambda m: m.state != "cancel"
            and not m.scrapped
            and self.product_id == m.product_id
        )

        if moves and not strict:
            # The first move created was the one created from the intial rule that started it all.
            sorted_moves = moves.sorted("id")
            triggering_rule_ids = []
            seen_wh_ids = set()
            for move in sorted_moves:
                if move.warehouse_id.id not in seen_wh_ids:
                    triggering_rule_ids.append(move.rule_id.id)
                    seen_wh_ids.add(move.warehouse_id.id)

        if self._context.get("accrual_entry_date"):
            moves = moves.filtered(
                lambda r: fields.Date.context_today(r, r.date)
                <= self._context["accrual_entry_date"]
            )

        for move in moves:
            if (strict and move.location_dest_id._is_outgoing()) or (
                not strict
                and move.rule_id.id in triggering_rule_ids
                and (move.location_final_id or move.location_dest_id)._is_outgoing()
            ):
                if not move.origin_returned_move_id or (
                    move.origin_returned_move_id and move.to_refund
                ):
                    outgoing_moves_ids.add(move.id)
            elif move.location_id._is_outgoing() and move.to_refund:
                incoming_moves_ids.add(move.id)

        return (
            self.env["stock.move"].browse(outgoing_moves_ids),
            self.env["stock.move"].browse(incoming_moves_ids),
        )

    def _get_procurement_group(self):
        return self.order_id.procurement_group_id

    def _get_procurement_qty(self, previous_product_uom_qty=False):
        self.ensure_one()
        qty = 0.0
        outgoing_moves, incoming_moves = self._get_outgoing_incoming_moves(strict=False)
        for move in outgoing_moves:
            qty_to_compute = (
                move.quantity if move.state == "done" else move.product_uom_qty
            )
            qty += move.product_uom._compute_quantity(
                qty_to_compute, self.product_uom_id, rounding_method="HALF-UP"
            )
        for move in incoming_moves:
            qty_to_compute = (
                move.quantity if move.state == "done" else move.product_uom_qty
            )
            qty -= move.product_uom._compute_quantity(
                qty_to_compute, self.product_uom_id, rounding_method="HALF-UP"
            )
        return qty

    def _prepare_procurement_group_vals(self):
        return {
            "name": self.order_id.name,
            "move_type": self.order_id.picking_policy,
            "sale_id": self.order_id.id,
            "partner_id": self.order_id.partner_shipping_id.id,
        }

    def _prepare_procurement_values(self, group_id=False):
        """Prepare specific key for moves or other components that will be created
        from a stock rule coming from a sale order line. This method could be override
        in order to add other custom key that could be used in move/po creation."""
        values = super()._prepare_procurement_values(group_id)
        self.ensure_one()
        # Use the delivery date if there is else use date_order and lead time
        date_deadline = self.order_id.date_commitment or self._get_date_planned()
        date_planned = date_deadline - timedelta(
            days=self.order_id.company_id.security_lead
        )
        values.update(
            {
                "group_id": group_id,
                "sale_line_id": self.id,
                "date_planned": date_planned,
                "date_deadline": date_deadline,
                "route_ids": self.route_id,
                "warehouse_id": self.warehouse_id,
                "partner_id": self.order_id.partner_shipping_id.id,
                "location_final_id": self._get_location_final(),
                "product_description_variants": self.with_context(
                    lang=self.order_id.partner_id.lang
                )._get_sale_order_line_multiline_description_variants(),
                "company_id": self.order_id.company_id,
                "sequence": self.sequence,
                "never_product_template_attribute_value_ids": self.product_no_variant_attribute_value_ids,
                "packaging_uom_id": self.product_uom_id,
            }
        )
        return values

    # ------------------------------------------------------------
    # PRODUCT CATALOG MIXIN
    # ------------------------------------------------------------

    def _get_action_add_from_catalog_extra_context(self, order):
        extra_context = super()._get_action_add_from_catalog_extra_context(order)
        extra_context.update(warehouse_id=order.warehouse_id.id)
        return extra_context

    def _get_product_catalog_lines_data(self, **kwargs):
        """Override of `sale` to add the delivered quantity.
        :rtype: dict
        :return: A dict with the following structure:
            {
                'deliveredQty': float,
                'quantity': float,
                'price': float,
                'readOnly': bool,
            }"""
        res = super()._get_product_catalog_lines_data(**kwargs)
        res["deliveredQty"] = sum(
            self.mapped(
                lambda line: line.product_uom_id._compute_quantity(
                    qty=line.qty_transfered,
                    to_unit=line.product_id.uom_id,
                )
            )
        )
        return res

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _check_write_product_uom_qty(self, write_vals):
        # Prevent decreasing below received quantity
        if "product_uom_qty" in write_vals:
            lines = self.filtered(
                lambda l: l.order_id.state == "sale"
                and not l.display_type
                and not l.is_expense
            )
            if not lines:
                return

            product_uom_qty = write_vals.get("product_uom_qty", 0.0)
            precision = self.env["decimal.precision"].precision_get("Product Unit")
            for line in lines:
                if line.product_id.type == "consu":
                    if (
                        float_compare(
                            product_uom_qty,
                            line.qty_transfered,
                            precision_digits=precision,
                        )
                        < 0
                    ):
                        raise UserError(
                            _(
                                "The ordered quantity cannot be decreased below the "
                                "already received quantity.\nCreate a return first."
                            )
                        )
