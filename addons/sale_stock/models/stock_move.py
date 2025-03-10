from odoo import api, fields, models


class StockMove(models.Model):
    "Inherit StockMove"

    _inherit = "stock.move"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sale Line",
        ondelete="set null",
        index="btree_not_null",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("sale_line_id", "sale_line_id.product_uom_id")
    def _compute_packaging_uom_id(self):
        super()._compute_packaging_uom_id()
        for move in self:
            if move.sale_line_id:
                move.packaging_uom_id = move.sale_line_id.product_uom_id

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _assign_picking_post_process(self, new=False):
        super()._assign_picking_post_process(new=new)
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

    def _get_sale_order_lines(self):
        """Return all possible sale order lines for one stock move."""
        self.ensure_one()
        return (
            self + self.browse(self._rollup_move_origs() | self._rollup_move_dests())
        ).sale_line_id

    def _get_related_invoices(self):
        """Overridden from stock_account to return the customer invoices
        related to this stock move.
        """
        rslt = super()._get_related_invoices()
        invoices = self.mapped("picking_id.sale_id.invoice_ids").filtered(
            lambda x: x.state == "posted"
        )
        rslt += invoices
        return rslt

    def _get_source_document(self):
        res = super()._get_source_document()
        return self.sale_line_id.order_id or res

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields.append("sale_line_id")
        return distinct_fields
