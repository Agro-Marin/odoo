from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.orm.utils import SUPERUSER_ID
from odoo.tools.float_utils import float_compare, float_is_zero, float_round
from odoo.tools.translate import _


class PurchaseOrderLine(models.Model):
    "Inherit PurchaseOrderLine"

    _inherit = "purchase.order.line"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    is_storable = fields.Boolean(related="product_id.is_storable")
    qty_transfered_method = fields.Selection(
        ondelete={"stock_move": lambda self: self._ondelete_stock_moves()},
    )
    procurement_group_id = fields.Many2one(
        comodel_name="procurement.group",
        string="Procurement group that generated this line",
    )
    orderpoint_id = fields.Many2one(
        comodel_name="stock.warehouse.orderpoint",
        string="Orderpoint",
        copy=False,
        index="btree_not_null",
    )
    move_dest_ids = fields.Many2many(
        comodel_name="stock.move",
        relation="stock_move_created_purchase_line_rel",
        column1="created_purchase_line_id",
        column2="move_id",
        string="Downstream moves alt",
    )
    location_final_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location from procurement",
    )
    move_ids = fields.One2many(
        comodel_name="stock.move",
        inverse_name="purchase_line_id",
        string="Stock Moves",
        readonly=True,
        copy=False,
    )
    qty_to_transfer = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_transfered",
        store=True,
    )
    product_description_variants = fields.Char("Custom Description")
    propagate_cancel = fields.Boolean(string="Propagate cancellation", default=True)
    forecasted_issue = fields.Boolean(compute="_compute_forecasted_issue")

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def write(self, vals):
        self._check_write_product_qty(vals)
        res = super().write(vals)
        self._write_date_planned(vals)
        return res

    def unlink(self):
        self.move_ids._action_cancel()
        # Unlink move_dests that have other created_purchase_line_ids instead of cancelling them
        for line in self:
            moves_to_unlink = line.move_dest_ids.filtered(
                lambda m: len(m.created_purchase_line_ids.ids) > 1
            )
            if moves_to_unlink:
                moves_to_unlink.created_purchase_line_ids = [Command.unlink(line.id)]

        ppg_cancel_lines = self.filtered(lambda line: line.propagate_cancel)
        ppg_cancel_lines.move_dest_ids._action_cancel()

        not_ppg_cancel_lines = self.filtered(lambda line: not line.propagate_cancel)
        not_ppg_cancel_lines.move_dest_ids.write({"procure_method": "make_to_stock"})
        not_ppg_cancel_lines.move_dest_ids._recompute_state()

        return super().unlink()

    def _ondelete_stock_moves(self):
        modified_fields = ["qty_transfered_method"]
        self.flush_recordset(fnames=["qty_transfered", *modified_fields])
        self.invalidate_recordset(fnames=modified_fields, flush=False)
        query = f"""
            UPDATE {self._table}
            SET qty_transfered_method = 'manual'
            WHERE id IN %(ids)s
        """
        self.env.cr.execute(query, {"ids": self._ids or (None,)})
        self.modified(modified_fields)

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends(
        "product_uom_qty",
        "move_ids.state",
        "move_ids.product_uom",
        "move_ids.quantity",
    )
    def _compute_qty_transfered(self):
        stock_lines = self.filtered(
            lambda line: line.qty_transfered_method == "stock_move"
        )
        super(PurchaseOrderLine, self - stock_lines)._compute_qty_transfered()
        for line in stock_lines:
            vals = {
                "qty_transfered": 0.0,
                "qty_to_transfer": 0.0,
            }

            if line.state != "purchase":
                line.write(vals)
                continue

            vals["qty_to_transfer"] = line.product_uom_qty

            if not line.move_ids:
                line.write(vals)
                continue

            # In case of a BOM in kit, the products delivered do not correspond
            # to the products in the PO. Therefore, we can skip them since they
            # will be handled later on.
            for move in line._get_stock_moves():
                if move._is_purchase_return():
                    if not move.origin_returned_move_id or move.to_refund:
                        vals["qty_transfered"] -= move.product_uom._compute_quantity(
                            move.quantity,
                            line.product_uom_id,
                            rounding_method="HALF-UP",
                        )
                elif (
                    move.origin_returned_move_id
                    and move.origin_returned_move_id._is_dropshipped()
                    and not move._is_dropshipped_returned()
                ):
                    # Edge case: the dropship is returned to the stock, no to the supplier.
                    # In this case, the received quantity on the PO is set although we didn't
                    # receive the product physically in our stock. To avoid counting the
                    # quantity twice, we do nothing.
                    pass

                elif (
                    move.origin_returned_move_id
                    and move.origin_returned_move_id._is_purchase_return()
                    and not move.to_refund
                ):
                    pass

                else:
                    vals["qty_transfered"] += move.product_uom._compute_quantity(
                        move.quantity,
                        line.product_uom_id,
                        rounding_method="HALF-UP",
                    )

            vals["qty_to_transfer"] = max(
                0, vals["qty_to_transfer"] - vals["qty_transfered"]
            )
            line.write(vals)

    @api.depends("product_uom_qty", "date_planned")
    def _compute_forecasted_issue(self):
        for line in self:
            warehouse = line.order_id.picking_type_id.warehouse_id
            line.forecasted_issue = False
            if line.product_id:
                virtual_available = line.product_id.with_context(
                    warehouse_id=warehouse.id, to_date=line.date_planned
                ).virtual_available
                if line.state == "draft":
                    virtual_available += line.product_uom_qty
                if virtual_available < 0:
                    line.forecasted_issue = True

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_product_forecast_report(self):
        self.ensure_one()
        action = self.product_id.action_product_forecast_report()
        action["context"] = {
            "active_id": self.product_id.id,
            "active_model": "product.product",
            "move_to_match_ids": self.move_ids.filtered(
                lambda m: m.product_id == self.product_id
            ).ids,
            "purchase_line_to_match_id": self.id,
        }
        warehouse = self.order_id.picking_type_id.warehouse_id
        if warehouse:
            action["context"]["warehouse_id"] = warehouse.id
        return action

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _create_invoice_activity_smaller_than_qty_invoiced(self):
        """Create an activity on the vendor bill if the quantity on the
        PO is smaller than the invoiced quantity."""
        for line in self.filtered(lambda l: l.product_id.type == "consu"):
            rounding = line.product_uom_id.rounding
            if (
                float_compare(
                    line.product_qty,
                    line.qty_invoiced,
                    precision_rounding=rounding,
                )
                < 0
                and line.invoice_lines
            ):
                # If the quantity is now below the invoiced quantity, create an activity
                # on the vendor bill inviting the user to create a refund.
                line.invoice_lines[0].move_id.activity_schedule(
                    "mail.mail_activity_data_warning",
                    note=_(
                        "The quantities on your purchase order indicate less than billed. "
                        "You should ask for a refund."
                    ),
                )

    def _create_stock_moves(self, picking):
        values = []
        for line in self.filtered(lambda l: not l.display_type):
            for vals in line._prepare_stock_move_vals_list():
                vals["picking_id"] = picking.id
                values.append(vals)
            line.move_dest_ids.created_purchase_line_ids = [Command.clear()]
        return self.env["stock.move"].create(values)

    def _hook_on_created_confirmed_lines(self):
        super()._hook_on_created_confirmed_lines()
        self._update_or_create_picking()

    def _hook_on_written_confirmed_lines(self, write_vals, previous_vals):
        super()._hook_on_written_confirmed_lines(write_vals, previous_vals)
        dp = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self:
            if "price_unit" in write_vals:
                # Avoid updating kit component's stock.move
                moves = line.move_ids.filtered(
                    lambda m: m.state not in ("cancel", "done")
                    and m.product_id == line.product_id
                )
                moves.write({"price_unit": line._get_price_unit()})
            if (
                "product_qty" in write_vals
                and float_compare(
                    previous_vals[line.id].get("product_qty"),
                    line.product_qty,
                    precision_digits=dp,
                )
                > 0
            ):
                line._create_invoice_activity_smaller_than_qty_invoiced()
                line.with_context(
                    previous_product_qty=previous_vals[line.id].get("product_qty", {})
                )._update_or_create_picking()

    def _merge_po_line(self, rfq_line):
        super()._merge_po_line(rfq_line)
        self.move_dest_ids += rfq_line.move_dest_ids

    def _update_date_planned(self, updated_date):
        move_to_update = self.move_ids.filtered(
            lambda m: m.state not in ["done", "cancel"]
        )
        if (
            not self.move_ids or move_to_update
        ):  # Only change the date if there is no move done or none
            super()._update_date_planned(updated_date)
        if move_to_update:
            self._update_stock_move_date_deadline(updated_date)

    def _update_or_create_picking(self):
        """Lines must be prefiltered state == purchase and not display_type and product_id."""
        for line in self.filtered(
            lambda l: l.product_id and l.product_id.type == "consu"
        ):
            if not line.product_qty > line.qty_transfered:
                continue

            # If the user increased quantity of existing line or created a new line
            # Give priority to the pickings related to the line
            line_pickings = line.move_ids.picking_id.filtered(
                lambda p: p.state not in ("done", "cancel")
                and p.location_dest_id.usage in ("internal", "transit", "customer")
            )
            if line_pickings:
                picking = line_pickings[0]
            else:
                pickings = line.order_id.picking_ids.filtered(
                    lambda x: x.state not in ("done", "cancel")
                    and x.location_dest_id.usage in ("internal", "transit", "customer")
                )
                picking = pickings and pickings[0] or False
            if not picking:
                res = line.order_id._prepare_picking_vals()
                picking = self.env["stock.picking"].create(res)

            moves = line._create_stock_moves(picking)
            moves._action_confirm()._action_assign()

    @api.model
    def _update_qty_transfered_method(self):
        """Update qty_transfered_method for old PO before install this module."""
        self.search(["!", ("state", "=", "purchase")])._compute_qty_transfered_method()

    def _update_stock_move_date_deadline(self, new_date):
        """Updates corresponding move picking line deadline dates that are not yet completed."""
        moves_to_update = self.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
        if not moves_to_update:
            moves_to_update = self.move_dest_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            )
        for move in moves_to_update:
            move.date_deadline = new_date

    def _write_date_planned(self, write_vals):
        if write_vals.get("date_planned"):
            new_date = fields.Datetime.to_datetime(write_vals["date_planned"])
            self.filtered(
                lambda l: not l.display_type
            )._update_stock_move_date_deadline(new_date)

    def _get_outgoing_incoming_moves(self):
        outgoing_moves = self.env["stock.move"]
        incoming_moves = self.env["stock.move"]
        moves = self.move_ids.filtered(
            lambda m: m.state != "cancel"
            and not m.scrapped
            and self.product_id == m.product_id
        )

        for move in moves:
            if move._is_purchase_return() and (
                move.to_refund or not move.origin_returned_move_id
            ):
                outgoing_moves |= move
            elif move.location_dest_id.usage != "supplier":
                if not move.origin_returned_move_id or (
                    move.origin_returned_move_id and move.to_refund
                ):
                    incoming_moves |= move
        return outgoing_moves, incoming_moves

    def _get_price_unit(self):
        self.ensure_one()
        order = self.order_id
        price_unit = self.price_unit
        price_unit_prec = self.env["decimal.precision"].precision_get("Product Price")
        if self.tax_ids:
            qty = self.product_qty or 1
            price_unit = self.tax_ids.compute_all(
                price_unit,
                currency=self.order_id.currency_id,
                quantity=qty,
                product=self.product_id,
                partner=self.order_id.partner_id,
                rounding_method="round_globally",
            )["total_void"]
            price_unit = price_unit / qty
        if self.product_uom_id.id != self.product_id.uom_id.id:
            price_unit /= self.product_uom_id.factor
            price_unit *= self.product_id.uom_id.factor
        if order.currency_id != order.company_id.currency_id:
            price_unit = order.currency_id._convert(
                price_unit,
                order.company_id.currency_id,
                self.company_id,
                self.date_order or fields.Date.today(),
                round=False,
            )
        return float_round(price_unit, precision_digits=price_unit_prec)

    def _get_procurement_qty(self):
        self.ensure_one()
        qty = 0.0
        outgoing_moves, incoming_moves = self._get_outgoing_incoming_moves()
        for move in outgoing_moves:
            qty_to_compute = (
                move.quantity if move.state == "done" else move.product_uom_qty
            )
            qty -= move.product_uom._compute_quantity(
                qty_to_compute, self.product_uom_id, rounding_method="HALF-UP"
            )
        for move in incoming_moves:
            qty_to_compute = (
                move.quantity if move.state == "done" else move.product_uom_qty
            )
            qty += move.product_uom._compute_quantity(
                qty_to_compute, self.product_uom_id, rounding_method="HALF-UP"
            )
        return qty

    def _get_stock_moves(self):
        self.ensure_one()
        moves = self.move_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state == "done"
        )
        if self._context.get("accrual_entry_date"):
            moves = moves.filtered(
                lambda r: fields.Date.context_today(r, r.date)
                <= self._context["accrual_entry_date"]
            )
        return moves

    def _get_stock_move_dests_initial_demand(self, move_dests):
        return self.product_id.uom_id._compute_quantity(
            sum(
                move_dests.filtered(
                    lambda m: m.state != "cancel"
                    and m.location_dest_id.usage != "supplier"
                ).mapped("product_qty")
            ),
            self.product_uom_id,
            rounding_method="HALF-UP",
        )

    def _find_candidate(
        self,
        product_id,
        product_qty,
        product_uom,
        location_id,
        name,
        origin,
        company_id,
        values,
    ):
        """Return the record in self where the procurement with values passed as args can
        be merged. If it returns an empty record then a new line will be created."""
        description_picking = ""
        if values.get("product_description_variants"):
            description_picking = values["product_description_variants"]
        lines = self.filtered(
            lambda l: l.propagate_cancel == values["propagate_cancel"]
            and (
                l.orderpoint_id == values["orderpoint_id"]
                if values["orderpoint_id"] and not values["move_dest_ids"]
                else True
            )
        )

        # In case 'product_description_variants' is in the values, we also filter on the PO line
        # name. This way, we can merge lines with the same description. To do so, we need the
        # product name in the context of the PO partner.
        if lines and values.get("product_description_variants"):
            partner = self.mapped("order_id.partner_id")[:1]
            product_lang = product_id.with_context(
                lang=partner.lang,
                partner_id=partner.id,
            )
            name = product_lang.display_name
            if product_lang.description_purchase:
                name += "\n" + product_lang.description_purchase
            lines = lines.filtered(
                lambda l: (l.name == name + "\n" + description_picking)
                or (
                    values.get("product_description_variants")
                    in (product_lang.name, product_id.with_user(SUPERUSER_ID).name)
                    and l.name == name
                )
            )
            if lines:
                return lines[0]

        return lines and lines[0] or self.env["purchase.order.line"]

    def _prepare_stock_move_vals(self, product_uom, product_uom_qty, price_unit):
        self.ensure_one()
        self._check_orderpoint_picking_type()
        product = self.product_id.with_context(
            lang=self.order_id.dest_address_id.lang or self.env.user.lang
        )
        location_dest = self.env["stock.location"].browse(
            self.order_id._get_location_destination()
        )
        location_final = (
            self.location_final_id or self.order_id._get_location_final()
        )
        if location_final and location_final._child_of(location_dest):
            location_dest = location_final
        date_planned = self.date_planned or self.order_id.date_planned
        return {
            # TODO: remove index in master?
            "company_id": self.company_id.id,
            "partner_id": self.order_id.dest_address_id.id,
            "picking_type_id": self.order_id.picking_type_id.id,
            "warehouse_id": self.order_id.picking_type_id.warehouse_id.id,
            "group_id": self.order_id.procurement_group_id.id,
            "location_id": self.order_id.partner_id.property_stock_supplier.id,
            "location_dest_id": location_dest.id,
            "location_final_id": location_final.id,
            "move_dest_ids": [(4, x) for x in self.move_dest_ids.ids],
            "purchase_line_id": self.id,
            "state": "draft",
            "origin": self.order_id.name,
            "propagate_cancel": self.propagate_cancel,
            "description_picking": product.description_pickingin or self.name,
            # truncate to 2000 to avoid triggering index limit error
            "name": (self.product_id.display_name or "")[:2000],
            "sequence": self.sequence,
            "date": date_planned,
            "date_deadline": date_planned,
            "product_id": self.product_id.id,
            "price_unit": price_unit,
            "product_uom_qty": product_uom_qty,
            "product_uom": product_uom.id,
        }

    def _prepare_stock_move_vals_list(self):
        """Prepare the stock moves data for one order line.
        This function returns a list of dictionary ready
        to be used in stock.move's create()"""
        self.ensure_one()
        res = []
        if self.product_id.type != "consu":
            return res

        qty = self._get_procurement_qty()
        move_dests = self.move_dest_ids or self.move_ids.move_dest_ids
        move_dests = move_dests.filtered(
            lambda m: m.state != "cancel" and not m._is_purchase_return()
        )
        if not move_dests:
            qty_to_attach = 0
            qty_to_push = self.product_qty - qty
        else:
            move_dests_initial_demand = self._get_stock_move_dests_initial_demand(
                move_dests
            )
            qty_to_attach = move_dests_initial_demand - qty
            qty_to_push = self.product_qty - move_dests_initial_demand

        price_unit = self._get_price_unit()

        if (
            float_compare(
                qty_to_attach, 0.0, precision_rounding=self.product_uom_id.rounding
            )
            > 0
        ):
            product_uom_qty, product_uom = self.product_uom_id._adjust_uom_quantities(
                qty_to_attach, self.product_id.uom_id
            )
            res.append(
                self._prepare_stock_move_vals(product_uom, product_uom_qty, price_unit)
            )
        if not float_is_zero(
            qty_to_push, precision_rounding=self.product_uom_id.rounding
        ):
            product_uom_qty, product_uom = self.product_uom_id._adjust_uom_quantities(
                qty_to_push, self.product_id.uom_id
            )
            extra_move_vals = self._prepare_stock_move_vals(
                product_uom, product_uom_qty, price_unit
            )
            extra_move_vals["move_dest_ids"] = False  # don't attach
            res.append(extra_move_vals)
        return res

    def _prepare_aml_vals(self, **optional_values):
        res = super()._prepare_aml_vals(**optional_values)
        if "balance" not in res:
            res["balance"] = self.currency_id._convert(
                self.price_unit_discounted_taxexc * (self.qty_transfered or 1),
                self.company_id.currency_id,
                round=False,
            )
        return res

    @api.model
    def _prepare_purchase_order_line_from_procurement(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
        po,
    ):
        supplier = values.get("supplier")
        partner = supplier.partner_id
        uom_po_qty = product_uom._compute_quantity(
            product_qty, product_id.uom_id, rounding_method="HALF-UP"
        )
        # _select_seller is used if the supplier have different price depending
        # the quantities ordered.
        today = fields.Date.today()
        seller = product_id.with_company(company_id)._select_seller(
            partner_id=partner,
            quantity=uom_po_qty,
            date=po.date_order and max(po.date_order.date(), today) or today,
            uom_id=product_id.uom_id,
        )

        if (
            seller
            and (seller.product_uom_id or seller.product_tmpl_id.uom_id) != product_uom
        ):
            uom_po_qty = product_id.uom_id._compute_quantity(
                uom_po_qty,
                seller.product_uom_id or seller.product_tmpl_id.uom_id,
                rounding_method="HALF-UP",
            )

        product_taxes = product_id.supplier_taxes_id.filtered(
            lambda x: x.company_id in company_id.parent_ids
        )
        taxes = po.fiscal_position_id.map_tax(product_taxes)
        if seller:
            price_unit = (
                (seller.product_uom_id or seller.product_tmpl_id.uom_id)._compute_price(
                    seller.price, product_uom
                )
                if product_uom
                else seller.price
            )
            price_unit = self.env["account.tax"]._fix_tax_included_price_company(
                price_unit, product_taxes, taxes, company_id
            )
        else:
            price_unit = 0
        if (
            price_unit
            and seller
            and po.currency_id
            and seller.currency_id != po.currency_id
        ):
            price_unit = seller.currency_id._convert(
                price_unit,
                po.currency_id,
                po.company_id,
                po.date_order or fields.Date.today(),
            )

        product_lang = product_id.with_prefetch().with_context(
            lang=partner.lang,
            partner_id=partner.id,
        )
        name = product_lang.with_context(seller_id=seller.id).display_name
        if product_lang.description_purchase:
            name += "\n" + product_lang.description_purchase
        discount = seller.discount or 0.0
        res = {
            "order_id": po.id,
            "name": name,
            "product_id": product_id.id,
            "product_uom_id": seller.product_uom_id.id or product_uom.id,
            "product_qty": uom_po_qty,
            "price_unit": price_unit,
            "discount": discount,
            "tax_ids": [(6, 0, taxes.ids)],
        }

        # We need to keep the vendor name set in _prepare_purchase_order_line. To avoid redundancy
        # in the line name, we add the line_description only if different from the product name.
        # This way, we shoud not lose any valuable information.
        line_description = ""
        if values.get("product_description_variants"):
            line_description = values["product_description_variants"]
        if line_description and product_id.name != line_description:
            res["name"] += "\n" + line_description
        res["product_description_variants"] = values.get("product_description_variants")
        res["move_dest_ids"] = [(4, x.id) for x in values.get("move_dest_ids", [])]
        res["location_final_id"] = location_dest_id.id
        res["orderpoint_id"] = (
            values.get("orderpoint_id", False) and values.get("orderpoint_id").id
        )
        res["product_no_variant_attribute_value_ids"] = values.get(
            "never_product_template_attribute_value_ids"
        )
        res["date_planned"] = values.get("date_planned")
        res["propagate_cancel"] = values.get("propagate_cancel")

        # Need to attach purchase order to procurement group for mtso
        group = values.get("group_id")
        if group and not res["move_dest_ids"]:
            res["procurement_group_id"] = group.id
        return res

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _check_orderpoint_picking_type(self):
        warehouse_loc = self.order_id.picking_type_id.warehouse_id.view_location_id
        dest_loc = self.move_dest_ids.location_id or self.orderpoint_id.location_id
        if (
            warehouse_loc
            and dest_loc
            and dest_loc.warehouse_id
            and not warehouse_loc.parent_path in dest_loc[0].parent_path
        ):
            raise UserError(
                _(
                    "The warehouse of operation type (%(operation_type)s) is "
                    "inconsistent with location (%(location)s) of reordering rule "
                    "(%(reordering_rule)s) for product %(product)s. "
                    "Change the operation type or cancel the request for quotation.",
                    product=self.product_id.display_name,
                    operation_type=self.order_id.picking_type_id.display_name,
                    location=self.orderpoint_id.location_id.display_name,
                    reordering_rule=self.orderpoint_id.display_name,
                )
            )

    def _check_write_product_qty(self, write_vals):
        # Prevent decreasing below received quantity
        if "product_qty" in write_vals:
            lines = self.filtered(
                lambda l: l.order_id.state == "purchase"
                and not l.display_type
                and l.product_id
                and l.product_id.type == "consu"
            )
            if not lines:
                return

            product_qty = write_vals.get("product_qty", 0.0)
            precision = self.env["decimal.precision"].precision_get("Product Unit")
            for line in lines:
                if (
                    float_compare(
                        product_qty,
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
