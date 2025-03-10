from odoo import api, fields, models
from odoo.tools.sql import column_exists, create_column


class StockPicking(models.Model):
    "Inherit StockPicking"

    _inherit = "stock.picking"

    # ------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------

    def _auto_init(self):
        """
        Create related field here, too slow
        when computing it afterwards through _compute_related.

        Since group_id.sale_id is created in this module,
        no need for an UPDATE statement.
        """
        if not column_exists(self.env.cr, "stock_picking", "sale_id"):
            create_column(self.env.cr, "stock_picking", "sale_id", "int4")
        return super()._auto_init()

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        compute="_compute_sale_id",
        store=True,
        inverse="_set_sale_id",
        index="btree_not_null",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("group_id")
    def _compute_sale_id(self):
        for picking in self:
            picking.sale_id = picking.group_id.sale_id

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _set_sale_id(self):
        if self.group_id:
            self.group_id.sale_id = self.sale_id
        else:
            if self.sale_id:
                vals = {
                    "sale_id": self.sale_id.id,
                    "name": self.sale_id.name,
                }
            else:
                vals = {}

            pg = self.env["procurement.group"].create(vals)
            self.group_id = pg

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def _action_done(self):
        res = super()._action_done()
        sale_order_lines_vals = []
        for move in self.move_ids:
            sale_order = move.picking_id.sale_id
            # Creates new SO line only when pickings linked to a sale order and
            # for moves with qty. done and not already linked to a SO line.
            if (
                not sale_order
                or move.sale_line_id
                or not move.picked
                or not (
                    (
                        move.location_dest_id.usage in ["customer", "transit"]
                        and not move.move_dest_ids
                    )
                    or (move.location_id.usage == "customer" and move.to_refund)
                )
            ):
                continue

            product = move.product_id
            quantity = move.quantity
            if move.to_refund:
                quantity *= -1

            so_line_vals = {
                "move_ids": [(4, move.id, 0)],
                "name": product.display_name,
                "order_id": sale_order.id,
                "product_id": product.id,
                "product_uom_qty": 0,
                "qty_transfered": quantity,
                "product_uom_id": move.product_uom.id,
            }
            so_line = sale_order.line_ids.filtered(
                lambda sol: sol.product_id == product
            )
            if product.invoice_policy == "delivery":
                # Check if there is already a SO line for this product to get
                # back its unit price (in case it was manually updated).
                if so_line:
                    so_line_vals["price_unit"] = so_line[0].price_unit
            elif product.invoice_policy == "order":
                # No unit price if the product is invoiced on the ordered qty.
                so_line_vals["price_unit"] = 0
            # New lines should be added at the bottom of the SO (higher sequence number)
            if not so_line:
                so_line_vals["sequence"] = (
                    max(sale_order.line_ids.mapped("sequence"))
                    + len(sale_order_lines_vals)
                    + 1
                )
            sale_order_lines_vals.append(so_line_vals)

        if sale_order_lines_vals:
            self.env["sale.order.line"].with_context(skip_procurement=True).create(
                sale_order_lines_vals
            )
        return res

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _log_less_quantities_than_expected(self, moves):
        """Log an activity on sale order that are linked to moves. The
        note summarize the real processed quantity and promote a
        manual action.

        :param dict moves: a dict with a move as key and tuple with
        new and old quantity as value. eg: {move_1 : (4, 5)}
        """

        def _keys_in_groupby(sale_line):
            """group by order_id and the sale_person on the order"""
            return (sale_line.order_id, sale_line.order_id.user_id)

        def _render_note_exception_quantity(moves_information):
            """Generate a note with the picking on which the action
            occurred and a summary on impacted quantity that are
            related to the sale order where the note will be logged.

            :param moves_information dict:
            {'move_id': ['sale_order_line_id', (new_qty, old_qty)], ..}

            :return: an html string with all the information encoded.
            :rtype: str
            """
            origin_moves = self.env["stock.move"].browse(
                [
                    move.id
                    for move_orig in moves_information.values()
                    for move in move_orig[0]
                ]
            )
            origin_picking = origin_moves.mapped("picking_id")
            values = {
                "origin_moves": origin_moves,
                "origin_picking": origin_picking,
                "moves_information": moves_information.values(),
            }
            return self.env["ir.qweb"]._render(
                "sale_stock.exception_on_picking", values
            )

        documents = self.sudo()._log_activity_get_documents(
            moves, "sale_line_id", "DOWN", _keys_in_groupby
        )
        self._log_activity(_render_note_exception_quantity, documents)

        return super()._log_less_quantities_than_expected(moves)

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _can_return(self):
        self.ensure_one()
        return super()._can_return() or self.sale_id
