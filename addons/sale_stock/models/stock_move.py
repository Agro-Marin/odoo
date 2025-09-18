
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"
    sale_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sale Line",
        index="btree_not_null",
    )

    @api.depends("sale_line_id", "sale_line_id.product_uom_id")
    def _compute_packaging_uom_id(self):
        super()._compute_packaging_uom_id()
        for move in self:
            if move.sale_line_id:
                move.packaging_uom_id = move.sale_line_id.product_uom_id

    @api.depends("sale_line_id")
    def _compute_description_picking(self):
        super()._compute_description_picking()
        for move in self:
            if move.sale_line_id and not move.description_picking_manual:
                sale_line_id = move.sale_line_id.with_context(
                    lang=move.sale_line_id.order_id.partner_id.lang
                )
                move.description_picking = (
                    sale_line_id._get_line_multiline_description_variants()
                    + "\n"
                    + move.description_picking
                ).strip()

    def _action_synch_order(self):
        sale_order_lines_vals = []
        for move in self:
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

            if line := sale_order.line_ids.filtered(
                lambda l: l.product_id == product
            ):
                move.sale_line_id = line[:1]
                continue

            quantity = move.quantity
            if move.location_id.usage in ["customer", "transit"]:
                quantity *= -1

            so_line_vals = {
                "move_ids": [(4, move.id, 0)],
                "name": product.display_name,
                "order_id": sale_order.id,
                "product_id": product.id,
                "product_uom_qty": 0,
                "qty_transferred": quantity,
                "product_uom_id": move.product_uom.id,
            }
            so_line = sale_order.line_ids.filtered(
                lambda sol: sol.product_id == product
            )
            if product.invoice_policy == "transfered":
                # Check if there is already a SO line for this product to get
                # back its unit price (in case it was manually updated).
                so_line = sale_order.line_ids.filtered(
                    lambda sol: sol.product_id == product
                )
                if so_line:
                    so_line_vals["price_unit"] = so_line[0].price_unit
            elif product.invoice_policy == "ordered":
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
        return super()._action_synch_order()

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields.append("sale_line_id")
        return distinct_fields

    def _get_related_invoices(self):
        """Overridden from stock_account to return the customer invoices
        related to this stock move.
        """
        rslt = super(StockMove, self)._get_related_invoices()
        invoices = self.mapped("picking_id.sale_id.invoice_ids").filtered(
            lambda x: x.state == "posted"
        )
        rslt += invoices
        # rslt += invoices.mapped('reverse_entry_ids')
        return rslt

    def _get_source_document(self):
        res = super()._get_source_document()
        return self.sale_line_id.order_id or res

    def _get_sale_order_lines(self):
        """Return all possible sale order lines for one stock move."""
        self.ensure_one()
        return (
            self + self.browse(self._rollup_move_origs() | self._rollup_move_dests())
        ).sale_line_id

    def _assign_picking_post_process(self, new=False):
        super(StockMove, self)._assign_picking_post_process(new=new)
        if new:
            picking_id = self.mapped("picking_id")
            sale_order_ids = self.mapped("sale_line_id.order_id")
            for sale_order_id in sale_order_ids:
                picking_id.message_post_with_source(
                    "mail.message_origin_link",
                    render_values={"self": picking_id, "origin": sale_order_id},
                    subtype_xmlid="mail.mt_note",
                )

    def _get_all_related_sm(self, product):
        return super()._get_all_related_sm(product) | self.filtered(
            lambda m: m.sale_line_id.product_id == product
        )

    def _prepare_procurement_values(self):
        res = super()._prepare_procurement_values()
        # to pass sale_line_id fom SO to MO in mto
        if self.sale_line_id:
            res["sale_line_id"] = self.sale_line_id.id
        return res
